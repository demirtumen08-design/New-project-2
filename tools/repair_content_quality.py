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
    DEFAULT_MIN_PUBLISH_SCORE,
    HEADLINE_ABSOLUTE_MAX_CHARS,
    HEADLINE_LONG_MAX_CHARS,
    article_quality_metrics,
    body_has_complete_sentences,
    clean_text,
    concise_headline,
    has_encoding_damage,
    headline_allowed_max,
    headline_has_complete_predicate,
    headline_is_incomplete,
    is_publishable_article,
    is_rejected_title,
    map_category,
    sentence_is_complete,
    story_preserves_required_meaning,
    title_preserves_meaning,
)
from src.growth_os.sitegen import generate  # noqa: E402
from tools.rewrite_existing_news_originality import article_to_item, rewrite_article  # noqa: E402


SITE_ID = "turkiye-gundemi"


def local_article_facts(article: dict) -> list[str]:
    facts: list[str] = []
    for key in ("source_title", "summary", "title"):
        value = clean_text(article.get(key) or "")
        if value:
            facts.append(value)
    body = article.get("body") or []
    body_parts = body if isinstance(body, list) else [str(body)]
    for part in body_parts[:10]:
        value = clean_text(part)
        if value:
            facts.append(value)
    return facts


def body_parts(article: dict) -> list[str]:
    body = article.get("body") or []
    return [clean_text(part) for part in (body if isinstance(body, list) else [str(body)]) if clean_text(part)]


def quality_reasons(article: dict, *, enforce_score: bool = False) -> list[str]:
    if str(article.get("category") or "") == "dosya":
        return []
    status = str(article.get("status") or "published")
    if status != "published" and str(article.get("publish_decision") or "") != "draft-content-quality-gate":
        return []
    title = clean_text(article.get("title") or "")
    summary = clean_text(article.get("summary") or "")
    body = body_parts(article)
    source_title = clean_text(article.get("source_title") or title)
    category = map_category(article.get("category") or "gundem")
    facts = local_article_facts(article)
    reasons: list[str] = []
    raw_body = article.get("body") or []
    raw_body_parts = raw_body if isinstance(raw_body, list) else [str(raw_body)]
    if (
        str(article.get("title") or "") != title
        or str(article.get("summary") or "") != summary
        or [str(part) for part in raw_body_parts if str(part)] != body
    ):
        reasons.append("text_normalization")
    if not title or is_rejected_title(title):
        reasons.append("rejected_title")
    if has_encoding_damage(" ".join([title, summary, *body])):
        reasons.append("encoding_damage")
    if headline_is_incomplete(title) or not headline_has_complete_predicate(title):
        reasons.append("incomplete_title")
    if source_title and not title_preserves_meaning(title, source_title):
        reasons.append("title_meaning_loss")
    if len(title) > min(HEADLINE_ABSOLUTE_MAX_CHARS, HEADLINE_LONG_MAX_CHARS):
        reasons.append("headline_too_long")
    if not sentence_is_complete(summary):
        reasons.append("incomplete_spot")
    if not body_has_complete_sentences(body):
        reasons.append("incomplete_body")
    if source_title and not story_preserves_required_meaning(title, summary, body, source_title, facts):
        reasons.append("story_meaning_loss")
    if not is_publishable_article(title, summary, body, source_title=source_title, facts=facts):
        reasons.append("publish_gate")
    if enforce_score:
        item = article_to_item_without_fetch(article)
        quality = article_quality_metrics(item, title, summary, body)
        if int(quality.get("quality_score") or 0) < DEFAULT_MIN_PUBLISH_SCORE:
            reasons.append("low_quality_score")
    return sorted(set(reasons))


