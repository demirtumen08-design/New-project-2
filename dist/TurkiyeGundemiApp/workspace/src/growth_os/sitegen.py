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


def article_image(article: dict[str, Any]) -> str:
    image = str(article.get("image") or "").strip()
    fallback = {
        "son-dakika": "/assets/images/son-dakika.png",
        "gundem": "/assets/images/ankara.png",
        "ekonomi": "/assets/images/ekonomi.png",
        "dunya": "/assets/images/dunya.png",
        "teknoloji": "/assets/images/teknoloji.png",
        "spor": "/assets/images/spor.png",
        "kultur": "/assets/images/kultur.png",
    }.get(str(article.get("category") or ""), "/assets/images/ankara.png")
    if not image or image == "/assets/images/ankara.png":
        return fallback
    return image


def article_time(article: dict[str, Any]) -> str:
    published = str(article.get("published_at") or "")
    if "T" in published and len(published) >= 16:
        return published[11:16]
    return published[:16]


def articles_for_category(articles: list[dict[str, Any]], category: str, limit: int = 4) -> list[dict[str, Any]]:
    return [article for article in articles if article.get("category") == category][:limit]


def render_ticker(articles: list[dict[str, Any]]) -> str:
    items = "\n".join(
        f'<a href="{slug_to_path(article)}">{esc(article["title"])}</a>'
        for article in articles[:6]
    )
    if not items:
        items = "<span>Güncel haber akışı hazırlanıyor.</span>"
    return f"""
  <div class="breaking-bar" aria-label="Son dakika haberleri">
    <strong>Son Dakika</strong>
    <div class="breaking-track">{items}</div>
  </div>
"""


STATIC_PAGES: list[dict[str, Any]] = [
    {
        "slug": "hakkimizda",
        "title": "Hakkımızda",
        "description": "Türkiye Gündemi yayın ilkeleri ve haber yaklaşımı.",
        "body": [
            "Türkiye Gündemi, Türkiye ve dünyadan gelişmeleri hızlı, anlaşılır ve kaynaklı biçimde okura ulaştırmak için kurulan dijital haber yayınıdır.",
            "Yayın akışında doğrulanabilir bilgi, açık kaynak gösterimi, sade haber dili ve editoryal denetim esastır. Haber robotu yalnızca kaynak sinyallerini derler; yayın standardı ve son sorumluluk editoryal kontroldedir.",
            "Sitede yer alan otomatik içerikler, kaynak bağlantısı ve haber değeri kontrolünden geçecek şekilde kurgulanır. Uygun görülmeyen servis, ilan, arama sayfası ve düşük kaliteli içerikler taslakta tutulur.",
        ],
    },
    {
        "slug": "kunye",
        "title": "Künye",
        "description": "Türkiye Gündemi yayın bilgileri ve sorumluluk alanları.",
        "body": [
            "Yayın adı: Türkiye Gündemi.",
            "Yayın türü: Dijital haber yayını.",
            "Yayın dili: Türkçe.",
            "Sorumlu yayın ve teknik yönetim bilgileri, resmi yayın başlangıcı öncesinde alan sahibi tarafından tamamlanmalıdır.",
            "Editoryal iletişim ve resmi bildirimler için iletişim sayfasındaki kanallar kullanılmalıdır.",
        ],
    },
    {
        "slug": "iletisim",
        "title": "İletişim",
        "description": "Türkiye Gündemi iletişim ve düzeltme başvuru kanalları.",
        "body": [
            "Türkiye Gündemi ile haber, düzeltme, erişim, reklam ve teknik bildirim konularında iletişime geçebilirsiniz.",
            "Yayın başlangıcı öncesinde bu sayfaya kurumsal e-posta adresi, telefon ve posta adresi eklenmelidir.",
            "Düzeltme taleplerinde haber bağlantısı, talebin gerekçesi ve varsa doğrulayıcı belge veya kaynak açıkça belirtilmelidir.",
        ],
    },
    {
        "slug": "gizlilik-politikasi",
        "title": "Gizlilik Politikası",
        "description": "Türkiye Gündemi gizlilik, çerez ve veri işleme ilkeleri.",
        "body": [
            "Türkiye Gündemi, ziyaretçi gizliliğini ve kişisel verilerin korunmasını önemser.",
            "Yayın sitesinde zorunlu teknik kayıtlar, güvenlik ve performans ölçümü amacıyla sınırlı şekilde işlenebilir. Reklam, analiz veya üçüncü taraf servisleri kullanıldığında bu sayfa ilgili detaylarla güncellenmelidir.",
            "Kişisel veri, çerez ve iletişim izinlerine ilişkin resmi metinler yayın öncesinde hukuk danışmanı veya yetkili kişi tarafından son kez kontrol edilmelidir.",
        ],
    },
]


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
        "image": [f"{base}{article_image(article)}"],
        "mainEntityOfPage": f"{base}{slug_to_path(article)}",
    }
    if article.get("source_url"):
        data["citation"] = article["source_url"]
        data["isBasedOn"] = article["source_url"]
    return json.dumps(data, ensure_ascii=False)


