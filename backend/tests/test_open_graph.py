from html.parser import HTMLParser

import pytest

from app import db, main
from test_workflows import client


class Metadata(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.properties = {}
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        attrs = dict(attrs)
        if tag == "meta" and "property" in attrs:
            assert attrs["property"] not in self.properties
            self.properties[attrs["property"]] = attrs["content"]


def save(client, **values):
    config = client.get("/api/v1/admin/settings").json()
    return client.put("/api/v1/admin/settings", json={**config, **values})


def test_defaults_migration_and_older_clients(client):
    assert save(client, og_title="Saved title").status_code == 200
    with db.connect(True) as conn:
        conn.execute("DELETE FROM settings WHERE key='og_description_ja'")
    db.init()
    config = client.get("/api/v1/admin/settings").json()
    assert config["og_description_ja"] == ""
    assert config["og_title"] == "Saved title"
    old_config = {key: value for key, value in config.items() if not key.startswith("og_")}
    assert client.put("/api/v1/admin/settings", json=old_config).status_code == 200
    assert client.get("/api/v1/admin/settings").json()["og_title"] == "Saved title"
    assert save(client, og_title="   ", site_title="My gallery").status_code == 200
    client.cookies.clear()
    response = client.get("/api/v1/site/open-graph")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert Metadata(response.text).properties == {
        "og:type": "website", "og:site_name": "My gallery",
        "og:title": "My gallery", "og:locale": "zh_CN",
    }
    assert client.put("/api/v1/admin/settings", json=old_config).status_code == 401


def test_localized_metadata_escaping_and_clearing(client, monkeypatch, tmp_path):
    title = '\"><script>alert("x")</script> & 照片'
    assert save(client, og_title=title, og_description=" 中文说明 ",
                og_image="https://example.com/share.jpg?a=1&b=2",
                og_url="https://zh.example.com/", og_title_ja="投稿一覧",
                og_description_ja="日本語の説明", og_url_ja="https://ja.example.com/",
                og_image_ja="https://example.com/ja.jpg").status_code == 200
    fragment = client.get("/api/v1/site/open-graph").text
    parsed = Metadata(fragment)
    assert set(parsed.tags) == {"meta"}
    assert parsed.properties["og:title"] == title
    assert parsed.properties["og:description"] == "中文说明"
    assert parsed.properties["og:image"] == "https://example.com/share.jpg?a=1&b=2"
    japanese = Metadata(client.get("/api/v1/site/open-graph?locale=ja").text).properties
    assert japanese["og:title"] == "投稿一覧"
    assert japanese["og:description"] == "日本語の説明"
    assert japanese["og:image"] == "https://example.com/ja.jpg"
    assert japanese["og:url"] == "https://ja.example.com/"
    assert japanese["og:locale"] == "ja_JP"
    assert client.get("/api/v1/site/open-graph?locale=other").status_code == 422
    # Exercise the actual SPA response without relying on a pre-existing build.
    (tmp_path / "index.html").write_text('<html><head><!--open-graph--></head><body>App</body></html>')
    monkeypatch.setattr(main, "static", tmp_path)
    from fastapi import Request
    request = Request({"type": "http", "method": "GET", "path": "/posts"})
    response = main.spa(request, "posts")
    assert Metadata(response.body.decode()).properties == parsed.properties
    assert response.headers["cache-control"] == "no-store"
    assert save(client, og_title="", og_description="", og_image="", og_url="").status_code == 200
    properties = Metadata(main.spa(request, "").body.decode()).properties
    assert properties["og:title"] == "Gallery Faces"
    assert "og:image" not in properties and "og:description" not in properties and "og:url" not in properties
    assert Metadata(client.get("/api/v1/site/open-graph?locale=ja").text).properties == japanese


@pytest.mark.parametrize("field,value", [
    ("og_image", "javascript:alert(1)"), ("og_url", "/relative"),
    ("og_image_ja", "data:image/png;base64,abc"), ("og_url_ja", "ftp://example.com"),
    ("og_image", "https://user:password@example.com/image.jpg"),
    ("og_url", "https://exa mple.com"), ("og_title", "a" * 101),
    ("og_description_ja", "a" * 501), ("og_url_ja", "https://example.com/" + "a" * 2048),
])
def test_invalid_settings_are_atomic(client, field, value):
    response = save(client, **{field: value, "site_title": "Must not persist"})
    assert response.status_code == 422
    assert client.get("/api/v1/admin/settings").json()["site_title"] == "Gallery Faces"
