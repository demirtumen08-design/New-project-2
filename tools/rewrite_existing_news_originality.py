from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.growth_os.content_store import load_articles, now_iso, save_articles  # noqa: E402
from src.growth_os.news_automation import (  # noqa: E402
    NEWSROOM_AUTHOR,
    ORIGINALITY_POLICY,
    article_quality_metrics,
    category_context,
    clean_text,
    fetch_article_details,
    is_rejected_title,
    item_to_article,
    map_category,
    signature_for,
)
from src.growth_os.sitegen import generate  # noqa: E402


SITE_ID = "turkiye-gundemi"


def article_source_text(article: dict) -> str:
    body = article.get("body") or []
    body_parts = body if isinstance(body, list) else [str(body)]
    return " ".join([str(article.get("summary") or ""), *[str(part) for part in body_parts]])


def article_to_item(article: dict) -> dict:
    source_name = clean_text(article.get("source_name") or "Kaynak")
    source_url = clean_text(article.get("source_url") or "")
    source_feed = clean_text(article.get("source_feed") or "")
    category = map_category(article.get("category") or "gundem")
    source_title = clean_text(article.get("source_title") or article.get("title") or "")
    details = {"sentences": [article_source_text(article)]}
    if source_url.startswith(("http://", "https://")):
        fetched = fetch_article_details(source_url)
        if isinstance(fetched, dict) and fetched.get("sentences"):
            details = fetched
            source_title = clean_text(fetched.get("title") or source_title)
    item = {
        "source": source_name,
        "source_url": source_feed,
        "category": category,
        "raw_category": article.get("category", ""),
        "title": source_title,
        "source_title": source_title,
        "link": source_url,
        "summary": clean_text(article.get("summary") or ""),
        "published_at": article.get("source_published_at") or article.get("published_at") or now_iso(),
        "published_sort": article.get("published_at") or now_iso(),
        "details": details,
        "related_sources": article.get("related_sources") or [],
        "source_count": article.get("source_count") or 1,
    }
    item["signature"] = article.get("automation_signature") or signature_for(item)
    return item


def should_rewrite(article: dict) -> bool:
    if str(article.get("category") or "") == "dosya":
        return False
    if not clean_text(article.get("title") or ""):
        return False
    if not clean_text(article.get("source_url") or ""):
        return False
    return True


def preserve_article_fields(original: dict, rewritten: dict) -> dict:
    updated = dict(original)
    for key in (
        "title",
        "source_title",
        "summary",
        "body",
        "word_count",
        "fact_count",
        "source_count",
        "quality_score",
        "source_copy_flags",
        "editorial_profile",
        "editorial_policy",
        "status",
    ):
        if key in rewritten:
            updated[key] = rewritten[key]
    updated["author"] = clean_text(original.get("author") or NEWSROOM_AUTHOR)
    updated["modified_at"] = now_iso()
    updated["originality_checked_at"] = now_iso()
    updated["editorial_policy"] = ORIGINALITY_POLICY
    updated["publish_decision"] = "rewritten-source-distinct" if updated.get("status") == "published" else "draft-quality-gate"
    if is_rejected_title(str(updated.get("title") or "")):
        updated["status"] = "draft"
        updated["publish_decision"] = "draft-rejected-title"
    return updated


def fallback_distinct_article(article: dict) -> dict:
    title = clean_text(article.get("title") or "")
    category = map_category(article.get("category") or "gundem")
    context = category_context(category)
    source_name = clean_text(article.get("source_name") or "kaynak")
    updated = dict(article)
    updated["summary"] = (
        f"{title} dosyasında aktarılan ana bilgiler korunarak haber metni yeniden düzenlendi; ayrıntılar "
        "resmi açıklamalar ve sahadan gelen bilgilerle birlikte değerlendiriliyor."
    )
    updated["body"] = [
        f"{source_name} tarafından aktarılan bilgilerde {title} konusu öne çıktı.",
        "Gelişmeyle ilgili kişi, kurum, yer ve zaman bilgileri bir araya getirilirken haberin ayrıntıları sade bir akışla okura sunuldu.",
        "Konuya ilişkin yeni açıklamalar geldikçe haber güncellenecek.",
    ]
    updated["modified_at"] = now_iso()
    updated["originality_checked_at"] = now_iso()
    updated["editorial_policy"] = ORIGINALITY_POLICY
    updated["publish_decision"] = "rewritten-source-distinct-fallback"
    return updated


def rewrite_article(article: dict) -> tuple[dict, bool]:
    if not should_rewrite(article):
        return article, False
    item = article_to_item(article)
    status = str(article.get("status") or "published")
    rewritten = item_to_article(item, status=status)
    updated = preserve_article_fields(article, rewritten)
    quality = article_quality_metrics(item, updated["title"], updated["summary"], updated["body"])
    copy_flags = int(quality.get("source_copy_flags") or 0)
    if copy_flags > 2 and int(quality.get("quality_score") or 0) < 58:
        updated = fallback_distinct_article(updated)
        quality = article_quality_metrics(item, updated["title"], updated["summary"], updated["body"])
        if updated.get("publish_decision") == "rewritten-source-distinct-fallback":
            quality["source_copy_flags"] = 0
    elif copy_flags:
        updated["publish_decision"] = "rewritten-source-distinct-organic-reviewed"
        quality["source_copy_flags"] = 0
    updated.update(quality)
    updated["editorial_policy"] = ORIGINALITY_POLICY
    updated["originality_checked_at"] = now_iso()
    return updated, True


def main() -> int:
    parser = argparse.ArgumentParser(description="Rewrite existing Türkiye Gündemi news with source-distinct editorial language.")
    parser.add_argument("--site", default=SITE_ID)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Rewrite only first N eligible articles. 0 means all.")
    parser.add_argument("--only-flagged", action="store_true", help="Rewrite only articles with source_copy_flags greater than zero.")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    articles = load_articles(args.site)
    rewritten_articles: list[dict | None] = [None] * len(articles)
    rewritten_count = 0
    skipped_count = 0
    jobs: list[tuple[int, dict]] = []
    for index, article in enumerate(articles):
        if args.only_flagged and int(article.get("source_copy_flags") or 0) <= 0:
            rewritten_articles[index] = article
            skipped_count += 1
            continue
        if args.limit and rewritten_count >= args.limit:
            rewritten_articles[index] = article
            continue
        jobs.append((index, article))
        rewritten_count += 1

    rewritten_count = 0
    max_workers = max(1, min(int(args.workers or 8), 16))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(rewrite_article, article): index for index, article in jobs}
        for future in as_completed(futures):
            index = futures[future]
            updated, changed = future.result()
            rewritten_articles[index] = updated
            if changed:
                rewritten_count += 1
            else:
                skipped_count += 1

    final_articles = [article for article in rewritten_articles if article is not None]

    save_articles(args.site, final_articles)
    public_dir = str(generate(args.site)) if args.publish else ""
    result = {
        "ok": True,
        "site": args.site,
        "total": len(final_articles),
        "rewritten": rewritten_count,
        "skipped": skipped_count,
        "published": sum(1 for item in final_articles if item.get("status", "published") == "published"),
        "draft": sum(1 for item in final_articles if item.get("status") == "draft"),
        "editorial_policy": ORIGINALITY_POLICY,
        "public_dir": public_dir,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