def layout(
    site: dict[str, Any],
    title: str,
    description: str,
    body: str,
    canonical_path: str,
    extra_head: str = "",
    ticker_html: str = "",
) -> str:
    theme = site["theme"]
    base = site["base_url"].rstrip("/")
    nav = "\n".join(
        f'<a href="/kategori/{esc(cat["slug"])}/">{esc(cat["name"])}</a>'
        for cat in site["categories"]
    )
    quick_nav = "\n".join(
        f'<a href="/kategori/{esc(cat["slug"])}/">{esc(cat["name"])}</a>'
        for cat in site["categories"][:5]
    )
    footer_pages = "\n".join(
        f'<a href="/{esc(page["slug"])}/">{esc(page["title"])}</a>'
        for page in STATIC_PAGES
    )
    today = datetime.now().strftime("%d.%m.%Y")
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
    <div class="top-rail">
      <nav class="quick-nav" aria-label="Öne çıkan kategoriler">{quick_nav}</nav>
      <span>{esc(today)} · Türkiye ve dünyadan sıcak başlıklar</span>
    </div>
    <div class="masthead">
      <a class="brand" href="/" aria-label="{esc(site["name"])} ana sayfa">
        <span class="brand-mark">TG</span>
        <span class="brand-text">
          <strong>{esc(site["name"])}</strong>
          <em>Haber Merkezi</em>
        </span>
      </a>
      <div class="masthead-meta">
        <span>7/24 gündem takibi</span>
        <a href="/kategori/son-dakika/">Canlı Akış</a>
      </div>
    </div>
    <nav class="top-nav" aria-label="Kategoriler">{nav}</nav>
    {ticker_html}
  </header>
  <main>{body}</main>
  <footer class="site-footer">
    <strong>{esc(site["name"])}</strong>
    <span>Bağımsız, hızlı, doğrulanabilir haber yayını.</span>
    {footer_pages}
    <a href="/robots.txt">robots.txt</a>
    <a href="/sitemap.xml">sitemap.xml</a>
    <a href="/llms.txt">llms.txt</a>
  </footer>
</body>
</html>
"""


def render_index(site: dict[str, Any], articles: list[dict[str, Any]]) -> str:
    if not articles:
        body = """
<section class="section-head">
  <h1>Henüz yayınlanmış haber yok</h1>
  <p>İlk haber yayınlandığında ana sayfa otomatik olarak burada görünecek.</p>
