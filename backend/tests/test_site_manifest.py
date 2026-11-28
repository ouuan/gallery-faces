from test_workflows import client


def test_public_manifest_uses_site_title(client):
    config = client.get('/api/v1/admin/settings').json()
    title = '照片 & Gallery'
    assert client.put('/api/v1/admin/settings', json={**config, 'site_title': title}).is_success
    client.cookies.clear()
    response = client.get('/api/v1/site/manifest.webmanifest')
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/manifest+json'
    manifest = response.json()
    assert manifest['name'] == manifest['short_name'] == title
    assert manifest['id'] == manifest['start_url'] == manifest['scope'] == '/'
    assert manifest['display'] == 'standalone'
    assert manifest['icons'][0]['src'].startswith('data:image/svg+xml,')
    entries = {'/daily', '/random', '/heatmap', '/face-game', '/history-quiz'}
    assert {shortcut['url'] for shortcut in manifest['shortcuts']} == entries
    for shortcut in manifest['shortcuts']:
        path = shortcut['url']
        page = client.get('/api/v1/site/manifest.webmanifest', params={'entry': path[1:]}).json()
        assert page['id'] == page['start_url'] == page['scope'] == path
        assert page['short_name'] == shortcut['name']
        assert page['name'] == f"{title} · {shortcut['name']}"
    posts = client.get('/api/v1/site/manifest.webmanifest?entry=posts').json()
    assert posts['start_url'] == '/' and 'shortcuts' not in posts
