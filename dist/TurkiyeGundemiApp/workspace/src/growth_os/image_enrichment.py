from __future__ import annotations

import html
import json
import mimetypes
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .config import get_site, project_path
from .content_store import load_articles, now_iso, save_articles
from .sitegen import generate as generate_site

USER_AGENT = "Mozilla/5.0 (compatible; TurkiyeGundemiImageBot/1.0; +https://turkiyegundemi.com)"
REQUEST_TIMEOUT = 18
MAX_IMAGE_BYTES = 8_000_000
PLACEHOLDER_IMAGES = {
    "/assets/images/ankara.png",
    "/assets/images/ekonomi.png",
    "/assets/images/teknoloji.png",
}
CONTENT_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def default_image_for_category(category: str) -> str:
    mapping = {
        "ekonomi": "/assets/images/ekonomi.png",
        "teknoloji": "/assets/images/teknoloji.png",
    }
    return mapping.get(str(category or "").strip(), "/assets/images/ankara.png")


class ImageCandidateParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.meta_alt = ""
        self.candidates: list[dict[str, Any]] = []

    def add_candidate(self, url: str, *, score: int, alt: str = "", source: str = "page") -> None:
        normalized = normalize_url(url, self.base_url)
        if not normalized or is_bad_image_url(normalized):
            return
        self.candidates.append(
            {
                "url": normalized,
                "score": score,
                "alt": clean_text(alt),
                "source": source,
            }
        )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {str(key).lower(): (value or "") for key, value in attrs}
        if tag == "meta":
            key = (data.get("property") or data.get("name") or data.get("itemprop") or "").strip().lower()
            content = data.get("content", "")
            if key in {"og:image", "og:image:url", "twitter:image", "twitter:image:src", "image", "thumbnailurl"}:
                self.add_candidate(content, score=160, alt=self.meta_alt, source=f"meta:{key}")
            elif key in {"og:image:alt", "twitter:image:alt"}:
                self.meta_alt = clean_text(content)
            return
        if tag == "link":
            rel = data.get("rel", "").lower()
            href = data.get("href", "")
            if "image_src" in rel or ("preload" in rel and data.get("as", "").lower() == "image"):
                self.add_candidate(href, score=115, source=f"link:{rel}")
            return
        if tag != "img":
            return
        source = data.get("src") or data.get("data-src") or data.get("data-original") or data.get("data-lazy-src")
        if not source:
            return
        classes = " ".join([data.get("class", ""), data.get("id", "")]).lower()
        score = 50
        if any(token in classes for token in ("article", "content", "main", "hero", "lead", "featured", "news", "story", "post")):
            score += 35
        if any(token in classes for token in ("logo", "icon", "sprite", "avatar", "banner", "ads", "advert", "footer", "header")):
            score -= 55
        width = parse_int(data.get("width"))
        height = parse_int(data.get("height"))
        if width >= 400 or height >= 300:
            score += 15
        alt = data.get("alt", "")
        if alt:
            score += 5
        self.add_candidate(source, score=score, alt=alt, source="img")


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or "")).strip())


def parse_int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def normalize_url(url: str, base_url: str) -> str:
    value = clean_text(url)
    if not value:
        return ""
    if value.startswith("//"):
        parsed_base = urllib.parse.urlparse(base_url)
        return f"{parsed_base.scheme or 'https'}:{value}"
    normalized = urllib.parse.urljoin(base_url, value)
    parsed = urllib.parse.urlparse(normalized)
    if parsed.scheme not in {"http", "https"}:
        return ""
    return urllib.parse.urlunparse(parsed._replace(fragment=""))


def is_bad_image_url(url: str) -> bool:
    lowered = url.casefold()
    blocked = [
        "logo",
        "icon",
        "sprite",
        "avatar",
        "favicon",
        "blank.",
        "placeholder",
        "analytics",
        "pixel",
        "doubleclick",
        "/ads/",
        "advert",
        "reklam",
    ]
    return any(token in lowered for token in blocked)


def fetch_text(url: str) -> tuple[str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        payload = response.read(1_000_000)
        content_type = response.headers.get("content-type", "")
        final_url = response.geturl()
    charset = "utf-8"
    match = re.search(r"charset=([\w-]+)", content_type, re.I)
    if match:
        charset = match.group(1)
    try:
        page = payload.decode(charset, errors="replace")
    except LookupError:
        page = payload.decode("utf-8", errors="replace")
    return page, final_url


def extract_jsonld_candidates(page: str, base_url: str) -> list[dict[str, Any]]:
    matches = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page,
        re.I | re.S,
    )
    candidates: list[dict[str, Any]] = []
    for raw in matches:
        text = html.unescape(raw).strip()
        if not text:
            continue
        try:
            data = json.loads(text)
        except Exception:
            continue
        for image_url in find_jsonld_images(data):
            normalized = normalize_url(image_url, base_url)
            if normalized and not is_bad_image_url(normalized):
                candidates.append({"url": normalized, "score": 145, "alt": "", "source": "jsonld"})
    return candidates


def find_jsonld_images(value: Any) -> list[str]:
    results: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = str(key).lower()
            if lowered in {"image", "thumbnailurl", "contenturl", "url"}:
                if isinstance(nested, str):
                    results.append(nested)
                elif isinstance(nested, dict):
                    for candidate_key in ("url", "contentUrl"):
                        if nested.get(candidate_key):
                            results.append(str(nested[candidate_key]))
                elif isinstance(nested, list):
                    for item in nested:
                        if isinstance(item, str):
                            results.append(item)
                        elif isinstance(item, dict) and item.get("url"):
                            results.append(str(item["url"]))
            else:
                results.extend(find_jsonld_images(nested))
    elif isinstance(value, list):
        for item in value:
            results.extend(find_jsonld_images(item))
    return results