</section>
"""
        return layout(
            site,
            f"{site['name']} | Son Dakika ve Gündem Haberleri",
            "Türkiye ve dünyadan son dakika, gündem, ekonomi, teknoloji ve spor haberleri.",
            body,
            "/",
        )
    lead = articles[0]
    lead_img = esc(article_image(lead))
    side_items = articles[1:3]
    side_html = "\n".join(render_feature_card(article, site, "side-feature") for article in side_items)
    cards = "\n".join(render_card(article, site) for article in articles[3:11])
    latest = "\n".join(
        f'<li><time>{esc(article_time(article))}</time><a href="{slug_to_path(article)}">{esc(article["title"])}</a></li>'
        for article in articles[:10]
    )
    program_tiles = "\n".join(
        f'<a href="/kategori/{esc(slug)}/"><time>{esc(time)}</time><strong>{esc(title)}</strong><span>{esc(label)}</span></a>'
        for time, title, label, slug in [
            ("09:00", "Sabah Gündemi", "Güne başlayan başlıklar", "gundem"),
            ("12:00", "Gün Ortası", "Anlık gelişmeler", "son-dakika"),
            ("16:00", "Ekonomi Ekranı", "Piyasa ve iş dünyası", "ekonomi"),
            ("19:00", "Ana Haber", "Günün ana dosyaları", "gundem"),
            ("21:00", "Dış Bakış", "Dünya gündemi", "dunya"),
            ("23:00", "Gece Akışı", "Son gelişmeler", "son-dakika"),
        ]
    )
    category_sections = "\n".join(
        render_category_block(site, category, articles)
        for category in site["categories"][:6]
    )
    body = f"""
<section class="headline-stage">
  <article class="lead-story">
    <a href="{slug_to_path(lead)}">
      <img src="{lead_img}" alt="{esc(lead["image_alt"])}" width="1200" height="760" fetchpriority="high">
      <div class="headline-copy">
        <span class="kicker">{esc(category_name(site, lead["category"]).upper())}</span>
        <h1>{esc(lead["title"])}</h1>
        <p>{esc(lead["summary"])}</p>
      </div>
    </a>
  </article>
  <div class="headline-side">{side_html}</div>
  <aside class="latest-strip" aria-label="Son haberler">
    <h2>Son Haberler</h2>
    <ol>{latest}</ol>
  </aside>
</section>
<section class="program-strip" aria-label="Türkiye Gündemi ekranı">
  <div class="section-title">
    <span>Yayın Akışı</span>
    <h2>Türkiye Gündemi Ekranı</h2>
  </div>
  <div class="program-grid">{program_tiles}</div>
</section>
<section class="story-grid" aria-label="Gündem akışı">
  {cards}
</section>
{category_sections}
"""
    return layout(
        site,
        f"{site['name']} | Son Dakika ve Gündem Haberleri",
        "Türkiye ve dünyadan son dakika, gündem, ekonomi, teknoloji ve spor haberleri.",
        body,
        "/",
        ticker_html=render_ticker(articles),
    )


def render_feature_card(article: dict[str, Any], site: dict[str, Any], class_name: str = "") -> str:
    category = category_name(site, article["category"])
    classes = "feature-card"
    if class_name:
        classes += f" {class_name}"
    return f"""
<article class="{classes}">
  <a href="{slug_to_path(article)}">
    <img src="{esc(article_image(article))}" alt="{esc(article["image_alt"])}" width="720" height="456" loading="lazy">
    <span>{esc(category.upper())}</span>
    <h2>{esc(article["title"])}</h2>
  </a>
</article>
"""


def render_category_block(site: dict[str, Any], category: dict[str, str], articles: list[dict[str, Any]]) -> str:
    items = articles_for_category(articles, category["slug"], 4)
    if not items:
        return ""
    lead = items[0]
    list_items = "\n".join(
        f'<li><a href="{slug_to_path(article)}">{esc(article["title"])}</a></li>'
        for article in items[1:]
    )
    return f"""
<section class="category-block">
  <div class="section-title">
    <span>{esc(category["name"])}</span>
    <h2>{esc(category["name"])} haberleri</h2>
    <a href="/kategori/{esc(category["slug"])}/">Tümünü gör</a>
  </div>
  <div class="category-layout">
    {render_feature_card(lead, site, "category-lead")}
    <ul>{list_items}</ul>
  </div>
