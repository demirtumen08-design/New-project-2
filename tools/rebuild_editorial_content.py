from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.growth_os.content_store import save_articles  # noqa: E402
from src.growth_os.news_automation import (  # noqa: E402
    NEWSROOM_AUTHOR,
    clean_text,
    fetch_article_details,
    is_rejected_title,
    item_to_article,
    map_category,
    now_iso,
    parse_date,
    signature_for,
)
from src.growth_os.sitegen import generate  # noqa: E402


SITE_ID = "turkiye-gundemi"
ARTICLES_PATH = ROOT / "content" / "turkiye-gundemi" / "articles.json"
SOURCES_PATH = ROOT / "config" / "news_sources.json"


LEGACY_DRAFTS = {
    "ankara-kulisleri-yeni-haftaya-ekonomi-basliklariyla-giriyor": {
        "title": "Ankara kulisleri yeni haftaya ekonomi başlıklarıyla giriyor",
        "summary": "Kabine ve Meclis trafiğinde enflasyon, emekli aylıkları ve yerel yönetim düzenlemeleri öne çıkıyor.",
        "image_alt": "Ankara gündemini temsil eden haber görseli",
    },
    "piyasalarda-gozler-haftanin-veri-takviminde": {
        "title": "Piyasalarda gözler haftanın veri takviminde",
        "summary": "Küresel piyasalarda faiz beklentileri ve enerji fiyatları ekonomi haberlerinin ana başlığı oldu.",
        "image_alt": "Piyasa ve ekonomi verilerini temsil eden görsel",
    },
    "teknoloji-sirketleri-yapay-zeka-yatirimlarini-artiriyor": {
        "title": "Teknoloji şirketleri yapay zekâ yatırımlarını artırıyor",
        "summary": "Yeni yatırım dalgası medya, reklam ve arama davranışlarını yeniden şekillendiriyor.",
        "image_alt": "Teknoloji haberlerini temsil eden görsel",
    },
}


def load_source_map() -> dict[str, str]:
    config = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    return {clean_text(source["name"]): clean_text(source["url"]) for source in config.get("sources", [])}


def draft_notice(article: dict[str, str], *, reason: str) -> dict[str, str]:
    article["summary"] = reason
    article["body"] = ["Bu kayıt, haber niteliği veya kaynak bütünlüğü yeterli olmadığı için editör onayına bırakıldı."]
    article["author"] = NEWSROOM_AUTHOR
    article["status"] = "draft"
    article["modified_at"] = now_iso()
    article["tags"] = [clean_text(tag) for tag in article.get("tags", []) if clean_text(tag).casefold() != "haber robotu"]
    return article


def rebuild_article(article: dict[str, str], feed_by_source: dict[str, str]) -> dict[str, str]:
    title = clean_text(article.get("title", ""))
    source_url = clean_text(article.get("source_url", ""))
    if not source_url.startswith("http"):
        legacy = LEGACY_DRAFTS.get(article.get("slug", ""), {})
        article["title"] = legacy.get("title", title)
        article["summary"] = legacy.get("summary", clean_text(article.get("summary", "")))
        article["image_alt"] = legacy.get("image_alt", clean_text(article.get("image_alt", article["title"])))
        return draft_notice(article, reason=article["summary"])

    if is_rejected_title(title):
        article["title"] = title
        return draft_notice(article, reason="Bu başlık servis veya arama sayfası niteliğinde olduğu için yayına alınmadı.")

    published_at, published_sort = parse_date(article.get("source_published_at") or article.get("published_at"))
    source_name = clean_text(article.get("source_name") or "Kaynak")
    item = {
        "source": source_name,
        "source_url": clean_text(article.get("source_feed") or feed_by_source.get(source_name, "")),
        "category": map_category(article.get("category", "gundem")),
        "raw_category": article.get("category", ""),
        "title": title,
        "link": source_url,
        "summary": clean_text(article.get("summary", "")),
        "published_at": published_at,
        "published_sort": published_sort,
    }
    item["signature"] = article.get("automation_signature") or signature_for(item)
    item["details"] = fetch_article_details(source_url)
    item["variants"] = {}

    rebuilt = item_to_article(item, status=article.get("status", "published"))
    rebuilt["slug"] = article.get("slug") or rebuilt["slug"]
    rebuilt["published_at"] = article.get("published_at") or rebuilt["published_at"]
    rebuilt["image"] = article.get("image") or rebuilt["image"]
    rebuilt["image_alt"] = clean_text(article.get("image_alt") or rebuilt["image_alt"])
    rebuilt["automation_signature"] = item["signature"]
    rebuilt["imported_at"] = article.get("imported_at") or rebuilt.get("imported_at", now_iso())
    return rebuilt


def main() -> int:
    feed_by_source = load_source_map()
    articles = json.loads(ARTICLES_PATH.read_text(encoding="utf-8"))
    rebuilt = [rebuild_article(article, feed_by_source) for article in articles]
    save_articles(SITE_ID, rebuilt)
    public_dir = generate(SITE_ID)
    result = {
        "total": len(rebuilt),
        "published": sum(1 for article in rebuilt if article.get("status", "published") == "published"),
        "draft": sum(1 for article in rebuilt if article.get("status") == "draft"),
        "public_dir": str(public_dir),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
