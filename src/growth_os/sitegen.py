from __future__ import annotations

import argparse
from email.utils import format_datetime
import html
import json
import math
import os
import re
import shutil
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .config import get_site, project_path
from .content_quality import is_publication_safe
from .subscriptions import public_subscription_settings

PRIORITY_CATEGORIES = {"gundem", "son-dakika", "ekonomi"}
PRIORITY_KEYWORDS = {
    "siyaset",
    "politik",
    "parti",
    "meclis",
    "bakan",
    "cumhurbaşkanı",
    "cumhurbaskani",
    "belediye",
    "başkan",
    "baskan",
    "seçim",
    "secim",
    "dava",
    "mahkeme",
    "soruşturma",
    "sorusturma",
    "operasyon",
    "gözaltı",
    "gozalti",
    "tutuklama",
    "deprem",
    "yangın",
    "yangin",
    "kaza",
    "işçi",
    "isci",
    "emekli",
    "öğrenci",
    "ogrenci",
    "kadın",
    "kadin",
    "çocuk",
    "cocuk",
    "toplum",
    "sosyal",
    "enflasyon",
    "faiz",
    "merkez bankasi",
    "piyasa",
    "borsa",
    "dolar",
    "euro",
    "vergi",
    "zam",
    "asgari",
    "butce",
    "ihracat",
    "ithalat",
}


def category_path(category: dict[str, Any] | str) -> str:
    slug = category if isinstance(category, str) else str(category.get("slug") or "")
    return "/dosya/" if slug == "dosya" else f"/kategori/{slug}/"


def slug_to_path(article: dict[str, Any]) -> str:
    if str(article.get("category") or "") == "dosya":
        return f"/dosya/{article['slug']}/"
    return f"/haber/{article['slug']}/"


def article_output_dir(public_dir: Path, article: dict[str, Any]) -> Path:
    if str(article.get("category") or "") == "dosya":
        return public_dir / "dosya" / article["slug"]
    return public_dir / "haber" / article["slug"]


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def category_name(site: dict[str, Any], slug: str) -> str:
    for category in site["categories"]:
        if category["slug"] == slug:
            return category["name"]
    return slug.replace("-", " ").title()


def article_image(article: dict[str, Any]) -> str:
    image = str(article.get("image") or "").strip()
    fallback = category_fallback_image(str(article.get("category") or ""))
    if not image or image == "/assets/images/ankara.png":
        return fallback
    if not image.startswith(("http://", "https://", "/")):
        return "/" + image
    return image


def category_fallback_image(category: str) -> str:
    return {
        "son-dakika": "/assets/images/son-dakika.png",
        "gundem": "/assets/images/ankara.png",
        "ekonomi": "/assets/images/ekonomi.png",
        "dunya": "/assets/images/dunya.png",
        "teknoloji": "/assets/images/teknoloji.png",
        "spor": "/assets/images/spor.png",
        "kultur": "/assets/images/kultur.png",
        "dosya": "/assets/images/dosya.png",
    }.get(category, "/assets/images/ankara.png")


def image_tag(
    article: dict[str, Any],
    *,
    class_name: str = "",
    width: int = 720,
    height: int = 456,
    loading: str | None = "lazy",
    fetchpriority: str | None = None,
    sizes: str | None = None,
) -> str:
    fallback = category_fallback_image(str(article.get("category") or "gundem"))
    attrs = [
        f'src="{esc(article_image(article))}"',
        f'alt="{esc(str(article.get("image_alt") or article.get("title") or ""))}"',
        f'width="{width}"',
        f'height="{height}"',
        'decoding="async"',
        f'data-fallback="{esc(fallback)}"',
        'onerror="this.onerror=null;this.src=this.dataset.fallback;this.classList.add(\'is-fallback-image\');"',
    ]
    if class_name:
        attrs.insert(0, f'class="{esc(class_name)}"')
    if loading:
        attrs.append(f'loading="{esc(loading)}"')
    if fetchpriority:
        attrs.append(f'fetchpriority="{esc(fetchpriority)}"')
    if sizes:
        attrs.append(f'sizes="{esc(sizes)}"')
    return "<img " + " ".join(attrs) + ">"


def article_word_count(article: dict[str, Any]) -> int:
    body = article.get("body") or []
    if isinstance(body, str):
        text = body
    else:
        text = " ".join(str(part) for part in body)
    return len(re.findall(r"\w+", text, flags=re.UNICODE))


def reading_minutes(article: dict[str, Any]) -> int:
    return max(1, math.ceil(article_word_count(article) / 190))


def article_public_id(article: dict[str, Any]) -> str:
    seed = str(
        article.get("public_id")
        or article.get("automation_signature")
        or article.get("source_url")
        or article.get("slug")
        or article.get("title")
        or "haber"
    )
    number = zlib.crc32(seed.encode("utf-8", errors="ignore")) % 900_000 + 100_000
    return f"TG-{number:06d}"


def article_datetime_display(article: dict[str, Any]) -> str:
    return str(article.get("published_at") or "").replace("T", " ")[:16]


def article_time(article: dict[str, Any]) -> str:
    published = str(article.get("published_at") or "")
    if "T" in published and len(published) >= 16:
        return published[11:16]
    return published[:16]


def articles_for_category(articles: list[dict[str, Any]], category: str, limit: int = 4) -> list[dict[str, Any]]:
    return [article for article in articles if article.get("category") == category][:limit]


def priority_score(article: dict[str, Any]) -> int:
    text = " ".join(
        [
            str(article.get("title") or ""),
            str(article.get("summary") or ""),
            str(article.get("category") or ""),
            " ".join(str(tag) for tag in article.get("tags", []) if tag),
        ]
    ).casefold()
    score = 0
    if str(article.get("category") or "") in PRIORITY_CATEGORIES:
        score += 30
    if str(article.get("category") or "") == "ekonomi":
        score += 12
    for keyword in PRIORITY_KEYWORDS:
        if keyword in text:
            score += 12
    if str(article.get("category") or "") in {"ekonomi", "dunya"} and any(word in text for word in ("bakan", "meclis", "kriz", "savaş", "savas", "yaptırım", "yaptirim")):
        score += 10
    return score


def frontpage_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not articles:
        return []
    pool = articles[:30]
    priority = sorted(pool, key=lambda item: (priority_score(item), str(item.get("published_at") or "")), reverse=True)
    lead = priority[0] if priority and priority_score(priority[0]) > 0 else articles[0]
    rest = [article for article in articles if article.get("slug") != lead.get("slug")]
    return [lead, *rest]


def render_ticker(articles: list[dict[str, Any]]) -> str:
    ticker_items = articles[:10]
    item_html = "\n".join(
        f'<a href="{slug_to_path(article)}"><time>{esc(article_time(article))}:</time><span>{esc(article["title"])}</span></a>'
        for article in ticker_items
    )
    items = item_html + "\n" + item_html if item_html else ""
    if not items:
        items = "<span>Güncel haber akışı hazırlanıyor.</span>"
    return f"""
  <div class="breaking-bar live-breaking" aria-label="Canlı son dakika haber akışı">
    <strong><span></span> Canlı Akış</strong>
    <div class="breaking-track" aria-live="polite">
      <div class="breaking-lane">{items}</div>
    </div>
  </div>
"""


def adsense_client(site: dict[str, Any]) -> str:
    env_client = os.environ.get("GROWTH_OS_ADSENSE_CLIENT", "").strip()
    configured = str((site.get("ads") or {}).get("google_ads_client") or "").strip()
    client = env_client or configured
    if not client.startswith("ca-pub-") or "CHANGE_ME" in client or "XXXX" in client:
        return ""
    return client


def ad_slot_id(site: dict[str, Any], placement: str) -> str:
    slots = (site.get("ads") or {}).get("slots") or {}
    env_name = f"GROWTH_OS_AD_SLOT_{placement.upper().replace('-', '_')}"
    slot = os.environ.get(env_name, "").strip() or str(slots.get(placement) or "").strip()
    if not slot or "CHANGE_ME" in slot or "XXXX" in slot:
        return ""
    return slot


def render_adsense_head(site: dict[str, Any]) -> str:
    client = adsense_client(site)
    if not client:
        return ""
    return f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={esc(client)}" crossorigin="anonymous"></script>'


def render_live_flow_script() -> str:
    return """<script>
(function () {
  function initLiveFlow() {
    document.querySelectorAll(".live-breaking .breaking-track").forEach(function (track) {
      var lane = track.querySelector(".breaking-lane");
      if (!lane || lane.dataset.liveFlowReady === "1") return;
      lane.dataset.liveFlowReady = "1";

      var originals = Array.prototype.slice.call(lane.children);
      while (lane.scrollWidth < track.clientWidth * 2 && originals.length) {
        originals.forEach(function (item) {
          lane.appendChild(item.cloneNode(true));
        });
      }

      var wrapper = track.closest(".live-breaking");
      if (wrapper) wrapper.classList.add("is-js-live");
      lane.style.animation = "none";

      var x = 0;
      var last = 0;
      var paused = false;
      var speed = window.matchMedia("(max-width: 760px)").matches ? 46 : 62;

      function resetPoint() {
        return Math.max(track.clientWidth, lane.scrollWidth / 2);
      }

      function tick(now) {
        if (!last) last = now;
        var delta = Math.min(80, now - last) / 1000;
        last = now;
        if (!paused && lane.scrollWidth > track.clientWidth) {
          x -= speed * delta;
          if (Math.abs(x) >= resetPoint()) x = 0;
          lane.style.transform = "translate3d(" + x + "px,0,0)";
        }
        window.requestAnimationFrame(tick);
      }

      track.addEventListener("mouseenter", function () { paused = true; });
      track.addEventListener("mouseleave", function () { paused = false; });
      track.addEventListener("focusin", function () { paused = true; });
      track.addEventListener("focusout", function () { paused = false; });
      track.addEventListener("touchstart", function () {
        paused = true;
        window.setTimeout(function () { paused = false; }, 1200);
      }, { passive: true });

      window.requestAnimationFrame(tick);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initLiveFlow);
  } else {
    initLiveFlow();
  }
})();
</script>"""