</section>
"""


def render_card(article: dict[str, Any], site: dict[str, Any] | None = None) -> str:
    category = category_name(site, article["category"]) if site else article["category"].replace("-", " ").title()
    return f"""
<article class="story-card">
  <a href="{slug_to_path(article)}">
    <img src="{esc(article_image(article))}" alt="{esc(article["image_alt"])}" width="720" height="456" loading="lazy">
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
  <meta property="og:image" content="{site['base_url'].rstrip('/')}{esc(article_image(article))}">
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
  <img class="article-image" src="{esc(article_image(article))}" alt="{esc(article["image_alt"])}" width="1200" height="760" fetchpriority="high">
  <div class="article-body">{paragraphs}</div>
  {source_html}
  <nav class="tag-list" aria-label="Etiketler">{tags}</nav>
</article>
<section class="related-shell" aria-label="İlgili haberler">
  <div class="section-title">
    <span>Devamı</span>
    <h2>İlgili Haberler</h2>
  </div>
  <div class="story-grid compact">
  {related_html}
  </div>
</section>
"""
    return layout(site, f"{article['title']} - {site['name']}", article["summary"], body, slug_to_path(article), extra)


def render_category(site: dict[str, Any], category: dict[str, str], articles: list[dict[str, Any]]) -> str:
    items = [article for article in articles if article["category"] == category["slug"]]
    cards = "\n".join(render_card(article, site) for article in items) or "<p>Bu kategoride henüz haber yok.</p>"
    latest = "\n".join(
        f'<li><time>{esc(article_time(article))}</time><a href="{slug_to_path(article)}">{esc(article["title"])}</a></li>'
        for article in items[:8]
    )
    body = f"""
<section class="category-hero">
  <div>
    <span class="kicker">{esc(site["name"]).upper()}</span>
    <h1>{esc(category["name"])}</h1>
    <p>{esc(site["name"])} {esc(category["name"])} haberleri, son gelişmeler ve öne çıkan başlıklar.</p>
  </div>
  <aside class="latest-strip compact-list">
    <h2>Bu kategoride son akış</h2>
    <ol>{latest}</ol>
  </aside>
</section>
<section class="story-grid">{cards}</section>
"""
    return layout(
        site,
        f"{category['name']} Haberleri - {site['name']}",
        f"{category['name']} kategorisinden son haberler.",
        body,
        f"/kategori/{category['slug']}/",
        ticker_html=render_ticker(items),
    )


def render_static_page(site: dict[str, Any], page: dict[str, Any]) -> str:
    paragraphs = "\n".join(f"<p>{esc(text)}</p>" for text in page["body"])
    body = f"""
<article class="article-layout static-page">
  <header class="article-head">
    <span class="kicker">TÜRKİYE GÜNDEMİ</span>
    <h1>{esc(page["title"])}</h1>
    <p>{esc(page["description"])}</p>
  </header>
  <div class="article-body">{paragraphs}</div>
