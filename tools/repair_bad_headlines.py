import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.growth_os.content_store import load_articles, now_iso, save_articles  # noqa: E402
from src.growth_os.news_automation import (  # noqa: E402
    clean_text,
    has_encoding_damage,
    headline_has_complete_predicate,
    headline_is_incomplete,
    headline_too_close,
    make_organic_title,
    normalized_title,
    source_based_headline,
    title_preserves_meaning,
)
from src.growth_os.sitegen import generate  # noqa: E402


def article_facts(article: dict) -> list[str]:
    facts: list[str] = []
    for key in ("source_title", "summary", "title"):
        value = clean_text(article.get(key) or "")
        if value:
            facts.append(value)
    body = article.get("body") or []
    body_parts = body if isinstance(body, list) else [str(body)]
    for part in body_parts[:8]:
        value = clean_text(part)
        if value:
            facts.append(value)
    return facts


def title_reasons(article: dict) -> list[str]:
    title = clean_text(article.get("title") or "")
    source_title = clean_text(article.get("source_title") or "")
    reasons: list[str] = []
    if not title:
        reasons.append("empty")
    if has_encoding_damage(title):
        reasons.append("encoding")
    if headline_is_incomplete(title):
        reasons.append("incomplete")
    if not headline_has_complete_predicate(title):
        reasons.append("missing_predicate")
    if len(title) < 38:
        reasons.append("too_short")
    if source_title and not title_preserves_meaning(title, source_title):
        reasons.append("meaning_loss")
    return reasons


def repaired_title(article: dict) -> str:
    source_title = clean_text(article.get("source_title") or article.get("title") or "")
    facts = article_facts(article)
    category = str(article.get("category") or "gundem")
    title = source_based_headline(source_title, [], category)
    if not acceptable(title, source_title):
        title = make_organic_title(source_title, facts[:2], category, article.get("summary") or "")
    return clean_text(title)


def acceptable(title: str, source_title: str) -> bool:
    if not title or has_encoding_damage(title):
        return False
    if headline_is_incomplete(title) or not headline_has_complete_predicate(title):
        return False
    if source_title and not title_preserves_meaning(title, source_title):
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair damaged, incomplete or source-identical headlines.")
    parser.add_argument("--site", default="turkiye-gundemi")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    articles = load_articles(args.site)
    changed = 0
    drafted = 0
    report = []
    for article in articles:
        if article.get("category") == "dosya" or article.get("status") != "published":
            continue
        reasons = title_reasons(article)
        if not reasons:
            continue
        old_title = clean_text(article.get("title") or "")
        source_title = clean_text(article.get("source_title") or "")
        new_title = repaired_title(article)
        if acceptable(new_title, source_title):
            if not args.dry_run:
                article["title"] = new_title
                article["image_alt"] = new_title
                article["modified_at"] = now_iso()
                article["headline_repair_reasons"] = ", ".join(reasons)
            changed += 1
            report.append({"slug": article.get("slug"), "old": old_title, "new": new_title, "reasons": reasons})
        else:
            if not args.dry_run:
                article["status"] = "draft"
                article["publish_decision"] = "draft-headline-quality-gate"
                article["headline_repair_reasons"] = ", ".join(reasons)
                article["modified_at"] = now_iso()
            drafted += 1
            report.append({"slug": article.get("slug"), "old": old_title, "new": new_title, "reasons": [*reasons, "drafted"]})

    if not args.dry_run:
        save_articles(args.site, articles)
    public_dir = str(generate(args.site)) if args.publish and not args.dry_run else ""
    print(
        json.dumps(
            {
                "ok": True,
                "site": args.site,
                "changed": changed,
                "drafted": drafted,
                "public_dir": public_dir,
                "sample": report[:30],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
