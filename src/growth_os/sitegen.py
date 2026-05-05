from __future__ import annotations

import argparse
import html
import json
import math
import shutil
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import get_site, project_path


def slug_to_path(article: dict[str, Any]) -> str:
    return f"/haber/{article['slug']}/"


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def category_name(site: dict[str, Any], slug: str) -> str:
    for category in site["categories"]:
        if category["slug"] == slug:
            return category["name"]
    return slug.replace("-", " ").title()


def read_articles(site: dict[str, Any]) -> list[dict[str, Any]]:
    content_file = project_path(site["content_file"])
    with content_file.open("r", encoding="utf-8") as handle:
        articles = json.load(handle)
    published = [article for article in articles if article.get("status", "published") == "published"]
    return sorted(published, key=lambda item: item["published_at"], reverse=True)


def article_json_ld(site: dict[str, Any], article: dict[str, Any]) -> str:
    base = site["base_url"].rstrip("/")
    data = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": article["title"],
        "description": article["summary"],
        "datePublished": article["published_at"],
        "dateModified": article.get("modified_at", article["published_at"]),
        "author": {"@type": "Organization", "name": article["author"]},
        "publisher": {
            "@type": "Organization",
            "name": site["name"],
            "logo": {"@type": "ImageObject", "url": f"{base}/assets/images/logo.png"},
        },
        "image": [f"{base}{article['image']}"],
        "mainEntityOfPage": f"{base}{slug_to_path(article)}",
    }
    if article.get("source_url"):
        data["citation"] = article["source_url"]
        data["isBasedOn"] = article["source_url"]
    return json.dumps(data, ensure_ascii=False)


def layout(site: dict[str, Any], title: str, description: str, body: str, canonical_path: str, extra_head: str = "") -> str:
    theme = site["theme"]
    base = site["base_url"].rstrip("/")
    nav = "\n".join(
        f'<a href="/kategori/{esc(cat["slug"])}/">{esc(cat["name"])}</a>'
        for cat in site["categories"]
    )
    return f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(description)}">
  <link rel="canonical" href="{base}{canonical_path}">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:type" content="website">
  <meta property="og:url" content="{base}{canonical_path}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="theme-color" content="{theme["primary"]}">
  <link rel="preload" href="/assets/styles.css" as="style">
  <link rel="stylesheet" href="/assets/styles.css">
  {extra_head}
</head>
<body>
  <header class="site-header">
    <a class="brand" href="/" aria-label="{esc(site["name"])} ana sayfa">
      <span class="brand-mark">TG</span>
      <span>{esc(site["name"])}</span>
    </a>
    <nav class="top-nav" aria-label="Kategoriler">{nav}</nav>
  </header>
  <main>{body}</main>
  <footer class="site-footer">
    <strong>{esc(site["name"])}</strong>
    <span>Bağımsız, hızlı, doğrulanabilir haber yayını.</span>
    <a href="/robots.txt">robots.txt</a>
    <a href="/sitemap.xml">sitemap.xml</a>
    <a href="/llms.txt">llms.txt</a>
  </footer>
</body>
</html>
"""


def render_index(site: dict[str, Any], articles: list[dict[str, Any]]) -> str:
    lead = articles[0]
    lead_img = esc(lead["image"])
    cards = "\n".join(render_card(article, site) for article in articles[1:])
    latest = "\n".join(
        f'<li><time>{esc(article["published_at"][11:16])}</time><a href="{slug_to_path(article)}">{esc(article["title"])}</a></li>'
        for article in articles[:8]
    )
    body = f"""
<section class="news-shell">
  <div class="lead-story">
    <a href="{slug_to_path(lead)}">
      <img src="{lead_img}" alt="{esc(lead["image_alt"])}" width="1200" height="760" fetchpriority="high">
      <span class="kicker">{esc(category_name(site, lead["category"]).upper())}</span>
      <h1>{esc(lead["title"])}</h1>
      <p>{esc(lead["summary"])}</p>
    </a>
  </div>
  <aside class="latest-strip" aria-label="Son haberler">
    <h2>Son Haberler</h2>
    <ol>{latest}</ol>
  </aside>
</section>
<section class="story-grid" aria-label="Gündem akışı">
  {cards}
