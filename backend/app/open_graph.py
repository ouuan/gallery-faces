"""Site-wide sharing metadata, rendered before any browser JavaScript runs."""
from html import escape


def render_open_graph(config: dict, locale: str = "zh") -> str:
    suffix = "_ja" if locale == "ja" else ""
    title = config.get(f"og_title{suffix}") or config["site_title"]
    properties = {
        "og:type": "website",
        "og:site_name": config["site_title"],
        "og:title": title,
        "og:locale": "ja_JP" if locale == "ja" else "zh_CN",
        "og:description": config.get(f"og_description{suffix}", ""),
        "og:image": config.get(f"og_image{suffix}", ""),
        "og:url": config.get(f"og_url{suffix}", ""),
    }
    return "\n".join(
        f'<meta property="{key}" content="{escape(value, quote=True)}">'
        for key, value in properties.items() if value
    )
