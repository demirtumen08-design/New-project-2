from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import get_site, project_path


TR_MAP = str.maketrans(
    {
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
        "Ç": "c",
        "Ğ": "g",
        "İ": "i",
        "I": "i",
        "Ö": "o",
        "Ş": "s",
        "Ü": "u",
    }
)


def slugify(value: str) -> str:
    cleaned = value.translate(TR_MAP)
    cleaned = unicodedata.normalize("NFKD", cleaned).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", cleaned).strip("-").lower()
    return cleaned or "haber"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def article_path(site_id: str) -> Path:
    site = get_site(site_id)
    return project_path(site["content_file"])


def load_articles(site_id: str) -> list[dict[str, Any]]:
    path = article_path(site_id)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        articles = json.load(handle)
    return sorted(articles, key=lambda item: item.get("published_at", ""), reverse=True)


def save_articles(site_id: str, articles: list[dict[str, Any]]) -> None:
    path = article_path(site_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(articles, key=lambda item: item.get("published_at", ""), reverse=True)
    path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_article(raw: dict[str, Any], existing_slug: str | None = None) -> dict[str, Any]:
    title = str(raw.get("title", "")).strip()
    if not title:
        raise ValueError("Baslik zorunlu.")
    slug = str(raw.get("slug") or existing_slug or slugify(title)).strip()
    slug = slugify(slug)
    body_value = raw.get("body", [])
    if isinstance(body_value, str):
        body = [part.strip() for part in re.split(r"\n\s*\n", body_value) if part.strip()]
    else:
        body = [str(part).strip() for part in body_value if str(part).strip()]
    if not body:
        body = [str(raw.get("summary", "")).strip() or title]
    tags_value = raw.get("tags", [])
    if isinstance(tags_value, str):
        tags = [part.strip() for part in tags_value.split(",") if part.strip()]
    else:
        tags = [str(part).strip() for part in tags_value if str(part).strip()]
    published_at = str(raw.get("published_at") or now_iso()).strip()
    modified_at = str(raw.get("modified_at") or now_iso()).strip()
    image = str(raw.get("image") or "/assets/images/ankara.png").strip()
    if not image.startswith("/") and not image.startswith("http"):
        image = "/" + image
    status = str(raw.get("status") or "published").strip()
    if status not in {"draft", "published"}:
        status = "published"
    article = {
        "slug": slug,
        "category": str(raw.get("category") or "gundem").strip(),
        "title": title,
        "summary": str(raw.get("summary") or title).strip(),
        "body": body,
        "author": str(raw.get("author") or "Türkiye Gündemi Haber Merkezi").strip(),
        "published_at": published_at,
        "modified_at": modified_at,
        "image": image,
        "image_alt": str(raw.get("image_alt") or title).strip(),
        "tags": tags,
        "status": status,
    }
    for key in (
        "source_name",
        "source_url",
        "source_feed",
        "source_published_at",
        "automation_signature",
        "imported_at",
        "image_source_url",
        "image_provider",
        "image_enriched_at",
    ):
        if raw.get(key):
            article[key] = str(raw.get(key)).strip()
    return article


def upsert_article(site_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    articles = load_articles(site_id)
    incoming_slug = str(raw.get("slug") or "").strip()
    existing = next((item for item in articles if item.get("slug") == incoming_slug), None)
    article = normalize_article(raw, incoming_slug or None)
    article["modified_at"] = now_iso()
    updated = False
    for index, item in enumerate(articles):
        if item.get("slug") == incoming_slug or item.get("slug") == article["slug"]:
            if existing:
                article["published_at"] = raw.get("published_at") or item.get("published_at") or article["published_at"]
            articles[index] = article
            updated = True
            break
    if not updated:
        articles.append(article)
    save_articles(site_id, articles)
    return article


def delete_article(site_id: str, slug: str) -> bool:
    articles = load_articles(site_id)
    remaining = [item for item in articles if item.get("slug") != slug]
    if len(remaining) == len(articles):
        return False
    save_articles(site_id, remaining)
    return True


def public_url_for(site_id: str) -> str:
    site = get_site(site_id)
    return f"/{site_id}/"