</section>
"""
    return layout(site, f"{site['name']} | Son Dakika ve Gündem Haberleri", "Türkiye ve dünyadan son dakika, gündem, ekonomi, teknoloji ve spor haberleri.", body, "/")


def render_card(article: dict[str, Any], site: dict[str, Any] | None = None) -> str:
    category = category_name(site, article["category"]) if site else article["category"].replace("-", " ").title()
    return f"""
<article class="story-card">
  <a href="{slug_to_path(article)}">
    <img src="{esc(article["image"])}" alt="{esc(article["image_alt"])}" width="720" height="456" loading="lazy">
    <span>{esc(category.upper())}</span>
    <h2>{esc(article["title"])}</h2>
    <p>{esc(article["summary"])}</p>
  </a>
</article>
"""


def render_article(site: dict[str, Any], article: dict[str, Any], related: list[dict[str, Any]]) -> str:
    paragraphs = "\n".join(f"<p>{esc(text)}</p>" for text in article["body"])
    tags = "\n".join(f"<a href=\"/etiket/{esc(tag)}/\">#{esc(tag)}</a>" for tag in article.get("tags", []))
    related_html = "\n".join(render_card(item, site) for item in related[:3])
    source_html = ""
    if article.get("source_url"):
        source_name = article.get("source_name") or "Kaynak"
        source_html = f"""
  <aside class="source-box">
    <strong>Kaynak:</strong>
    <a href="{esc(article["source_url"])}" target="_blank" rel="noopener noreferrer nofollow">{esc(source_name)}</a>
  </aside>
"""
    extra = f"""
  <meta property="og:type" content="article">
  <meta property="og:image" content="{site['base_url'].rstrip('/')}{esc(article['image'])}">
  <script type="application/ld+json">{article_json_ld(site, article)}</script>
"""
    body = f"""
<article class="article-layout">
  <header class="article-head">
    <span class="kicker">{esc(category_name(site, article["category"]).upper())}</span>
    <h1>{esc(article["title"])}</h1>
    <p>{esc(article["summary"])}</p>
    <div class="byline">
      <span>{esc(article["author"])}</span>
      <time datetime="{esc(article["published_at"])}">{esc(article["published_at"].replace("T", " ")[:16])}</time>
    </div>
  </header>
  <img class="article-image" src="{esc(article["image"])}" alt="{esc(article["image_alt"])}" width="1200" height="760" fetchpriority="high">
  <div class="article-body">{paragraphs}</div>
  {source_html}
  <nav class="tag-list" aria-label="Etiketler">{tags}</nav>
</article>
<section class="story-grid compact" aria-label="İlgili haberler">
  {related_html}
</section>
"""
    return layout(site, f"{article['title']} - {site['name']}", article["summary"], body, slug_to_path(article), extra)


def render_category(site: dict[str, Any], category: dict[str, str], articles: list[dict[str, Any]]) -> str:
    items = [article for article in articles if article["category"] == category["slug"]]
    cards = "\n".join(render_card(article, site) for article in items) or "<p>Bu kategoride henüz haber yok.</p>"
    body = f"""
<section class="section-head">
  <h1>{esc(category["name"])}</h1>
  <p>{esc(site["name"])} {esc(category["name"])} haberleri.</p>
</section>
<section class="story-grid">{cards}</section>
"""
    return layout(site, f"{category['name']} Haberleri - {site['name']}", f"{category['name']} kategorisinden son haberler.", body, f"/kategori/{category['slug']}/")


def xml_escape(value: str) -> str:
    return esc(value)


def render_sitemap(site: dict[str, Any], articles: list[dict[str, Any]]) -> str:
    base = site["base_url"].rstrip("/")
    now = datetime.now(timezone.utc).isoformat()
    urls = [("/", now)]
    urls.extend((f"/kategori/{cat['slug']}/", now) for cat in site["categories"])
    urls.extend((slug_to_path(article), article.get("modified_at", article["published_at"])) for article in articles)
    body = "\n".join(
        f"  <url><loc>{xml_escape(base + path)}</loc><lastmod>{xml_escape(lastmod)}</lastmod><changefreq>always</changefreq><priority>0.8</priority></url>"
        for path, lastmod in urls
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}\n</urlset>\n'


def render_news_sitemap(site: dict[str, Any], articles: list[dict[str, Any]]) -> str:
    base = site["base_url"].rstrip("/")
    items = "\n".join(
        f"""  <url>
    <loc>{xml_escape(base + slug_to_path(article))}</loc>
    <news:news>
      <news:publication><news:name>{xml_escape(site["name"])}</news:name><news:language>tr</news:language></news:publication>
      <news:publication_date>{xml_escape(article["published_at"])}</news:publication_date>
      <news:title>{xml_escape(article["title"])}</news:title>
    </news:news>
  </url>"""
        for article in articles[:1000]
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">\n{items}\n</urlset>\n'


def render_css(site: dict[str, Any]) -> str:
    theme = site["theme"]
    return f"""