def render_ad_slot(site: dict[str, Any], placement: str, label: str, class_name: str = "") -> str:
    client = adsense_client(site)
    slot = ad_slot_id(site, placement)
    classes = f"ad-slot ad-{placement}"
    if class_name:
        classes += f" {class_name}"
    if client and slot:
        return f"""
<aside class="{classes}" aria-label="{esc(label)}">
  <ins class="adsbygoogle"
       style="display:block"
       data-ad-client="{esc(client)}"
       data-ad-slot="{esc(slot)}"
       data-ad-format="auto"
       data-full-width-responsive="true"></ins>
  <script>(adsbygoogle = window.adsbygoogle || []).push({{}});</script>
</aside>
"""
    return f'<aside class="{classes}" aria-label="{esc(label)}"><span>{esc(label)}</span></aside>'


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
    published = [
        article
        for article in articles
        if article.get("status", "published") == "published" and is_publication_safe(article)
    ]
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
        "identifier": article_public_id(article),
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


def site_json_ld(site: dict[str, Any]) -> str:
    base = site["base_url"].rstrip("/")
    data = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": f"{base}/#organization",
                "name": site["name"],
                "url": base,
                "logo": f"{base}/assets/images/logo.png",
            },
            {
                "@type": "WebSite",
                "@id": f"{base}/#website",
                "url": base,
                "name": site["name"],
                "publisher": {"@id": f"{base}/#organization"},
                "inLanguage": "tr-TR",
            },
        ],
    }
    return json.dumps(data, ensure_ascii=False)


def item_list_json_ld(site: dict[str, Any], articles: list[dict[str, Any]], canonical_path: str) -> str:
    base = site["base_url"].rstrip("/")
    data = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "url": f"{base}{canonical_path}",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": index,
                "url": f"{base}{slug_to_path(article)}",
                "name": article["title"],
            }
            for index, article in enumerate(articles[:12], start=1)
        ],
    }
    return json.dumps(data, ensure_ascii=False)