def article_to_item_without_fetch(article: dict) -> dict:
    source_title = clean_text(article.get("source_title") or article.get("title") or "")
    body = body_parts(article)
    return {
        "source": clean_text(article.get("source_name") or "Kaynak"),
        "source_url": clean_text(article.get("source_feed") or ""),
        "category": map_category(article.get("category") or "gundem"),
        "raw_category": article.get("category", ""),
        "title": source_title,
        "source_title": source_title,
        "link": clean_text(article.get("source_url") or ""),
        "summary": clean_text(article.get("summary") or ""),
        "published_at": article.get("source_published_at") or article.get("published_at") or now_iso(),
        "details": {"sentences": [clean_text(" ".join([article.get("summary") or "", *body]))]},
        "related_sources": article.get("related_sources") or [],
        "source_count": article.get("source_count") or 1,
    }


def verify_or_draft(article: dict, reasons: list[str]) -> dict:
    title = clean_text(article.get("title") or "")
    summary = clean_text(article.get("summary") or "")
    body = body_parts(article)
    article["title"] = title
    article["summary"] = summary
    article["body"] = body
    article["image_alt"] = clean_text(article.get("image_alt") or title)
    source_title = clean_text(article.get("source_title") or title)
    facts = local_article_facts(article)
    category = map_category(article.get("category") or "gundem")
    concise = concise_headline(title, source_title, facts, category)
    if concise and concise != title:
        article["title"] = concise
        article["image_alt"] = concise
        title = concise
    item = article_to_item_without_fetch(article)
    quality = article_quality_metrics(item, title, summary, body)
    article.update(quality)
    if not is_publishable_article(
        title,
        summary,
        body,
        min_quality_score=DEFAULT_MIN_PUBLISH_SCORE,
        quality_score=int(quality.get("quality_score") or 0),
        source_title=source_title,
        facts=facts,
    ):
        article["status"] = "draft"
        article["publish_decision"] = "draft-content-quality-gate"
    else:
        article["status"] = "published"
        article["publish_decision"] = "published-content-quality-verified"
    article["content_quality_reasons"] = ", ".join(reasons)
    article["content_quality_checked_at"] = now_iso()
    article["modified_at"] = now_iso()
    return article


def repair_one(article: dict, reasons: list[str]) -> tuple[dict, bool]:
    if not reasons:
        return article, False
    if set(reasons) <= {"text_normalization", "headline_too_long"}:
        updated = verify_or_draft(article, reasons)
        return updated, updated != article
    try:
        rewritten, changed = rewrite_article(article)
    except Exception:
        rewritten, changed = article, False
    updated = verify_or_draft(rewritten, reasons)
    return updated, bool(changed or updated != article)


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair title, spot and body completeness without meaning loss.")
    parser.add_argument("--site", default=SITE_ID)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--enforce-score", action="store_true")
    args = parser.parse_args()

    articles = load_articles(args.site)
    reasons_by_index: dict[int, list[str]] = {}
    for index, article in enumerate(articles):
        reasons = quality_reasons(article, enforce_score=args.enforce_score)
        if reasons:
            reasons_by_index[index] = reasons
            if args.limit and len(reasons_by_index) >= args.limit:
                break

    changed = 0
    drafted = 0
    repaired_indexes = set(reasons_by_index)
    updated_articles = list(articles)
    if not args.dry_run and reasons_by_index:
        max_workers = max(1, min(int(args.workers or 8), 16))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(repair_one, articles[index], reasons): index
                for index, reasons in reasons_by_index.items()
            }
            for future in as_completed(futures):
                index = futures[future]
                updated, did_change = future.result()
                updated_articles[index] = updated
                if did_change:
                    changed += 1
                if updated.get("status") == "draft":
                    drafted += 1

        save_articles(args.site, updated_articles)

    public_dir = str(generate(args.site)) if args.publish and not args.dry_run else ""
    result = {
        "ok": True,
        "site": args.site,
        "checked": len(articles),
        "flagged": len(repaired_indexes),
        "changed": changed,
        "drafted": drafted,
        "published": sum(1 for item in updated_articles if item.get("status", "published") == "published"),
        "draft": sum(1 for item in updated_articles if item.get("status") == "draft"),
        "public_dir": public_dir,
        "sample": [
            {
                "slug": articles[index].get("slug"),
                "title": clean_text(articles[index].get("title") or ""),
                "reasons": reasons,
            }
            for index, reasons in list(reasons_by_index.items())[:25]
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