</article>
"""
    return layout(site, f"{page['title']} - {site['name']}", page["description"], body, f"/{page['slug']}/")


def xml_escape(value: str) -> str:
    return esc(value)


def render_sitemap(site: dict[str, Any], articles: list[dict[str, Any]]) -> str:
    base = site["base_url"].rstrip("/")
    now = datetime.now(timezone.utc).isoformat()
    urls = [("/", now)]
    urls.extend((f"/kategori/{cat['slug']}/", now) for cat in site["categories"])
    urls.extend((f"/{page['slug']}/", now) for page in STATIC_PAGES)
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
  font-size: 44px;
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
  font-size: 48px;
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

/* Visual news portal redesign */
:root {{
  --line: #d9dde5;
  --navy: #10233f;
  --red: #c3192d;
  --gold: #f5b301;
  --soft: #f3f5f8;
  --panel: #ffffff;
}}
body {{
  background: #f5f6f8;
}}
.site-header {{
  position: relative;
  top: auto;
  display: block;
  padding: 0;
  background: #fff;
  border-bottom: 1px solid var(--line);
  box-shadow: 0 2px 12px rgba(16, 35, 63, .08);
}}
.top-rail {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  min-height: 34px;
  padding: 0 max(18px, calc((100vw - 1180px) / 2));
  color: #fff;
  background: var(--navy);
  font-size: 13px;
}}
.quick-nav {{
  display: flex;
  gap: 16px;
  overflow-x: auto;
  white-space: nowrap;
  font-weight: 700;
}}
.quick-nav a:hover {{ color: var(--gold); }}
.masthead {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  width: min(1180px, calc(100vw - 32px));
  min-height: 96px;
  margin: 0 auto;
}}
.brand {{
  gap: 14px;
  color: var(--navy);
}}
.brand-text {{
  display: grid;
  gap: 2px;
}}
.brand-text strong {{
  font-size: 35px;
  line-height: 1;
  font-weight: 800;
}}
.brand-text em {{
  font-style: normal;
  color: var(--red);
  font-size: 13px;
  font-weight: 800;
  text-transform: uppercase;
}}
.brand-mark {{
  width: 58px;
  height: 58px;
  background: var(--red);
  font-size: 20px;
  font-weight: 900;
  border: 4px solid var(--navy);
}}
.masthead-meta {{
  display: flex;
  align-items: center;
  gap: 12px;
  color: #344054;
  font-size: 14px;
  font-weight: 700;
}}
.masthead-meta a {{
  display: inline-flex;
  align-items: center;
  min-height: 36px;
  padding: 0 14px;
  border-radius: 6px;
  color: #fff;
  background: var(--red);
  font-weight: 800;
}}
.top-nav {{
  justify-content: center;
  gap: 0;
  padding: 0 max(16px, calc((100vw - 1180px) / 2));
  background: var(--red);
  color: #fff;
  font-size: 14px;
  font-weight: 800;
  text-transform: uppercase;
}}
.top-nav a {{
  display: inline-flex;
  align-items: center;
  min-height: 42px;
  padding: 0 16px;
  border-left: 1px solid rgba(255,255,255,.18);
}}
.top-nav a:last-child {{ border-right: 1px solid rgba(255,255,255,.18); }}
.top-nav a:hover {{
  color: #fff;
  background: rgba(255,255,255,.14);
}}
.breaking-bar {{
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  width: min(1180px, calc(100vw - 32px));
  min-height: 42px;
  margin: 12px auto 0;
  border: 1px solid var(--line);
  border-bottom: 0;
  background: #fff;
  overflow: hidden;
}}
.breaking-bar strong {{
  display: grid;
  place-items: center;
  height: 100%;
  padding: 0 16px;
  color: #fff;
  background: var(--navy);
  font-size: 13px;
  text-transform: uppercase;
}}
.breaking-track {{
  display: flex;
  gap: 22px;
  overflow-x: auto;
  padding: 0 14px;
  color: #1d2939;
  font-size: 14px;
  font-weight: 700;
  white-space: nowrap;
}}
.breaking-track a::before {{
  content: "";
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-right: 8px;
  border-radius: 50%;
  background: var(--red);
}}
.headline-stage {{
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(260px, .75fr) minmax(280px, .75fr);
  gap: 18px;
  width: min(1180px, calc(100vw - 32px));
  margin: 24px auto;
}}
.lead-story, .feature-card {{
  position: relative;
  overflow: hidden;
  background: #111827;
  border-bottom: 0;
}}
.lead-story a, .feature-card a {{
  display: block;
  min-height: 100%;
}}
.lead-story img, .feature-card img {{
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform .25s ease;
}}
.lead-story:hover img, .feature-card:hover img {{ transform: scale(1.02); }}
.lead-story::after, .feature-card::after {{
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(0,0,0,.06), rgba(0,0,0,.72));
  pointer-events: none;
}}
.lead-story {{
  min-height: 520px;
}}
.lead-story img {{
  aspect-ratio: 16 / 11;
}}
.headline-copy, .feature-card span, .feature-card h2 {{
  position: absolute;
  z-index: 1;
}}
.headline-copy {{
  left: 24px;
  right: 24px;
  bottom: 24px;
  color: #fff;
}}
.headline-side {{
  display: grid;
  gap: 18px;
}}
.side-feature {{
  min-height: 251px;
}}
.side-feature h2 {{
  left: 18px;
  right: 18px;
  bottom: 18px;
  margin: 0;
  color: #fff;
  font-size: 24px;
  line-height: 1.15;
  letter-spacing: 0;
}}
.side-feature span {{
  left: 18px;
  top: 18px;
}}
.headline-copy .kicker, .feature-card span {{
  width: max-content;
  max-width: 100%;
  padding: 5px 8px;
  color: #fff;
  background: var(--red);
}}
.kicker, .story-card span {{
  color: var(--red);
  text-transform: uppercase;
}}
.lead-story h1 {{
  margin: 10px 0 8px;
  font-size: 44px;
  line-height: 1.05;
  letter-spacing: 0;
}}
.lead-story p {{
  max-width: 720px;
  color: rgba(255,255,255,.88);
}}
.latest-strip {{
  padding: 16px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-top: 4px solid var(--navy);
}}
.latest-strip h2 {{
  margin: 0 0 10px;
  color: var(--navy);
}}
.latest-strip li {{
  padding: 11px 0;
}}
.latest-strip time {{
  color: var(--red);
}}
.latest-strip a {{
  font-weight: 800;
  line-height: 1.25;
}}
.program-strip, .category-block, .related-shell {{
  width: min(1180px, calc(100vw - 32px));
  margin: 32px auto;
}}
.section-title {{
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 14px;
  border-bottom: 3px solid var(--navy);
}}
.section-title span {{
  color: var(--red);
  font-size: 12px;
  font-weight: 900;
  text-transform: uppercase;
}}
.section-title h2 {{
  margin: 0;
  padding-bottom: 8px;
  font-size: 27px;
  line-height: 1.1;
  color: var(--navy);
  letter-spacing: 0;
}}
.section-title a {{
  margin-bottom: 9px;
  color: var(--red);
  font-size: 13px;
  font-weight: 800;
}}
.program-grid {{
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
}}
.program-grid a {{
  display: grid;
  gap: 7px;
  min-height: 116px;
  padding: 13px;
  background: #fff;
  border: 1px solid var(--line);
  border-top: 4px solid var(--red);
}}
.program-grid time {{
  color: var(--red);
  font-weight: 900;
}}
.program-grid strong {{
  color: var(--navy);
  line-height: 1.15;
}}
.program-grid span {{
  color: #667085;
  font-size: 13px;
}}
.story-grid {{
  gap: 20px;
}}
.story-card {{
  background: #fff;
  border-bottom: 3px solid var(--line);
}}
.story-card a {{
  display: block;
}}
.story-card img {{
  width: 100%;
}}
.story-card span, .story-card h2, .story-card p {{
  margin-left: 12px;
  margin-right: 12px;
}}
.story-card h2 {{
  font-size: 21px;
}}
.story-card p {{
  margin-bottom: 16px;
}}
.category-layout {{
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(280px, .85fr);
  gap: 18px;
}}
.category-lead {{
  min-height: 330px;
}}
.category-lead h2 {{
  left: 20px;
  right: 20px;
  bottom: 20px;
  margin: 0;
  color: #fff;
  font-size: 29px;
  line-height: 1.12;
  letter-spacing: 0;
}}
.category-lead span {{
  left: 20px;
  top: 20px;
}}
.category-layout ul {{
  list-style: none;
  margin: 0;
  padding: 0;
  background: #fff;
  border: 1px solid var(--line);
}}
.category-layout li + li {{
  border-top: 1px solid var(--line);
}}
.category-layout li a {{
  display: block;
  padding: 18px;
  color: var(--navy);
  font-size: 18px;
  font-weight: 800;
  line-height: 1.25;
}}
.article-layout, .section-head {{
  width: min(860px, calc(100vw - 32px));
}}
.category-hero {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 380px);
  gap: 24px;
  width: min(1180px, calc(100vw - 32px));
  margin: 28px auto;
  padding: 26px;
  background: #fff;
  border-top: 5px solid var(--red);
}}
.article-head h1, .section-head h1 {{
  font-size: 48px;
}}
.category-hero h1 {{
  margin: 8px 0;
  color: var(--navy);
  font-size: 50px;
  line-height: 1;
  letter-spacing: 0;
}}
.category-hero p {{
  max-width: 620px;
  color: #475467;
  font-size: 18px;
}}
.compact-list {{
  padding: 0;
  border-top: 0;
  border-left: 1px solid var(--line);
  background: transparent;
}}
.compact-list h2 {{
  padding-left: 14px;
}}
.compact-list li {{
  grid-template-columns: 44px 1fr;
  padding-left: 14px;
  padding-right: 0;
}}
.source-box {{
  border-radius: 6px;
}}
.site-footer {{
  gap: 18px;
  padding: 32px 16px;
  margin-top: 44px;
  color: #d9dde5;
  background: var(--navy);
  border-top: 0;
}}
.site-footer a:hover {{ color: #fff; }}
@media (max-width: 1020px) {{
  .headline-stage {{ grid-template-columns: 1fr 1fr; }}
  .latest-strip {{ grid-column: 1 / -1; }}
  .program-grid {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
  .story-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
}}
@media (max-width: 720px) {{
  .top-rail {{ align-items: flex-start; flex-direction: column; padding-top: 8px; padding-bottom: 8px; }}
  .masthead {{ align-items: flex-start; flex-direction: column; min-height: auto; padding: 16px 0; }}
  .brand-text strong {{ font-size: 29px; }}
  .masthead-meta {{ width: 100%; justify-content: space-between; }}
  .headline-stage, .category-layout, .category-hero {{ grid-template-columns: 1fr; }}
  .lead-story {{ min-height: 420px; }}
  .lead-story h1 {{ font-size: 32px; }}
  .side-feature {{ min-height: 220px; }}
  .program-grid, .story-grid {{ grid-template-columns: 1fr; }}
  .article-head h1, .section-head h1, .category-hero h1 {{ font-size: 34px; }}
  .section-title {{ align-items: flex-start; flex-direction: column; }}
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
    for generated_dir in ("haber", "kategori", *(page["slug"] for page in STATIC_PAGES)):
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
    for page in STATIC_PAGES:
        out_dir = public_dir / page["slug"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(render_static_page(site, page), encoding="utf-8")
    (public_dir / "sitemap.xml").write_text(render_sitemap(site, articles), encoding="utf-8")
    (public_dir / "news-sitemap.xml").write_text(render_news_sitemap(site, articles), encoding="utf-8")
    (public_dir / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {site['base_url'].rstrip()}/sitemap.xml\nSitemap: {site['base_url'].rstrip()}/news-sitemap.xml\n",
        encoding="utf-8",
    )
    (public_dir / "llms.txt").write_text(
        f"# {site['name']}\n\nTürkiye odaklı haber yayını. Ana kategoriler: "
        + ", ".join(cat["name"] for cat in site["categories"])
        + ". Kurumsal sayfalar: "
        + ", ".join(page["title"] for page in STATIC_PAGES)
        + ".\n",
        encoding="utf-8",
    )
    palette = {
        "ankara.png": ((15, 76, 129), (230, 240, 250)),
        "ekonomi.png": ((24, 100, 88), (237, 247, 242)),
        "teknoloji.png": ((67, 56, 202), (238, 242, 255)),
        "son-dakika.png": ((195, 25, 45), (255, 238, 238)),
        "dunya.png": ((16, 35, 63), (229, 239, 255)),
        "spor.png": ((15, 118, 110), (232, 247, 244)),
        "kultur.png": ((126, 52, 161), (246, 235, 252)),
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