def discover_image_candidates(article_url: str) -> list[dict[str, Any]]:
    page, final_url = fetch_text(article_url)
    parser = ImageCandidateParser(final_url)
    try:
        parser.feed(page)
    except Exception:
        pass
    candidates = parser.candidates + extract_jsonld_candidates(page, final_url)
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in sorted(candidates, key=lambda item: int(item.get("score", 0)), reverse=True):
        url = candidate.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(candidate)
    return unique[:12]


def detect_extension(content_type: str, url: str, payload: bytes) -> str:
    media = content_type.split(";", 1)[0].strip().lower()
    if media in CONTENT_EXTENSIONS:
        return CONTENT_EXTENSIONS[media]
    path = urllib.parse.urlparse(url).path
    guessed = Path(path).suffix.lower()
    if guessed in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ".jpg" if guessed == ".jpeg" else guessed
    if payload.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return ".webp"
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    return ".jpg"


def download_image(site_id: str, slug: str, image_url: str, *, referer: str = "") -> str:
    site = get_site(site_id)
    public_dir = project_path(site["public_dir"])
    target_dir = public_dir / "assets" / "images" / "news"
    target_dir.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": USER_AGENT, "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"}
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(image_url, headers=headers)
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        payload = response.read(MAX_IMAGE_BYTES + 1)
        content_type = response.headers.get("content-type", "")
    if len(payload) > MAX_IMAGE_BYTES:
        raise ValueError("Gorsel dosyasi izin verilen boyutu asiyor")
    media = content_type.split(";", 1)[0].strip().lower()
    if media and not media.startswith("image/"):
        raise ValueError("Kaynak gorsel degil")
    extension = detect_extension(content_type, image_url, payload)
    filename = f"{slug}{extension}"
    target = target_dir / filename
    target.write_bytes(payload)
    return f"/assets/images/news/{filename}"


def image_needs_enrichment(article: dict[str, Any], *, force: bool = False) -> bool:
    image = str(article.get("image") or "").strip()
    if force:
        return True
    if not image:
        return True
    if image.startswith("http://") or image.startswith("https://"):
        return True
    return image in PLACEHOLDER_IMAGES


def enrich_article_image(site_id: str, article: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    updated = dict(article)
    if not image_needs_enrichment(updated, force=force):
        return {"ok": True, "updated": False, "article": updated, "reason": "zaten uygun gorsel var"}

    candidate_urls: list[tuple[str, str, str]] = []
    current = str(updated.get("image") or "").strip()
    if current.startswith(("http://", "https://")):
        candidate_urls.append((current, str(updated.get("image_alt") or updated.get("title") or ""), "existing-remote"))

    source_url = str(updated.get("source_url") or "").strip()
    last_error = ""
    if source_url.startswith(("http://", "https://")):
        try:
            discovered = discover_image_candidates(source_url)
        except Exception as exc:
            discovered = []
            last_error = str(exc)
        for candidate in discovered:
            candidate_urls.append((str(candidate.get("url", "")), str(candidate.get("alt", "")), str(candidate.get("source", "page"))))

    seen: set[str] = set()
    for url, alt, provider in candidate_urls:
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            local_path = download_image(site_id, str(updated.get("slug") or "haber"), url, referer=source_url)
        except Exception as exc:
            last_error = str(exc)
            continue
        updated["image"] = local_path
        updated["image_alt"] = clean_text(alt or updated.get("title") or updated.get("summary") or "")
        updated["image_source_url"] = url
        updated["image_provider"] = provider
        updated["image_enriched_at"] = now_iso()
        return {"ok": True, "updated": True, "article": updated, "reason": "gorsel indirildi"}

    fallback = default_image_for_category(str(updated.get("category") or ""))
    if not str(updated.get("image") or "").strip():
        updated["image"] = fallback
        updated["image_alt"] = clean_text(updated.get("title") or updated.get("summary") or "")
        return {"ok": True, "updated": True, "article": updated, "reason": "kategori varsayilan gorseli atandi"}
    return {
        "ok": False,
        "updated": False,
        "article": updated,
        "reason": last_error or "uygun gorsel bulunamadi",
    }


def enrich_existing_articles(
    site_id: str = "turkiye-gundemi",
    *,
    force: bool = False,
    only_missing: bool = True,
    publish_site: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    articles = load_articles(site_id)
    changed = 0
    scanned = 0
    results: list[dict[str, Any]] = []
    max_items = int(limit) if limit is not None else None
    for index, article in enumerate(articles):
        if max_items is not None and scanned >= max_items:
            break
        if only_missing and not image_needs_enrichment(article, force=force):
            continue
        scanned += 1
        outcome = enrich_article_image(site_id, article, force=force)
        articles[index] = outcome["article"]
        if outcome.get("updated"):
            changed += 1
        results.append(
            {
                "slug": article.get("slug", ""),
                "title": article.get("title", ""),
                "updated": bool(outcome.get("updated")),
                "reason": str(outcome.get("reason", "")),
                "image": outcome["article"].get("image", ""),
            }
        )
    if changed:
        save_articles(site_id, articles)
    public_dir = str(generate_site(site_id)) if publish_site and changed else None
    return {
        "ok": True,
        "site_id": site_id,
        "scanned_count": scanned,
        "updated_count": changed,
        "results": results,
        "public_dir": public_dir,
    }