def breadcrumb_json_ld(site: dict[str, Any], article: dict[str, Any]) -> str:
    base = site["base_url"].rstrip("/")
    category = str(article.get("category") or "gundem")
    data = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": site["name"], "item": f"{base}/"},
            {
                "@type": "ListItem",
                "position": 2,
                "name": category_name(site, category),
                "item": f"{base}{category_path(category)}",
            },
            {
                "@type": "ListItem",
                "position": 3,
                "name": article["title"],
                "item": f"{base}{slug_to_path(article)}",
            },
        ],
    }
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
        f'<a href="{esc(category_path(cat))}">{esc(cat["name"])}</a>'
        for cat in site["categories"]
    )
    quick_nav = "\n".join(
        f'<a href="{esc(category_path(cat))}">{esc(cat["name"])}</a>'
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
  <meta property="og:site_name" content="{esc(site["name"])}">
  <meta property="og:locale" content="tr_TR">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="robots" content="index,follow,max-image-preview:large">
  <meta name="theme-color" content="{theme["primary"]}">
  <link rel="alternate" type="application/rss+xml" title="{esc(site["name"])} RSS" href="{base}/feed.xml">
  <link rel="manifest" href="/manifest.json">
  <link rel="preconnect" href="https://pagead2.googlesyndication.com" crossorigin>
  <link rel="preconnect" href="https://googleads.g.doubleclick.net" crossorigin>
  <link rel="preload" href="/assets/styles.css" as="style">
  <link rel="stylesheet" href="/assets/styles.css">
  {render_adsense_head(site)}
  <script type="application/ld+json">{site_json_ld(site)}</script>
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
        <a href="{esc(category_path('son-dakika'))}">Canlı Akış</a>
      </div>
    </div>
    <nav class="top-nav" aria-label="Kategoriler">{nav}</nav>
    {ticker_html}
  </header>
  <main id="icerik">{body}</main>
  <footer class="site-footer">
    <strong>{esc(site["name"])}</strong>
    <span>Bağımsız, hızlı, doğrulanabilir haber yayını.</span>
    {footer_pages}
  </footer>
  {render_live_flow_script()}
</body>
</html>
"""


def render_focus_panel(site: dict[str, Any], articles: list[dict[str, Any]]) -> str:
    return ""
    focus_items = sorted(articles[:60], key=lambda item: (priority_score(item), str(item.get("published_at") or "")), reverse=True)[:5]
    if not focus_items:
        return ""
    lead = focus_items[0]
    focus_html = "\n".join(
        f"""
        <a href="{slug_to_path(article)}">
          <span>{esc(category_name(site, article["category"]).upper())}</span>
          <strong>{esc(article["title"])}</strong>
          <time>{esc(article_time(article))}</time>
        </a>
        """
        for article in focus_items[1:]
    )
    politics_count = sum(1 for article in articles[:80] if priority_score(article) >= 42 and article.get("category") in {"gundem", "son-dakika"})
    economy_count = sum(1 for article in articles[:80] if article.get("category") == "ekonomi")
    category_counts = []
    for category in site["categories"]:
        count = sum(1 for article in articles if article.get("category") == category["slug"])
        if count:
            category_counts.append((category, count))
    chips = "\n".join(
        f'<a href="{esc(category_path(category))}"><strong>{esc(category["name"])}</strong><span>{count}</span></a>'
        for category, count in category_counts[:8]
    )
    return f"""
<section class="focus-panel" aria-label="Günün öne çıkan haberleri">
  <div class="section-title">
    <span>Editoryal Odak</span>
    <h2>Günün öne çıkan başlıkları</h2>
  </div>
  <div class="focus-layout">
    <article class="focus-lead">
      <a href="{slug_to_path(lead)}">
        {image_tag(lead, width=900, height=560, sizes="(max-width: 860px) 100vw, 48vw")}
        <div>
          <span>{esc(category_name(site, lead["category"]).upper())}</span>
          <h3>{esc(lead["title"])}</h3>
          <p>{esc(lead["summary"])}</p>
          <time>{esc(article_time(lead))}</time>
        </div>
      </a>
    </article>
    <div class="focus-stack">{focus_html}</div>
  </div>
  <div class="focus-metrics" aria-label="Editoryal dağılım">
    <span><strong>{politics_count}</strong> siyaset/gündem sinyali</span>
    <span><strong>{economy_count}</strong> ekonomi başlığı</span>
    <span><strong>{len(articles)}</strong> yayındaki içerik</span>
  </div>
  <div class="topic-radar" aria-label="Kategori radarı">{chips}</div>
</section>
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
    articles = frontpage_articles(articles)
    lead = articles[0]
    side_items = articles[1:3]
    side_html = "\n".join(render_feature_card(article, site, "side-feature") for article in side_items)
    cards = "\n".join(render_card(article, site) for article in articles[3:11])
    latest = "\n".join(
        f'<li><time>{esc(article_time(article))}</time><a href="{slug_to_path(article)}">{esc(article["title"])}</a></li>'
        for article in articles[:10]
    )
    program_tiles = "\n".join(
        f'<a href="{esc(category_path(slug))}"><time>{esc(time)}</time><strong>{esc(title)}</strong><span>{esc(label)}</span></a>'
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
        for category in site["categories"]
    )
    body = f"""
<section class="headline-stage">
  <article class="lead-story">
    <a href="{slug_to_path(lead)}">
      {image_tag(lead, width=1200, height=760, loading=None, fetchpriority="high", sizes="(max-width: 860px) 100vw, 55vw")}
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
    {render_ad_slot(site, "sidebar", "Sidebar Reklam", "ad-sidebar")}
  </aside>
</section>
{render_ad_slot(site, "top", "Üst Reklam", "ad-wide")}
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
{render_ad_slot(site, "mid", "Orta Reklam", "ad-wide")}
{category_sections}
"""
    return layout(
        site,
        f"{site['name']} | Son Dakika ve Gündem Haberleri",
        "Türkiye ve dünyadan son dakika, gündem, ekonomi, teknoloji ve spor haberleri.",
        body,
        "/",
        extra_head=f'<script type="application/ld+json">{item_list_json_ld(site, articles, "/")}</script>',
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
    {image_tag(article, width=720, height=456, sizes="(max-width: 760px) 100vw, 33vw")}
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
    section_label = "Dosya yayınları" if category["slug"] == "dosya" else f"{category['name']} haberleri"
    list_items = "\n".join(
        f'<li><a href="{slug_to_path(article)}">{esc(article["title"])}</a></li>'
        for article in items[1:]
    )
    return f"""
<section class="category-block">
  <div class="section-title">
    <span>{esc(category["name"])}</span>
    <h2>{esc(section_label)}</h2>
    <a href="{esc(category_path(category))}">Tümünü gör</a>
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
    {image_tag(article, width=720, height=456, sizes="(max-width: 760px) 100vw, 33vw")}
    <span>{esc(category.upper())}</span>
    <h2>{esc(article["title"])}</h2>
    <p>{esc(article["summary"])}</p>
  </a>
</article>
"""


def is_premium_dossier(article: dict[str, Any]) -> bool:
    if str(article.get("category") or "") != "dosya":
        return False
    value = str(article.get("premium_required") or "true").strip().casefold()
    return value not in {"0", "false", "hayır", "hayir", "no", "free", "ücretsiz", "ucretsiz"}


def subscription_price_label(site: dict[str, Any], article: dict[str, Any]) -> str:
    article_label = str(article.get("subscription_price") or "").strip()
    site_label = str((site.get("subscriptions") or {}).get("price_label") or "").strip()
    return article_label or site_label or "Aylık 99 TL"


def render_subscription_gate(site: dict[str, Any], article: dict[str, Any], cover_label: str, issue: str) -> str:
    slug = str(article.get("slug") or "").strip()
    price = subscription_price_label(site, article)
    issue_html = f'<em>Sayı: {esc(issue)}</em>' if issue else ""
    return f"""
  <aside class="magazine-box subscription-box" data-premium-slug="{esc(slug)}">
    <span>Dosya aboneliği</span>
    <strong>{esc(cover_label)}</strong>
    {issue_html}
    <p>Bu dosya abonelere açıktır. Erişim kodunu girerek PDF yayınına devam edebilirsiniz.</p>
    <div class="subscription-price">{esc(price)}</div>
    <form class="subscription-form">
      <label>
        <span>Abonelik kodu</span>
        <input name="code" autocomplete="one-time-code" placeholder="TG-XXXXXXXXXXXX" required>
      </label>
      <button type="submit">Erişimi aç</button>
    </form>
    <p class="premium-status" role="status" aria-live="polite"></p>
    <a class="link-button premium-link hidden" href="/premium/dosya/{esc(slug)}/">Dergiyi aç</a>
    <a class="text-link" href="/dosya/abonelik/">Abonelik seçeneklerini incele</a>
  </aside>
  {render_subscription_script()}
"""


def render_subscription_script() -> str:
    return """<script>
(function () {
  if (window.__tgSubscriptionReady) return;
  window.__tgSubscriptionReady = true;
  document.addEventListener("submit", async function (event) {
    var form = event.target.closest(".subscription-form");
    if (!form) return;
    event.preventDefault();
    var box = form.closest(".subscription-box");
    var input = form.querySelector("input[name='code']");
    var status = box.querySelector(".premium-status");
    var link = box.querySelector(".premium-link");
    var button = form.querySelector("button");
    var code = input ? input.value.trim() : "";
    if (!code) return;
    status.textContent = "Kod kontrol ediliyor...";
    button.disabled = true;
    try {
      var response = await fetch("/api/subscription-check", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({site: "turkiye-gundemi", tier: "dosya", code: code})
      });
      var data = await response.json();
      if (!response.ok || !data.ok) throw new Error((data && data.error) || "Kod doğrulanamadı.");
      status.textContent = "Erişim açıldı. PDF yönlendiriliyor...";
      link.classList.remove("hidden");
      window.location.href = link.href;
    } catch (error) {
      status.textContent = error.message || "Kod geçersiz veya süresi dolmuş.";
    } finally {
      button.disabled = false;
    }
  });
})();
</script>"""


def render_dossier_subscription_promo(site: dict[str, Any], items: list[dict[str, Any]]) -> str:
    price = str((site.get("subscriptions") or {}).get("price_label") or "Aylık 99 TL").strip()
    latest = items[0] if items else None
    latest_html = (
        f"""
      <a class="dossier-promo-issue" href="{slug_to_path(latest)}">
        {image_tag(latest, width=420, height=260, sizes="(max-width: 760px) 100vw, 360px")}
        <span>Son yayın</span>
        <strong>{esc(latest["title"])}</strong>
      </a>
"""
        if latest
        else """
      <div class="dossier-promo-issue is-empty">
        <span>Yakında</span>
        <strong>İlk özel dosya yayına hazırlanıyor</strong>
      </div>
"""
    )
    return f"""
<section class="dossier-subscription-promo" aria-label="Dosya aboneliği">
  <div>
    <span class="kicker">Dosya aboneliği</span>
    <h2>Dergi, özel dosya ve arşiv yayınlarına tek kodla erişim</h2>
    <p>Türkiye Gündemi Dosya; dergi sayıları, araştırma dosyaları ve uzun soluklu arşiv çalışmalarını abonelik kodu ile okura açar.</p>
    <div class="dossier-promo-actions">
      <a class="link-button" href="/dosya/abonelik/">Abonelik sayfasına git</a>
      <strong>{esc(price)}</strong>
    </div>
  </div>
  {latest_html}
</section>
"""


def render_subscription_page(site: dict[str, Any], articles: list[dict[str, Any]]) -> str:
    settings = site.get("subscriptions") or {}
    price = str(settings.get("price_label") or "Aylık 99 TL").strip()
    payment = settings.get("payment") or {}
    payment_enabled = bool(payment.get("enabled"))
    provider_label = str(payment.get("provider_label") or "Ödeme linki").strip()
    dossier_items = [article for article in articles if article.get("category") == "dosya"][:6]
    ticker_items = [article for article in articles if article.get("category") != "dosya"][:10]
    defaults = [
        ("aylik", "Aylık", price.replace("Aylık ", "") if price.startswith("Aylık ") else price, 30, "Dergi ve özel dosya yayınlarını düzenli izlemek isteyen okurlar için.", ["Korumalı PDF erişimi", "Yeni dosya yayınlarını okuma", "Tek tarayıcıda hızlı kod doğrulama"]),
        ("uc-aylik", "3 Aylık", "249 TL", 90, "Arşiv okumaları ve yeni sayılar için en dengeli dosya paketi.", ["Tüm aktif dosya yayınları", "Yeni dergi sayıları", "Süre boyunca kesintisiz erişim"]),
        ("yillik", "Yıllık", "899 TL", 365, "Yıl boyu dergi, özel arşiv ve dosya yayınlarını takip eden okurlar için.", ["12 aylık dosya erişimi", "Dergi arşivi", "Yeni özel yayınlara öncelikli erişim"]),
    ]
    payment_plans = {str(plan.get("id") or ""): plan for plan in payment.get("plans", []) if isinstance(plan, dict)}
    plan_chunks: list[str] = []
    for plan_id, name, fallback_price, days, copy, features in defaults:
        configured = payment_plans.get(plan_id, {})
        plan_name = str(configured.get("name") or name)
        plan_price = str(configured.get("price_label") or fallback_price)
        payment_url = str(configured.get("payment_url") or "").strip() if payment_enabled else ""
        href = payment_url or "/iletisim/"
        external_attrs = ' target="_blank" rel="noopener noreferrer sponsored"' if href.startswith(("https://", "http://")) else ""
        cta_label = "Ödeme yap" if payment_url else "Kod talep et"
        is_featured = plan_id == "uc-aylik"
        plan_chunks.append(
            f"""
    <article class="subscription-plan{' is-featured' if is_featured else ''}">
      {('<b>Önerilen</b>' if is_featured else '')}
      <span>{esc(plan_name)}</span>
      <strong>{esc(plan_price)}</strong>
      <p>{esc(copy)}</p>
      <ul>{"".join(f"<li>{esc(feature)}</li>" for feature in features)}</ul>
      <a class="plan-link" href="{esc(href)}"{external_attrs}>{esc(cta_label)}</a>
      <small>{esc(str(days))} günlük erişim kodu için</small>
    </article>
"""
        )
    plan_html = "\n".join(plan_chunks)
    payment_notice = (
        f"{provider_label} üzerinden ödeme alındıktan sonra abonelik kodu paylaşılır."
        if payment_enabled
        else "Ödeme linkleri panelden tanımlandığında paketler doğrudan sağlayıcı ödeme sayfasına yönlenir."
    )
    dossier_html = "\n".join(
        f"""
    <a href="{slug_to_path(article)}">
      {image_tag(article, width=320, height=200, sizes="(max-width: 760px) 100vw, 320px")}
      <span>{esc(article_time(article))}</span>
      <strong>{esc(article["title"])}</strong>
    </a>
"""
        for article in dossier_items
    )
    if not dossier_html:
        dossier_html = "<p>İlk dosya yayını editör kontrolünden sonra bu alanda görünecek.</p>"
    body = f"""
<section class="subscription-hero-page">
  <div class="subscription-hero-copy">
    <span class="kicker">Türkiye Gündemi Dosya</span>
    <h1>Dosya aboneliği</h1>
    <p>Dergi sayıları, özel araştırma dosyaları ve PDF arşiv yayınları için hazırlanan okur alanı. Abonelik kodu doğrulandığında korumalı dosyalar bu tarayıcıda açılır.</p>
    <div class="subscription-proof-grid">
      <span><strong>PDF</strong> Dergi ve dosya erişimi</span>
      <span><strong>Arşiv</strong> Özel yayın takibi</span>
      <span><strong>Kod</strong> Hızlı doğrulama</span>
    </div>
    <div class="subscription-hero-actions">
      <a class="link-button" href="#abonelik-kodu">Abonelik kodu gir</a>
      <a class="text-link" href="/dosya/">Dosya arşivine dön</a>
    </div>
    <p class="subscription-payment-note">{esc(payment_notice)}</p>
  </div>
  <aside class="subscription-access subscription-box" id="abonelik-kodu" data-premium-slug="dosya">
    <div class="access-status"><i></i> Abone erişimi</div>
    <strong>Kod ile giriş</strong>
    <p>Ödeme sonrası verilen abonelik kodunu girin. Kod doğrulandığında bu tarayıcıda dosya erişimi açılır.</p>
    <form class="subscription-form">
      <label>
        <span>Abonelik kodu</span>
        <input name="code" autocomplete="one-time-code" placeholder="TG-XXXXXXXXXXXX" required>
      </label>
      <button type="submit">Erişimi aç</button>
    </form>
    <p class="premium-status" role="status" aria-live="polite"></p>
    <a class="link-button premium-link hidden" href="/dosya/">Dosya arşivine geç</a>
    <small>{esc(payment_notice)}</small>
  </aside>
</section>

<section class="subscription-plans" aria-label="Abonelik paketleri">
  <div class="section-title">
    <span>Paketler</span>
    <h2>Dosya yayınları için abonelik seçenekleri</h2>
  </div>
  <div class="subscription-plan-grid">{plan_html}</div>
</section>

<section class="subscription-included" aria-label="Abonelik kapsamı">
  <div class="subscription-included-copy">
    <span class="kicker">Kapsam</span>
    <h2>Dosya okurları için daha derli toplu bir arşiv deneyimi</h2>
    <p>Bu alan, haber akışından ayrı duran dergi sayıları ve uzun soluklu dosyaları tek başlık altında toplamak için tasarlandı.</p>
  </div>
  <div class="included-grid">
    <article><span>01</span><strong>Dergi PDF'leri</strong><p>Yüklenen sayıların korumalı PDF bağlantıları abonelik koduyla açılır.</p></article>
    <article><span>02</span><strong>Özel dosyalar</strong><p>Gündemin hızlı akışında kaybolmayan araştırma ve arşiv içerikleri öne çıkarılır.</p></article>
    <article><span>03</span><strong>Yayın arşivi</strong><p>Geçmiş sayı ve özel yayınlar dosya arşivinde kronolojik biçimde listelenir.</p></article>
    <article><span>04</span><strong>Kurumsal erişim</strong><p>İstenirse kurum, süre ve kullanıcı kapsamı bazlı abonelik kodları üretilebilir.</p></article>
  </div>
</section>

<section class="subscription-process" aria-label="Abonelik süreci">
  <div>
    <span>01</span>
    <strong>Talep oluştur</strong>
    <p>İletişim sayfasından veya editör ekibinden dosya abonelik kodu talep edilir.</p>
  </div>
  <div>
    <span>02</span>
    <strong>Kod paylaşılır</strong>
    <p>Abonelik süresi ve paket bilgisiyle birlikte kişiye özel erişim kodu verilir.</p>
  </div>
  <div>
    <span>03</span>
    <strong>PDF arşivi açılır</strong>
    <p>Kod doğrulanınca dergi ve özel dosya sayfalarındaki korumalı PDF bağlantıları kullanılabilir.</p>
  </div>
</section>

<section class="subscription-dossiers" aria-label="Son dosyalar">
  <div class="section-title">
    <span>Arşiv</span>
    <h2>Son dosya yayınları</h2>
    <a href="/dosya/">Tüm dosyalar</a>
  </div>
  <div class="subscription-dossier-grid">{dossier_html}</div>
</section>

<section class="subscription-faq" aria-label="Sık sorulan sorular">
  <details open>
    <summary>Abonelik sayfası şu anda nasıl ödeme alıyor?</summary>
    <p>Mevcut kurulumda ödeme sağlayıcısı bağlı değildir; abonelik kodları panelden manuel üretilir ve yalnızca ödeme/onarım süreci tamamlanan okurla paylaşılır.</p>
  </details>
  <details>
    <summary>Kod hangi içerikleri açar?</summary>
    <p>Kod, dosya kategorisindeki abonelik gerektiren dergi ve PDF yayınlarına erişim sağlar.</p>
  </details>
  <details>
    <summary>Kurumsal erişim eklenebilir mi?</summary>
    <p>Evet. Aynı altyapı kurum adı, süre ve erişim kapsamı tanımlanarak genişletilebilir.</p>
  </details>
</section>
{render_subscription_script()}
"""
    return layout(
        site,
        f"Dosya Aboneliği - {site['name']}",
        "Türkiye Gündemi dosya, dergi ve PDF arşiv yayınları için abonelik seçenekleri.",
        body,
        "/dosya/abonelik/",
        ticker_html=render_ticker(ticker_items),
    )


def render_article(site: dict[str, Any], article: dict[str, Any], related: list[dict[str, Any]]) -> str:
    paragraphs = "\n".join(f"<p>{esc(text)}</p>" for text in article["body"])
    tags = "\n".join(f"<a href=\"/etiket/{esc(tag)}/\">#{esc(tag)}</a>" for tag in article.get("tags", []))
    related_html = "\n".join(render_card(item, site) for item in related[:3])
    minutes = reading_minutes(article)
    share_url = f"{site['base_url'].rstrip('/')}{slug_to_path(article)}"
    share_text = article["title"]
    share_url_encoded = quote(share_url, safe="")
    share_text_encoded = quote(share_text, safe="")
    public_id = article_public_id(article)
    share_html = f"""
  <aside class="share-tools" aria-label="Haberi paylaş">
    <span class="share-label">Paylaş</span>
    <a class="share-x" href="https://twitter.com/intent/tweet?url={esc(share_url_encoded)}&text={esc(share_text_encoded)}" target="_blank" rel="noopener noreferrer" aria-label="X'te paylaş">
      <svg width="14" height="14" style="width:14px;height:14px;max-width:14px;max-height:14px;" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M18.2 3h3.2l-7 8 8.2 10h-6.4l-5-6.1L5.4 21H2.2l7.5-8.6L1.8 3h6.6l4.5 5.5L18.2 3Zm-1.1 16.2h1.8L7.5 4.7H5.6l11.5 14.5Z"></path></svg>
      <span class="share-name">X</span>
    </a>
    <a class="share-facebook" href="https://www.facebook.com/sharer/sharer.php?u={esc(share_url_encoded)}" target="_blank" rel="noopener noreferrer" aria-label="Facebook'ta paylaş">
      <svg width="14" height="14" style="width:14px;height:14px;max-width:14px;max-height:14px;" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M14 8.5V6.7c0-.9.4-1.4 1.5-1.4H18V2.2C17.6 2.1 16.5 2 15.3 2c-2.7 0-4.6 1.7-4.6 4.7v1.8H8v3.6h2.7V22H14v-9.9h3.2l.5-3.6H14Z"></path></svg>
      <span class="share-name">Facebook</span>
    </a>
    <a class="share-whatsapp" href="https://api.whatsapp.com/send?text={esc(share_text_encoded)}%20{esc(share_url_encoded)}" target="_blank" rel="noopener noreferrer" aria-label="WhatsApp'ta paylaş">
      <svg width="14" height="14" style="width:14px;height:14px;max-width:14px;max-height:14px;" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12.1 2C6.6 2 2.2 6.4 2.2 11.8c0 1.8.5 3.5 1.3 5L2 22l5.4-1.4c1.4.8 3 1.2 4.7 1.2 5.4 0 9.8-4.4 9.8-9.8S17.5 2 12.1 2Zm0 17.9c-1.5 0-2.8-.4-4.1-1.1l-.3-.2-3.2.8.9-3.1-.2-.3c-.8-1.3-1.2-2.7-1.2-4.2 0-4.4 3.6-8 8-8s8 3.6 8 8.1c.1 4.4-3.5 8-7.9 8Zm4.5-6c-.2-.1-1.4-.7-1.6-.8-.2-.1-.4-.1-.6.1-.2.2-.7.8-.8 1-.1.2-.3.2-.5.1-.3-.1-1.1-.4-2.1-1.3-.8-.7-1.3-1.6-1.5-1.8-.2-.3 0-.4.1-.5l.4-.5c.1-.2.2-.3.3-.5.1-.2.1-.4 0-.5 0-.1-.6-1.4-.8-1.9-.2-.5-.4-.4-.6-.4h-.5c-.2 0-.5.1-.7.3-.2.2-.9.9-.9 2.1s.9 2.4 1 2.6c.1.2 1.8 2.8 4.4 3.9.6.3 1.1.4 1.5.5.6.2 1.2.2 1.6.1.5-.1 1.4-.6 1.6-1.1.2-.6.2-1 .2-1.1-.1-.2-.3-.3-.5-.4Z"></path></svg>
      <span class="share-name">WhatsApp</span>
    </a>
  </aside>
"""
    magazine_html = ""
    if str(article.get("category") or "") == "dosya":
        issue = str(article.get("issue_number") or "").strip()
        cover_label = str(article.get("cover_label") or "Dergi dosyası").strip()
        attachment_url = str(article.get("attachment_url") or "").strip()
        if attachment_url and is_premium_dossier(article):
            magazine_html = render_subscription_gate(site, article, cover_label, issue)
        else:
            attachment_link = (
                f'<a class="link-button" href="{esc(attachment_url)}" target="_blank" rel="noopener noreferrer">Dergiyi aç</a>'
                if attachment_url
                else ""
            )
            magazine_html = f"""
  <aside class="magazine-box">
    <span>Dosya</span>
    <strong>{esc(cover_label)}</strong>
    {f'<em>Sayı: {esc(issue)}</em>' if issue else ''}
    {attachment_link}
  </aside>
"""
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
  <script type="application/ld+json">{breadcrumb_json_ld(site, article)}</script>
"""
    body = f"""
<article class="article-layout">
  <header class="article-head">
    <span class="kicker">{esc(category_name(site, article["category"]).upper())}</span>
    <h1>{esc(article["title"])}</h1>
    <p>{esc(article["summary"])}</p>
    <div class="byline">
      <span>{esc(article["author"])}</span>
      <time datetime="{esc(article["published_at"])}">{esc(article_datetime_display(article))}</time>
      <span class="article-id">Haber No: {esc(public_id)}</span>
      <span>{minutes} dk okuma</span>
    </div>
  </header>
  {image_tag(article, class_name="article-image", width=1200, height=760, loading=None, fetchpriority="high", sizes="(max-width: 860px) 100vw, 820px")}
  {share_html}
  {render_ad_slot(site, "article-top", "Haber İçi Reklam", "ad-article")}
  {magazine_html}
  <div class="article-body">{paragraphs}</div>
  {source_html}
  <nav class="tag-list" aria-label="Etiketler">{tags}</nav>
</article>
{render_ad_slot(site, "article-bottom", "Haber Altı Reklam", "ad-wide")}
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


def render_category_headline(site: dict[str, Any], category: dict[str, str], article: dict[str, Any] | None) -> str:
    if not article:
        return """
    <div class="category-hero-empty">
      <strong>Bu kategoride yayın hazırlanıyor.</strong>
      <p>Yeni haberler editör onayından sonra bu alanda manşete taşınacak.</p>
    </div>
"""
    return f"""
    <article class="category-hero-lead">
      <a href="{slug_to_path(article)}">
        {image_tag(article, width=960, height=560, loading=None, fetchpriority="high", sizes="(max-width: 760px) 100vw, 760px")}
        <div class="category-hero-copy">
          <span>{esc(category["name"]).upper()}</span>
          <h2>{esc(article["title"])}</h2>
          <p>{esc(article["summary"])}</p>
          <time datetime="{esc(article["published_at"])}">{esc(article_time(article))}</time>
        </div>
      </a>
    </article>
"""


def render_category(site: dict[str, Any], category: dict[str, str], articles: list[dict[str, Any]]) -> str:
    items = [article for article in articles if article["category"] == category["slug"]]
    lead = items[0] if items else None
    if category["slug"] == "dosya":
        empty_text = "<p>Bu bölümde henüz dosya/dergi yayını yok.</p>"
        description = f"{site['name']} dosya yayınları, dergi içerikleri, özel haber serileri ve arşiv çalışmaları."
        page_title = f"Dosya ve Dergi - {site['name']}"
        page_description = "Türkiye Gündemi dosya yayınları, dergi içerikleri ve özel haber serileri."
    else:
        empty_text = "<p>Bu kategoride henüz haber yok.</p>"
        description = f"{site['name']} {category['name']} haberleri, son gelişmeler ve öne çıkan başlıklar."
        page_title = f"{category['name']} Haberleri - {site['name']}"
        page_description = f"{category['name']} kategorisinden son haberler."
    cards = "\n".join(render_card(article, site) for article in items[1:]) or empty_text
    subscription_promo = render_dossier_subscription_promo(site, items) if category["slug"] == "dosya" else ""
    latest = "\n".join(
        f'<li><time>{esc(article_time(article))}</time><a href="{slug_to_path(article)}">{esc(article["title"])}</a></li>'
        for article in items[:8]
    )
    body = f"""
<section class="category-hero">
  <div class="category-hero-main">
    <span class="kicker">{esc(site["name"]).upper()}</span>
    <h1>{esc(category["name"])}</h1>
    <p>{esc(description)}</p>
{render_category_headline(site, category, lead)}
  </div>
  <aside class="latest-strip compact-list">
    <h2>Bu kategoride son akış</h2>
    <ol>{latest}</ol>
    {render_ad_slot(site, "category-sidebar", "Kategori Reklam", "ad-sidebar")}
  </aside>
</section>
{render_ad_slot(site, "category-top", "Kategori Üst Reklam", "ad-wide")}
{subscription_promo}
<section class="story-grid">{cards}</section>
"""
    return layout(
        site,
        page_title,
        page_description,
        body,
        category_path(category),
        extra_head=f'<script type="application/ld+json">{item_list_json_ld(site, items, category_path(category))}</script>',
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
    urls.extend((category_path(cat), now) for cat in site["categories"])
    urls.append(("/dosya/abonelik/", now))
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


def rss_date(value: str) -> str:
    try:
        text = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return format_datetime(parsed.astimezone(timezone.utc), usegmt=True)
    except ValueError:
        return format_datetime(datetime.now(timezone.utc), usegmt=True)


def render_rss(site: dict[str, Any], articles: list[dict[str, Any]]) -> str:
    base = site["base_url"].rstrip("/")
    items = "\n".join(
        f"""
    <item>
      <title>{xml_escape(article["title"])}</title>
      <link>{xml_escape(base + slug_to_path(article))}</link>
      <guid isPermaLink="true">{xml_escape(base + slug_to_path(article))}</guid>
      <description>{xml_escape(article["summary"])}</description>
      <pubDate>{rss_date(str(article.get("published_at") or ""))}</pubDate>
    </item>"""
        for article in articles[:50]
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{xml_escape(site["name"])}</title>
    <link>{xml_escape(base + "/")}</link>
    <description>Türkiye ve dünyadan son dakika, gündem ve dosya haberleri.</description>
    <language>tr-TR</language>
    <lastBuildDate>{format_datetime(datetime.now(timezone.utc), usegmt=True)}</lastBuildDate>
{items}
  </channel>
</rss>
"""


def render_manifest(site: dict[str, Any]) -> str:
    manifest = {
        "name": site["name"],
        "short_name": "TG",
        "description": "Türkiye Gündemi haber portalı",
        "lang": "tr-TR",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": site["theme"]["paper"],
        "theme_color": site["theme"]["primary"],
        "icons": [
            {"src": "/assets/images/logo.png", "sizes": "1200x760", "type": "image/png"},
        ],
    }
    return json.dumps(manifest, ensure_ascii=False, indent=2)


def render_ads_txt(site: dict[str, Any]) -> str:
    client = adsense_client(site)
    if not client:
        return ""
    publisher_id = client.replace("ca-", "", 1)
    return f"google.com, {publisher_id}, DIRECT, f08c47fec0942fa0\n"


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
  overflow-x: hidden;
  -webkit-text-size-adjust: 100%;
  text-size-adjust: 100%;
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
  align-items: center;
  color: var(--muted);
  font-size: 14px;
  border-top: 1px solid var(--line);
  padding-top: 14px;
}}
.article-id {{
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 3px 9px;
  border: 1px solid rgba(180, 35, 24, .18);
  border-radius: 999px;
  color: var(--red);
  background: #fff7f9;
  font-weight: 900;
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
.magazine-box {{
  display: grid;
  gap: 8px;
  margin: 0 0 22px;
  padding: 16px;
  border: 1px solid rgba(180, 35, 24, .2);
  border-left: 5px solid var(--red);
  background: #fff7f9;
}}
.magazine-box span {{
  color: var(--red);
  font-size: 12px;
  font-weight: 900;
  text-transform: uppercase;
}}
.magazine-box strong {{
  color: var(--navy);
  font-size: 20px;
}}
.magazine-box em {{
  color: #475467;
  font-style: normal;
}}
.magazine-box p {{
  margin: 0;
  color: #344054;
  line-height: 1.45;
}}
.subscription-price {{
  width: max-content;
  max-width: 100%;
  padding: 6px 10px;
  border-radius: 6px;
  color: #fff;
  background: var(--navy);
  font-size: 13px;
  font-weight: 900;
}}
.subscription-form {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: end;
}}
.subscription-form label {{
  display: grid;
  gap: 5px;
  margin: 0;
  color: #344054;
  font-size: 12px;
  font-weight: 900;
  text-transform: uppercase;
}}
.subscription-form input {{
  width: 100%;
  min-height: 38px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 0 10px;
  font: inherit;
  text-transform: uppercase;
}}
.subscription-form button {{
  min-height: 38px;
  border: 0;
  border-radius: 6px;
  padding: 0 12px;
  color: #fff;
  background: var(--red);
  font-weight: 900;
  cursor: pointer;
}}
.subscription-form button:disabled {{
  opacity: .65;
  cursor: wait;
}}
.premium-status {{
  min-height: 20px;
  color: var(--red);
  font-size: 13px;
  font-weight: 800;
}}
.hidden {{
  display: none !important;
}}
.link-button {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: max-content;
  max-width: 100%;
  min-height: 40px;
  padding: 0 14px;
  border-radius: 6px;
  color: #fff;
  background: var(--red);
  font-weight: 900;
  line-height: 1;
}}
.text-link {{
  width: max-content;
  color: var(--primary);
  font-size: 14px;
  font-weight: 900;
}}
.magazine-box .link-button {{
  width: max-content;
  min-height: 36px;
  padding: 0 12px;
  border-radius: 6px;
  color: #fff;
  background: var(--red);
  font-weight: 800;
}}
.dossier-subscription-promo,
.subscription-hero-page,
.subscription-plans,
.subscription-process,
.subscription-dossiers,
.subscription-faq {{
  width: min(1180px, calc(100vw - 32px));
  margin: 24px auto;
}}
.dossier-subscription-promo {{
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(260px, .7fr);
  gap: 22px;
  align-items: stretch;
  padding: 24px;
  border: 1px solid var(--line);
  border-top: 5px solid var(--red);
  background: #fff;
}}
.dossier-subscription-promo h2,
.subscription-hero-copy h1 {{
  margin: 8px 0 10px;
  color: var(--navy);
  line-height: 1.02;
  letter-spacing: 0;
}}
.dossier-subscription-promo h2 {{
  max-width: 760px;
  font-size: clamp(30px, 4vw, 52px);
}}
.dossier-subscription-promo p,
.subscription-hero-copy p,
.subscription-access p,
.subscription-plan p,
.subscription-process p,
.subscription-faq p {{
  color: #344054;
  line-height: 1.55;
}}
.dossier-promo-actions {{
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  margin-top: 18px;
}}
.dossier-promo-actions strong {{
  color: var(--navy);
  font-size: 18px;
}}
.dossier-promo-issue {{
  display: grid;
  align-content: end;
  min-height: 260px;
  padding: 0;
  overflow: hidden;
  border: 1px solid var(--line);
  background: var(--navy);
  color: #fff;
}}
.dossier-promo-issue img {{
  width: 100%;
  height: 170px;
  object-fit: cover;
}}
.dossier-promo-issue span,
.dossier-promo-issue strong {{
  margin: 0 14px;
}}
.dossier-promo-issue span {{
  margin-top: 12px;
  color: #ffccd2;
  font-size: 12px;
  font-weight: 900;
  text-transform: uppercase;
}}
.dossier-promo-issue strong {{
  margin-bottom: 16px;
  font-size: 20px;
  line-height: 1.1;
}}
.dossier-promo-issue.is-empty {{
  padding: 20px;
}}
.subscription-hero-page {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(310px, 430px);
  gap: 24px;
  align-items: stretch;
  padding: 28px;
  border-top: 5px solid var(--red);
  background: #fff;
}}
.subscription-hero-copy h1 {{
  font-size: clamp(44px, 7vw, 86px);
}}
.subscription-hero-actions {{
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  align-items: center;
  margin-top: 20px;
}}
.subscription-payment-note {{
  max-width: 680px;
  margin: 16px 0 0;
  padding: 12px 14px;
  border-left: 4px solid var(--red);
  background: #f8fafc;
  color: #344054;
  font-size: 14px;
  line-height: 1.45;
}}
.subscription-access {{
  display: grid;
  gap: 10px;
  align-content: center;
  margin: 0;
  padding: 22px;
  border: 1px solid rgba(180, 35, 24, .22);
  border-left: 5px solid var(--red);
  background: #fff7f9;
}}
.subscription-access > span {{
  color: var(--red);
  font-size: 12px;
  font-weight: 900;
  text-transform: uppercase;
}}
.subscription-access > strong {{
  color: var(--navy);
  font-size: 24px;
}}
.subscription-plan-grid,
.subscription-process,
.subscription-dossier-grid {{
  display: grid;
  gap: 16px;
}}
.subscription-plan-grid {{
  grid-template-columns: repeat(3, minmax(0, 1fr));
}}
.subscription-plan {{
  display: grid;
  gap: 10px;
  padding: 18px;
  border: 1px solid var(--line);
  border-top: 4px solid var(--red);
  background: #fff;
}}
.subscription-plan span {{
  color: var(--red);
  font-size: 12px;
  font-weight: 900;
  text-transform: uppercase;
}}
.subscription-plan strong {{
  color: var(--navy);
  font-size: 30px;
}}
.subscription-plan a {{
  align-self: end;
  color: var(--primary);
  font-weight: 900;
}}
.subscription-process {{
  grid-template-columns: repeat(3, minmax(0, 1fr));
}}
.subscription-process > div {{
  padding: 18px;
  border: 1px solid var(--line);
  background: #fff;
}}
.subscription-process span {{
  color: var(--red);
  font-weight: 900;
}}
.subscription-process strong {{
  display: block;
  margin-top: 8px;
  color: var(--navy);
  font-size: 20px;
}}
.subscription-dossier-grid {{
  grid-template-columns: repeat(3, minmax(0, 1fr));
}}
.subscription-dossier-grid a {{
  display: grid;
  gap: 8px;
  border: 1px solid var(--line);
  background: #fff;
}}
.subscription-dossier-grid img {{
  width: 100%;
  aspect-ratio: 16 / 10;
  object-fit: cover;
}}
.subscription-dossier-grid span,
.subscription-dossier-grid strong {{
  margin: 0 12px;
}}
.subscription-dossier-grid span {{
  color: var(--red);
  font-size: 12px;
  font-weight: 900;
}}
.subscription-dossier-grid strong {{
  margin-bottom: 14px;
  color: var(--navy);
  font-size: 18px;
  line-height: 1.15;
}}
.subscription-dossier-grid p {{
  margin: 0;
  padding: 18px;
  background: #fff;
  border: 1px solid var(--line);
}}
.subscription-faq {{
  display: grid;
  gap: 10px;
}}
.subscription-faq details {{
  padding: 16px 18px;
  border: 1px solid var(--line);
  background: #fff;
}}
.subscription-faq summary {{
  color: var(--navy);
  font-size: 18px;
  font-weight: 900;
  cursor: pointer;
}}
.subscription-included {{
  width: min(1180px, calc(100vw - 32px));
  margin: 24px auto;
}}
.subscription-hero-page {{
  position: relative;
  grid-template-columns: minmax(0, 1fr) minmax(350px, 430px);
  gap: 0;
  min-height: 520px;
  padding: 0;
  overflow: hidden;
  border: 1px solid var(--line);
  border-top: 0;
  background: #fff;
}}
.subscription-hero-page::before {{
  content: "";
  position: absolute;
  inset: 0 0 auto;
  height: 6px;
  background: var(--red);
}}
.subscription-hero-copy {{
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 54px 48px 44px;
}}
.subscription-hero-copy h1 {{
  max-width: 720px;
  font-size: 72px;
  line-height: .96;
}}
.subscription-hero-copy p {{
  max-width: 690px;
  font-size: 19px;
}}
.subscription-proof-grid {{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  max-width: 760px;
  margin: 26px 0 0;
}}
.subscription-proof-grid span {{
  display: grid;
  gap: 5px;
  min-height: 84px;
  padding: 13px;
  border: 1px solid var(--line);
  background: #f8fafc;
  color: #475467;
  font-size: 13px;
  line-height: 1.25;
}}
.subscription-proof-grid strong {{
  display: block;
  color: var(--navy);
  font-size: 19px;
}}
.subscription-access {{
  position: relative;
  align-content: center;
  padding: 34px;
  border: 0;
  border-left: 1px solid rgba(255, 255, 255, .14);
  background: var(--navy);
  color: #fff;
}}
.subscription-access::after {{
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 8px;
  background: var(--red);
}}
.access-status {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  width: max-content;
  max-width: 100%;
  color: #dbeafe;
  font-size: 12px;
  font-weight: 900;
  text-transform: uppercase;
}}
.access-status i {{
  width: 9px;
  height: 9px;
  border-radius: 999px;
  background: #38bdf8;
  box-shadow: 0 0 0 4px rgba(56, 189, 248, .16);
}}
.subscription-access > strong {{
  color: #fff;
  font-size: 32px;
}}
.subscription-access p,
.subscription-access small {{
  color: #dbeafe;
}}
.subscription-access small {{
  font-size: 12px;
  line-height: 1.45;
}}
.subscription-access .subscription-form label {{
  color: #dbeafe;
}}
.subscription-access .subscription-form input {{
  min-height: 46px;
  border: 1px solid rgba(255, 255, 255, .22);
  background: rgba(255, 255, 255, .96);
}}
.subscription-access .subscription-form button {{
  min-height: 46px;
}}
.subscription-access .premium-status {{
  color: #fff;
}}
.subscription-plans,
.subscription-included,
.subscription-process,
.subscription-dossiers,
.subscription-faq {{
  margin-top: 30px;
  margin-bottom: 30px;
}}
.subscription-plan-grid {{
  gap: 18px;
}}
.subscription-plan {{
  position: relative;
  min-height: 330px;
  gap: 12px;
  padding: 24px;
  border-top: 1px solid var(--line);
  transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
}}
.subscription-plan:hover {{
  transform: translateY(-3px);
  border-color: rgba(180, 35, 24, .35);
  box-shadow: 0 18px 38px rgba(16, 24, 40, .08);
}}
.subscription-plan.is-featured {{
  border: 2px solid var(--red);
  box-shadow: 0 18px 42px rgba(180, 35, 24, .12);
}}
.subscription-plan b {{
  position: absolute;
  top: 14px;
  right: 14px;
  padding: 5px 8px;
  border-radius: 999px;
  color: #fff;
  background: var(--red);
  font-size: 11px;
  line-height: 1;
  text-transform: uppercase;
}}
.subscription-plan strong {{
  font-size: 38px;
  line-height: 1;
}}
.subscription-plan ul {{
  display: grid;
  gap: 9px;
  margin: 4px 0 10px;
  padding: 0;
  list-style: none;
  color: #344054;
  font-size: 14px;
}}
.subscription-plan li {{
  position: relative;
  padding-left: 18px;
  line-height: 1.35;
}}
.subscription-plan li::before {{
  content: "";
  position: absolute;
  left: 0;
  top: .48em;
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--red);
}}
.subscription-plan .plan-link {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 40px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--navy);
  background: #f8fafc;
}}
.subscription-plan small {{
  color: #667085;
  font-size: 12px;
  line-height: 1.35;
}}
.subscription-included {{
  display: grid;
  grid-template-columns: minmax(260px, .72fr) minmax(0, 1fr);
  gap: 22px;
  align-items: stretch;
  padding: 26px;
  border: 1px solid var(--line);
  background: #fff;
}}
.subscription-included-copy h2 {{
  margin: 8px 0 10px;
  color: var(--navy);
  font-size: 36px;
  line-height: 1.04;
}}
.subscription-included-copy p {{
  color: #344054;
  line-height: 1.55;
}}
.included-grid {{
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}}
.included-grid article {{
  padding: 16px;
  border: 1px solid var(--line);
  background: #f8fafc;
}}
.included-grid span {{
  color: var(--red);
  font-size: 12px;
  font-weight: 900;
}}
.included-grid strong {{
  display: block;
  margin: 8px 0 6px;
  color: var(--navy);
  font-size: 19px;
}}
.included-grid p {{
  margin: 0;
  color: #475467;
  font-size: 14px;
  line-height: 1.45;
}}
.subscription-process > div,
.subscription-faq details,
.subscription-dossier-grid a {{
  transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease;
}}
.subscription-process > div:hover,
.subscription-faq details:hover,
.subscription-dossier-grid a:hover {{
  transform: translateY(-2px);
  border-color: rgba(15, 76, 129, .28);
  box-shadow: 0 14px 30px rgba(16, 24, 40, .07);
}}
@media (max-width: 900px) {{
  .dossier-subscription-promo,
  .subscription-hero-page,
  .subscription-plan-grid,
  .subscription-process,
  .subscription-dossier-grid,
  .subscription-included,
  .included-grid {{
    grid-template-columns: 1fr;
  }}
  .subscription-hero-page {{
    padding: 22px;
  }}
  .subscription-hero-copy {{
    padding: 28px 0 8px;
  }}
  .subscription-hero-copy h1 {{
    font-size: 52px;
  }}
  .subscription-access {{
    border-left: 0;
  }}
}}
@media (max-width: 560px) {{
  .subscription-hero-page {{
    min-height: 0;
    padding: 18px;
  }}
  .subscription-hero-copy h1 {{
    font-size: 42px;
  }}
  .subscription-proof-grid {{
    grid-template-columns: 1fr;
  }}
  .subscription-access {{
    padding: 22px;
  }}
  .subscription-included {{
    padding: 18px;
  }}
  .subscription-included-copy h2 {{
    font-size: 28px;
  }}
  .subscription-form {{
    grid-template-columns: 1fr;
  }}
  .subscription-form button,
  .magazine-box .link-button,
  .link-button,
  .text-link {{
    width: 100%;
  }}
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
.top-nav {{
  max-width: 100%;
}}
.top-nav,
.breaking-track {{
  scrollbar-width: none;
}}
.top-nav::-webkit-scrollbar,
.breaking-track::-webkit-scrollbar {{
  display: none;
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
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 0 16px;
  color: #fff;
  background: var(--navy);
  font-size: 13px;
  text-transform: uppercase;
}}
.breaking-track {{
  min-width: 0;
  overflow: hidden;
  color: #1d2939;
  font-size: 14px;
  font-weight: 700;
  white-space: nowrap;
}}
.breaking-lane {{
  display: flex;
  align-items: center;
  gap: 30px;
  width: max-content;
  min-width: 100%;
  padding: 0 14px;
  animation: breaking-slide 48s linear infinite;
  will-change: transform;
}}
.breaking-track:hover .breaking-lane,
.breaking-track:focus-within .breaking-lane {{
  animation-play-state: paused;
}}
.breaking-track a {{
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: #1d2939;
}}
.breaking-track time {{
  color: var(--red);
  font-size: 12px;
  font-weight: 900;
  flex: 0 0 auto;
}}
.breaking-track a > span {{
  display: inline-block;
  min-width: 0;
}}
.breaking-track a::before {{
  content: "";
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--red);
}}
.live-breaking strong span {{
  width: 8px;
  height: 8px;
  margin-right: 7px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 0 0 0 rgba(255,255,255,.75);
  animation: live-pulse 1.4s ease-out infinite;
}}
@keyframes breaking-slide {{
  from {{ transform: translateX(0); }}
  to {{ transform: translateX(-50%); }}
}}
@keyframes live-pulse {{
  70% {{ box-shadow: 0 0 0 8px rgba(255,255,255,0); }}
  100% {{ box-shadow: 0 0 0 0 rgba(255,255,255,0); }}
}}
@media (prefers-reduced-motion: reduce) {{
  .breaking-lane,
  .live-breaking strong span {{
    animation: none;
  }}
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
.category-hero-main {{
  min-width: 0;
}}
.category-hero-lead {{
  margin-top: 26px;
}}
.category-hero-lead a {{
  position: relative;
  display: block;
  min-height: 380px;
  overflow: hidden;
  border-radius: 8px;
  background: #111827;
  color: #fff;
}}
.category-hero-lead a::after {{
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(8, 18, 33, .08) 0%, rgba(8, 18, 33, .45) 45%, rgba(8, 18, 33, .88) 100%);
  pointer-events: none;
}}
.category-hero-lead img {{
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform .25s ease;
}}
.category-hero-lead:hover img {{
  transform: scale(1.02);
}}
.category-hero-copy {{
  position: absolute;
  z-index: 1;
  left: 24px;
  right: 24px;
  bottom: 24px;
  width: calc(100% - 48px);
  max-width: calc(100% - 48px);
  min-width: 0;
}}
.category-hero-copy span {{
  display: inline-flex;
  margin-bottom: 10px;
  padding: 5px 8px;
  background: var(--red);
  color: #fff;
  font-size: 11px;
  font-weight: 900;
}}
.category-hero-copy h2 {{
  max-width: 100%;
  margin: 0;
  font-size: clamp(26px, 3vw, 44px);
  line-height: 1;
  letter-spacing: 0;
  overflow-wrap: anywhere;
  word-break: normal;
}}
.category-hero-copy p {{
  display: -webkit-box;
  max-width: 100%;
  margin: 12px 0 0;
  color: rgba(255,255,255,.88);
  font-size: 16px;
  line-height: 1.45;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}}
.category-hero-copy time {{
  display: inline-block;
  margin-top: 14px;
  color: #fff;
  font-size: 13px;
  font-weight: 900;
}}
.category-hero-empty {{
  margin-top: 26px;
  padding: 24px;
  border: 1px dashed var(--line);
  border-radius: 8px;
  background: #f8fafc;
}}
.category-hero-empty strong {{
  color: var(--navy);
  font-size: 20px;
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
  .category-hero-lead a {{ min-height: 320px; }}
  .category-hero-copy {{ left: 18px; right: 40px; bottom: 18px; width: calc(100% - 58px); max-width: calc(100% - 58px); }}
  .category-hero-copy h2 {{ font-size: 20px; line-height: 1.08; }}
  .category-hero-copy p {{ font-size: 13.5px; }}
}}

/* Revenue-ready responsive refinements */
.lead-story,
.feature-card,
.story-card,
.category-layout ul,
.latest-strip,
.program-grid a,
.category-hero {{
  border-radius: 8px;
}}
.lead-story img,
.feature-card img,
.story-card img,
.article-image {{
  background: linear-gradient(135deg, #d9dde5, #ffffff);
}}
.story-card img {{
  aspect-ratio: 16 / 9;
  object-fit: cover;
}}
.feature-card img {{
  aspect-ratio: 16 / 10;
  object-fit: cover;
}}
.headline-stage {{
  align-items: start;
}}
.headline-copy {{
  max-width: 92%;
}}
.lead-story > a {{
  position: relative;
  height: 100%;
  min-height: 520px;
  overflow: hidden;
}}
.feature-card > a {{
  position: relative;
  height: 100%;
  min-height: inherit;
  overflow: hidden;
}}
.lead-story img,
.feature-card img {{
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  max-width: none;
  object-fit: cover;
}}
.lead-story h1,
.feature-card h2,
.story-card h2,
.article-head h1,
.headline-copy p {{
  overflow-wrap: break-word;
  word-break: normal;
}}
.headline-copy p {{
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  overflow-wrap: normal;
  word-break: normal;
  hyphens: none;
}}
.latest-strip {{
  max-height: 650px;
  overflow: auto;
}}
.ad-slot {{
  display: grid;
  place-items: center;
  min-height: 92px;
  width: min(1180px, calc(100vw - 32px));
  margin: 22px auto;
  padding: 12px;
  border: 1px dashed #b8c0cc;
  border-radius: 8px;
  background:
    repeating-linear-gradient(135deg, rgba(16, 35, 63, .035) 0 8px, rgba(195, 25, 45, .035) 8px 16px),
    #fff;
  color: #667085;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}}
.ad-slot ins {{
  min-height: 90px;
  width: 100%;
}}
.ad-sidebar {{
  width: 100%;
  min-height: 250px;
  margin: 18px 0 0;
}}
.ad-article {{
  width: 100%;
  min-height: 120px;
  margin: 18px 0 24px;
}}
.article-layout {{
  background: #fff;
  padding: 24px;
  border-radius: 8px;
  box-shadow: 0 1px 0 rgba(16, 35, 63, .06);
}}
.article-body {{
  max-width: 720px;
  margin: 0 auto;
}}
@media (max-width: 1180px) {{
  .headline-stage {{
    grid-template-columns: minmax(0, 1.15fr) minmax(260px, .85fr);
  }}
  .latest-strip {{
    grid-column: 1 / -1;
  }}
}}
@media (max-width: 860px) {{
  .top-nav {{
    justify-content: flex-start;
    overflow-x: auto;
  }}
  .headline-stage {{
    grid-template-columns: 1fr;
    gap: 14px;
  }}
  .lead-story {{
    min-height: auto;
  }}
  .lead-story a {{
    min-height: 460px;
  }}
  .headline-side {{
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }}
  .side-feature {{
    min-height: 240px;
  }}
  .latest-strip {{
    max-height: none;
  }}
}}
@media (max-width: 560px) {{
  body {{
    background: #fff;
  }}
  .top-rail span {{
    display: none;
  }}
  .brand-mark {{
    width: 48px;
    height: 48px;
  }}
  .brand-text strong {{
    font-size: 25px;
  }}
  .masthead-meta {{
    display: none;
  }}
  .breaking-bar {{
    grid-template-columns: 1fr;
  }}
  .breaking-bar strong {{
    min-height: 34px;
  }}
  .headline-stage,
  .program-strip,
  .category-block,
  .related-shell,
  .story-grid,
  .category-hero,
  .ad-slot {{
    width: calc(100vw - 20px);
    max-width: calc(100vw - 20px);
    margin-left: auto;
    margin-right: auto;
  }}
  .lead-story,
  .feature-card,
  .story-card {{
    min-width: 0;
    max-width: 100%;
  }}
  .headline-copy {{
    max-width: none;
    width: auto;
  }}
  .lead-story a {{
    min-height: 430px;
  }}
  .headline-copy {{
    left: 16px;
    right: 16px;
    bottom: 16px;
  }}
  .lead-story h1 {{
    font-size: 29px;
  }}
  .headline-side {{
    grid-template-columns: 1fr;
  }}
  .side-feature h2 {{
    font-size: 21px;
  }}
  .story-card h2 {{
    font-size: 20px;
  }}
  .article-layout {{
    width: calc(100vw - 20px);
    padding: 16px;
  }}
  .article-body p {{
    font-size: 18px;
  }}
}}

/* Complete responsive system */
.site-header,
main,
.site-footer {{
  max-width: 100vw;
}}
.top-rail,
.masthead,
.top-nav,
.breaking-bar,
.headline-stage,
.program-strip,
.category-block,
.related-shell,
.story-grid,
.category-hero,
.article-layout,
.section-head,
.ad-slot {{
  min-width: 0;
}}
.brand,
.masthead-meta,
.section-title,
.byline {{
  min-width: 0;
}}
.brand-text,
.brand-text strong,
.brand-text em,
.section-title h2,
.story-card h2,
.feature-card h2,
.lead-story h1,
.article-head h1,
.category-hero h1,
.category-hero-copy h2 {{
  overflow-wrap: anywhere;
  word-break: normal;
}}
.quick-nav,
.top-nav {{
  -webkit-overflow-scrolling: touch;
}}
.headline-stage,
.story-grid,
.program-grid,
.category-layout,
.category-hero {{
  align-items: start;
}}
.story-card a,
.program-grid a,
.latest-strip,
.article-layout,
.category-hero,
.category-hero-lead a {{
  min-width: 0;
}}
.story-card p,
.headline-copy p,
.category-hero-copy p {{
  overflow-wrap: break-word;
}}
@media (max-width: 1180px) {{
  .masthead,
  .headline-stage,
  .program-strip,
  .category-block,
  .related-shell,
  .story-grid,
  .category-hero,
  .breaking-bar,
  .ad-slot {{
    width: calc(100vw - 28px);
  }}
  .headline-stage {{
    grid-template-columns: minmax(0, 1fr) minmax(280px, .78fr);
  }}
  .headline-side {{
    grid-template-columns: 1fr;
  }}
  .latest-strip {{
    grid-column: 1 / -1;
  }}
}}
@media (max-width: 980px) {{
  .top-rail {{
    flex-wrap: wrap;
    padding-top: 6px;
    padding-bottom: 6px;
  }}
  .masthead {{
    min-height: 82px;
  }}
  .headline-stage,
  .category-hero {{
    grid-template-columns: 1fr;
  }}
  .headline-side {{
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }}
  .story-grid {{
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }}
  .program-grid {{
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }}
  .article-head h1,
  .section-head h1 {{
    font-size: 40px;
  }}
}}
@media (max-width: 760px) {{
  .top-rail {{
    display: none;
  }}
  .masthead {{
    width: calc(100vw - 24px);
    min-height: auto;
    padding: 14px 0;
  }}
  .brand {{
    gap: 10px;
  }}
  .brand-mark {{
    width: 48px;
    height: 48px;
    font-size: 18px;
  }}
  .brand-text strong {{
    font-size: 28px;
    line-height: 1;
  }}
  .brand-text em {{
    font-size: 12px;
  }}
  .masthead-meta {{
    display: none;
  }}
  .top-nav {{
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    width: 100%;
    overflow: visible;
  }}
  .top-nav a {{
    justify-content: center;
    min-height: 36px;
    padding: 0 8px;
    border-bottom: 1px solid rgba(255,255,255,.18);
    font-size: 12px;
    text-align: center;
  }}
  .breaking-bar {{
    grid-template-columns: 1fr;
    width: 100%;
    margin-top: 0;
    border-left: 0;
    border-right: 0;
  }}
  .breaking-bar strong {{
    min-height: 34px;
  }}
  .breaking-lane {{
    gap: 22px;
    padding: 0 10px;
    font-size: 13px;
  }}
  .headline-stage,
  .program-strip,
  .category-block,
  .related-shell,
  .story-grid,
  .category-hero,
  .ad-slot,
  .article-layout,
  .section-head {{
    width: calc(100vw - 20px);
    max-width: calc(100vw - 20px);
  }}
  .headline-stage {{
    grid-template-columns: 1fr;
    gap: 14px;
    margin-top: 18px;
  }}
  .headline-side,
  .story-grid,
  .program-grid,
  .category-layout {{
    grid-template-columns: 1fr;
  }}
  .lead-story > a {{
    min-height: 430px;
  }}
  .side-feature {{
    min-height: 230px;
  }}
  .lead-story h1 {{
    font-size: 30px;
    line-height: 1.05;
  }}
  .feature-card h2 {{
    font-size: 22px;
  }}
  .category-hero {{
    margin-top: 24px;
    padding: 24px 18px;
  }}
  .category-hero h1 {{
    font-size: 36px;
  }}
  .category-hero p {{
    font-size: 17px;
  }}
  .category-hero-lead a {{
    min-height: 350px;
  }}
  .category-hero-copy {{
    left: 16px;
    right: 16px;
    bottom: 16px;
    width: calc(100% - 32px);
    max-width: calc(100% - 32px);
  }}
  .category-hero-copy h2 {{
    display: -webkit-box;
    font-size: 22px;
    line-height: 1.08;
    -webkit-line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }}
  .category-hero-copy p {{
    font-size: 14px;
    -webkit-line-clamp: 2;
  }}
  .latest-strip {{
    max-height: none;
  }}
  .latest-strip li,
  .compact-list li {{
    grid-template-columns: 42px minmax(0, 1fr);
  }}
  .article-layout {{
    padding: 18px;
  }}
  .article-head h1,
  .section-head h1 {{
    font-size: 32px;
    line-height: 1.08;
  }}
  .article-head p {{
    font-size: 17px;
  }}
  .article-body p {{
    font-size: 18px;
    line-height: 1.65;
  }}
  .share-tools {{
    margin: 0 0 16px;
  }}
  .share-label {{
    flex: 1 0 100%;
  }}
  .share-tools a {{
    flex: 1 1 calc(33.333% - 8px);
    justify-content: center;
    min-width: 0;
    padding: 9px 8px;
  }}
  .ad-slot {{
    min-height: 76px;
    margin-top: 16px;
    margin-bottom: 16px;
  }}
}}
@media (max-width: 420px) {{
  .masthead {{
    width: calc(100vw - 16px);
    padding: 12px 0;
  }}
  .brand {{
    gap: 8px;
  }}
  .brand-mark {{
    width: 44px;
    height: 44px;
  }}
  .brand-text strong {{
    font-size: 24px;
  }}
  .top-nav {{
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }}
  .top-nav a {{
    min-height: 34px;
    padding: 0 6px;
    font-size: 12px;
  }}
  .headline-stage,
  .program-strip,
  .category-block,
  .related-shell,
  .story-grid,
  .category-hero,
  .ad-slot,
  .article-layout,
  .section-head {{
    width: calc(100vw - 16px);
    max-width: calc(100vw - 16px);
  }}
  .lead-story > a {{
    min-height: 390px;
  }}
  .lead-story h1 {{
    font-size: 27px;
  }}
  .headline-copy {{
    left: 14px;
    right: 14px;
    bottom: 14px;
  }}
  .category-hero {{
    padding: 22px 16px;
  }}
  .category-hero-lead a {{
    min-height: 330px;
  }}
  .category-hero-copy {{
    left: 14px;
    right: 14px;
    bottom: 14px;
    width: calc(100% - 28px);
    max-width: calc(100% - 28px);
  }}
  .category-hero-copy h2 {{
    font-size: 20px;
  }}
  .category-hero-copy p {{
    font-size: 13px;
  }}
  .story-card h2 {{
    font-size: 20px;
  }}
  .article-layout {{
    padding: 16px;
  }}
  .article-head h1,
  .section-head h1 {{
    font-size: 29px;
  }}
  .article-body p {{
    font-size: 17px;
  }}
  .share-name {{
    font-size: 12px;
  }}
  .share-tools svg {{
    width: 17px;
    height: 17px;
  }}
}}
.skip-link {{
  position: fixed;
  left: 12px;
  top: 12px;
  z-index: 999;
  transform: translateY(-140%);
  padding: 10px 12px;
  border-radius: 6px;
  color: #fff;
  background: var(--navy);
  font-weight: 900;
}}
.skip-link:focus {{
  transform: translateY(0);
}}
.is-fallback-image {{
  object-fit: cover;
  filter: saturate(.92);
}}
.focus-panel {{
  width: min(1180px, calc(100vw - 32px));
  margin: 32px auto;
}}
.focus-layout {{
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(320px, .75fr);
  gap: 16px;
  align-items: stretch;
}}
.focus-lead,
.focus-stack a,
.focus-metrics span {{
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}}
.focus-lead a {{
  position: relative;
  display: block;
  min-height: 420px;
  overflow: hidden;
  border-radius: 8px;
  color: #fff;
  background: var(--navy);
}}
.focus-lead img {{
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  opacity: .82;
}}
.focus-lead a::after {{
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(16, 35, 63, .08), rgba(16, 35, 63, .78));
}}
.focus-lead div {{
  position: absolute;
  z-index: 1;
  left: 24px;
  right: 24px;
  bottom: 24px;
}}
.focus-lead span,
.focus-stack span {{
  display: inline-flex;
  width: max-content;
  max-width: 100%;
  padding: 5px 8px;
  color: #fff;
  background: var(--red);
  font-size: 11px;
  font-weight: 900;
  text-transform: uppercase;
}}
.focus-lead h3 {{
  max-width: 760px;
  margin: 12px 0 10px;
  font-size: clamp(30px, 4vw, 48px);
  line-height: 1.02;
  letter-spacing: 0;
}}
.focus-lead p {{
  display: -webkit-box;
  max-width: 700px;
  margin: 0 0 10px;
  color: rgba(255,255,255,.9);
  font-size: 17px;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}}
.focus-lead time {{
  font-size: 13px;
  font-weight: 900;
}}
.focus-stack {{
  display: grid;
  gap: 10px;
}}
.focus-stack a {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px 12px;
  min-height: 96px;
  padding: 14px;
  border-top: 4px solid var(--red);
}}
.focus-stack span {{
  grid-column: 1 / -1;
}}
.focus-stack strong {{
  color: var(--navy);
  font-size: 18px;
  line-height: 1.16;
  overflow-wrap: anywhere;
}}
.focus-stack time {{
  justify-self: end;
  color: #667085;
  font-size: 13px;
  font-weight: 800;
}}
.focus-metrics {{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}}
.focus-metrics span {{
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 56px;
  padding: 12px 14px;
  color: #475467;
  font-size: 13px;
  font-weight: 800;
}}
.focus-metrics strong {{
  color: var(--navy);
  font-size: 24px;
}}
.topic-radar {{
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
}}
.topic-radar a {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 36px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: #fff;
  color: var(--navy);
  font-size: 13px;
  font-weight: 900;
}}
.topic-radar span {{
  display: inline-grid;
  place-items: center;
  min-width: 24px;
  height: 24px;
  border-radius: 999px;
  color: #fff;
  background: var(--red);
  font-size: 12px;
}}
.share-tools {{
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
  margin: -6px 0 18px;
}}
.share-label {{
  color: #667085;
  font-size: 12px;
  font-weight: 900;
  text-transform: uppercase;
}}
.share-tools a {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 32px;
  padding: 6px 9px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: #fff;
  color: var(--navy);
  font-size: 12px;
  font-weight: 900;
}}
.share-tools svg {{
  width: 14px;
  height: 14px;
  fill: currentColor;
  flex: 0 0 auto;
}}
.share-x {{
  color: #111827;
}}
.share-facebook {{
  color: #1877f2;
}}
.share-whatsapp {{
  color: #128c7e;
}}
.share-name {{
  line-height: 1;
}}
.share-tools a:hover,
.topic-radar a:hover,
.focus-stack a:hover {{
  border-color: rgba(180, 35, 24, .45);
  color: var(--red);
}}
@media (max-width: 760px) {{
  .share-tools a {{
    gap: 5px;
    min-height: 31px;
    padding: 7px 7px;
    font-size: 12px;
  }}
  .share-tools svg {{
    width: 13px;
    height: 13px;
  }}
}}
@media (max-width: 980px) {{
  .focus-layout {{
    grid-template-columns: 1fr;
  }}
  .focus-stack {{
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }}
}}
@media (max-width: 760px) {{
  .focus-panel {{
    width: calc(100vw - 20px);
  }}
  .focus-stack,
  .focus-metrics {{
    grid-template-columns: 1fr;
  }}
  .focus-lead a {{
    min-height: 390px;
  }}
  .focus-lead div {{
    left: 16px;
    right: 16px;
    bottom: 16px;
  }}
  .focus-lead h3 {{
    font-size: 28px;
  }}
  .focus-stack a {{
    min-height: 112px;
  }}
}}
@media (max-width: 420px) {{
  .focus-panel {{
    width: calc(100vw - 16px);
  }}
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
    site = dict(get_site(site_id))
    site["subscriptions"] = {**(site.get("subscriptions") or {}), **public_subscription_settings(site_id)}
    if site["type"] != "new_static_portal":
        raise SystemExit(f"{site_id} is not a static portal site.")
    articles = read_articles(site)
    public_dir = project_path(site["public_dir"])
    (public_dir / "assets" / "images").mkdir(parents=True, exist_ok=True)
    for generated_dir in ("haber", "kategori", "dosya", *(page["slug"] for page in STATIC_PAGES)):
        target = (public_dir / generated_dir).resolve()
        public_root = public_dir.resolve()
        if target.exists() and public_root in target.parents:
            shutil.rmtree(target)
    for generated_file in ("index.html", "sitemap.xml", "news-sitemap.xml", "feed.xml", "manifest.json", "manifest.webmanifest", "robots.txt", "llms.txt", "ads.txt"):
        target = public_dir / generated_file
        if target.exists():
            target.unlink()
    (public_dir / "haber").mkdir(parents=True, exist_ok=True)
    (public_dir / "kategori").mkdir(parents=True, exist_ok=True)
    (public_dir / "dosya").mkdir(parents=True, exist_ok=True)
    (public_dir / "assets" / "styles.css").write_text(render_css(site), encoding="utf-8")
    (public_dir / "index.html").write_text(render_index(site, articles), encoding="utf-8")
    for article in articles:
        out_dir = article_output_dir(public_dir, article)
        out_dir.mkdir(parents=True, exist_ok=True)
        related = [item for item in articles if item["slug"] != article["slug"] and item["category"] == article["category"]]
        if len(related) < 3:
            related += [item for item in articles if item["slug"] != article["slug"] and item not in related]
        (out_dir / "index.html").write_text(render_article(site, article, related), encoding="utf-8")
    for category in site["categories"]:
        out_dir = public_dir / "dosya" if category["slug"] == "dosya" else public_dir / "kategori" / category["slug"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(render_category(site, category, articles), encoding="utf-8")
    subscription_dir = public_dir / "dosya" / "abonelik"
    subscription_dir.mkdir(parents=True, exist_ok=True)
    (subscription_dir / "index.html").write_text(render_subscription_page(site, articles), encoding="utf-8")
    for page in STATIC_PAGES:
        out_dir = public_dir / page["slug"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(render_static_page(site, page), encoding="utf-8")
    (public_dir / "sitemap.xml").write_text(render_sitemap(site, articles), encoding="utf-8")
    (public_dir / "news-sitemap.xml").write_text(render_news_sitemap(site, articles), encoding="utf-8")
    (public_dir / "feed.xml").write_text(render_rss(site, articles), encoding="utf-8")
    (public_dir / "manifest.json").write_text(render_manifest(site), encoding="utf-8")
    (public_dir / "manifest.webmanifest").write_text(render_manifest(site), encoding="utf-8")
    ads_txt = render_ads_txt(site)
    if ads_txt:
        (public_dir / "ads.txt").write_text(ads_txt, encoding="utf-8")
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
        "dosya.png": ((113, 44, 76), (255, 241, 248)),
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