:root {{
  --primary: {theme["primary"]};
  --accent: {theme["accent"]};
  --ink: {theme["ink"]};
  --paper: {theme["paper"]};
  --muted: {theme["muted"]};
  --line: #d0d5dd;
  color-scheme: light;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: Arial, Helvetica, sans-serif;
  color: var(--ink);
  background: var(--paper);
  line-height: 1.5;
}}
a {{ color: inherit; text-decoration: none; }}
img {{ display: block; max-width: 100%; height: auto; background: #e4e7ec; }}
.site-header {{
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 14px max(20px, calc((100vw - 1180px) / 2));
  background: rgba(250, 250, 250, .96);
  border-bottom: 1px solid var(--line);
}}
.brand {{
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 21px;
  font-weight: 800;
}}
.brand-mark {{
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 6px;
  background: var(--primary);
  color: #fff;
  font-size: 15px;
}}
.top-nav {{
  display: flex;
  gap: 16px;
  overflow-x: auto;
  white-space: nowrap;
  font-size: 14px;
  color: #344054;
}}
.top-nav a:hover {{ color: var(--accent); }}
.news-shell {{
  display: grid;
  grid-template-columns: minmax(0, 1.9fr) minmax(280px, .85fr);
  gap: 28px;
  width: min(1180px, calc(100vw - 32px));
  margin: 24px auto;
}}
.lead-story, .latest-strip, .story-card {{
  border-bottom: 1px solid var(--line);
}}
.lead-story img {{
  aspect-ratio: 16 / 10;
  object-fit: cover;
}}
.kicker, .story-card span {{
  display: inline-block;
  margin-top: 12px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0;
}}
.lead-story h1 {{
  margin: 8px 0 8px;
  font-size: clamp(30px, 4vw, 54px);
  line-height: 1.05;
  letter-spacing: 0;
}}
.lead-story p, .article-head p {{
  color: #344054;
  font-size: 18px;
  margin: 0 0 18px;
}}
.latest-strip h2 {{
  margin: 0 0 12px;
  font-size: 20px;
}}
.latest-strip ol {{
  list-style: none;
  padding: 0;
  margin: 0;
}}
.latest-strip li {{
  display: grid;
  grid-template-columns: 48px 1fr;
  gap: 10px;
  padding: 12px 0;
  border-top: 1px solid var(--line);
}}
.latest-strip time {{
  color: var(--primary);
  font-weight: 700;
  font-size: 13px;
}}
.story-grid {{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 22px;
  width: min(1180px, calc(100vw - 32px));
  margin: 28px auto;
}}
.story-grid.compact {{
  margin-top: 10px;
}}
.story-card img {{
  aspect-ratio: 16 / 10;
  object-fit: cover;
}}
.story-card h2 {{
  margin: 7px 0;
  font-size: 21px;
  line-height: 1.2;
  letter-spacing: 0;
}}
.story-card p {{
  color: #475467;
  margin: 0 0 16px;
}}
.article-layout, .section-head {{
  width: min(820px, calc(100vw - 32px));
  margin: 28px auto;
}}
.article-head h1, .section-head h1 {{
  margin: 8px 0 12px;
  font-size: clamp(32px, 5vw, 58px);
  line-height: 1.05;
  letter-spacing: 0;
}}
.byline {{
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  color: var(--muted);
  font-size: 14px;
  border-top: 1px solid var(--line);
  padding-top: 14px;
}}
.article-image {{
  width: 100%;
  aspect-ratio: 16 / 10;
  object-fit: cover;
  margin: 22px 0;
}}
.article-body p {{
  font-size: 19px;
  margin: 0 0 18px;
}}
.source-box {{
  margin: 0 0 18px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  color: #344054;
  background: #fff;
}}
.source-box a {{
  color: var(--primary);
  font-weight: 700;
}}
.tag-list {{
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 24px;
  padding-top: 18px;
  border-top: 1px solid var(--line);
  color: var(--primary);
  font-weight: 700;
}}
.site-footer {{
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  padding: 28px 16px;
  margin-top: 40px;
  border-top: 1px solid var(--line);
  color: #475467;
  font-size: 14px;
}}
@media (max-width: 820px) {{
  .site-header {{ align-items: flex-start; flex-direction: column; }}
  .news-shell {{ grid-template-columns: 1fr; }}
  .story-grid {{ grid-template-columns: 1fr; }}
  .lead-story h1 {{ font-size: 34px; }}
}}
"""


def write_png(path: Path, colors: tuple[tuple[int, int, int], tuple[int, int, int]]) -> None:
    width, height = 1200, 760
    rows = []
    for y in range(height):
        row = bytearray([0])
        mix_y = y / max(1, height - 1)
        for x in range(width):
            wave = (math.sin((x / width) * math.pi * 4 + mix_y * 3) + 1) / 2
            mix = min(1, max(0, (mix_y * 0.72) + (wave * 0.28)))
            r = int(colors[0][0] * (1 - mix) + colors[1][0] * mix)
            g = int(colors[0][1] * (1 - mix) + colors[1][1] * mix)
            b = int(colors[0][2] * (1 - mix) + colors[1][2] * mix)
            row.extend([r, g, b])
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(name: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def generate(site_id: str) -> Path:
    site = get_site(site_id)
    if site["type"] != "new_static_portal":
        raise SystemExit(f"{site_id} is not a static portal site.")
    articles = read_articles(site)
    public_dir = project_path(site["public_dir"])
    (public_dir / "assets" / "images").mkdir(parents=True, exist_ok=True)
    for generated_dir in ("haber", "kategori"):
        target = (public_dir / generated_dir).resolve()
        public_root = public_dir.resolve()
        if target.exists() and public_root in target.parents:
            shutil.rmtree(target)
    for generated_file in ("index.html", "sitemap.xml", "news-sitemap.xml", "robots.txt", "llms.txt"):
        target = public_dir / generated_file
        if target.exists():
            target.unlink()
    (public_dir / "haber").mkdir(parents=True, exist_ok=True)
    (public_dir / "kategori").mkdir(parents=True, exist_ok=True)
    (public_dir / "assets" / "styles.css").write_text(render_css(site), encoding="utf-8")
    (public_dir / "index.html").write_text(render_index(site, articles), encoding="utf-8")
    for article in articles:
        out_dir = public_dir / "haber" / article["slug"]
        out_dir.mkdir(parents=True, exist_ok=True)
        related = [item for item in articles if item["slug"] != article["slug"] and item["category"] == article["category"]]
        if len(related) < 3:
            related += [item for item in articles if item["slug"] != article["slug"] and item not in related]
        (out_dir / "index.html").write_text(render_article(site, article, related), encoding="utf-8")
    for category in site["categories"]:
        out_dir = public_dir / "kategori" / category["slug"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(render_category(site, category, articles), encoding="utf-8")
    (public_dir / "sitemap.xml").write_text(render_sitemap(site, articles), encoding="utf-8")
    (public_dir / "news-sitemap.xml").write_text(render_news_sitemap(site, articles), encoding="utf-8")
    (public_dir / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {site['base_url'].rstrip()}/sitemap.xml\nSitemap: {site['base_url'].rstrip()}/news-sitemap.xml\n",
        encoding="utf-8",
    )
    (public_dir / "llms.txt").write_text(
        f"# {site['name']}\n\nTürkiye odaklı haber yayını. Ana kategoriler: "
        + ", ".join(cat["name"] for cat in site["categories"])
        + ".\n",
        encoding="utf-8",
    )
    palette = {
        "ankara.png": ((15, 76, 129), (230, 240, 250)),
        "ekonomi.png": ((24, 100, 88), (237, 247, 242)),
        "teknoloji.png": ((67, 56, 202), (238, 242, 255)),
        "logo.png": ((15, 76, 129), (180, 35, 24)),
    }
    for name, colors in palette.items():
        path = public_dir / "assets" / "images" / name
        if not path.exists():
            write_png(path, colors)
    return public_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate static news portal files.")
    parser.add_argument("--site", default="turkiye-gundemi")
    args = parser.parse_args(argv)
    out = generate(args.site)
    print(f"Generated: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
