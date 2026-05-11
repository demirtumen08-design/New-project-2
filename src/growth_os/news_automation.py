from __future__ import annotations

import argparse
import email.utils
import hashlib
import html
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .config import ROOT, project_path
from .content_quality import article_quality_flags, is_publication_safe, publication_blocking_flags, repair_title_fragment
from .content_store import load_articles, now_iso, save_articles, slugify, upsert_article
from .image_enrichment import (
    apply_related_visuals,
    default_image_for_category,
    enrich_article_image,
    enrich_existing_articles,
    generate_related_visual,
)
from .runtime_network import heal_network_runtime
from .sitegen import generate as generate_site


USER_AGENT = "Mozilla/5.0 (compatible; TurkiyeGundemiBot/1.0; +https://turkiyegundemi.com)"
SOURCE_CONFIG = ROOT / "config" / "news_sources.json"
STATE_PATH = ROOT / "content" / "turkiye-gundemi" / "news_automation_state.json"
ARTICLE_FETCH_TIMEOUT = 12
MAX_ARTICLE_FACTS = 14
MIN_PUBLIC_BODY_CHARS = 760
MIN_PUBLIC_PARAGRAPHS = 4
NEWSROOM_AUTHOR = "Türkiye Gündemi Haber Merkezi"
MAX_FETCH_LIMIT = 120
MAX_IMPORT_PER_CYCLE = 60
MAX_STATE_SIGNATURES = 5_000
DEFAULT_SOURCE_WORKERS = 6
DEFAULT_ARTICLE_DETAIL_WORKERS = 8
DEFAULT_MIN_PUBLISH_SCORE = 58
SOURCE_FETCH_TIMEOUT = 18
ORIGINALITY_POLICY = "source-distinct-organic-v3"
SOURCE_COPY_RATIO_LIMIT = 0.94
HEADLINE_TARGET_MAX_CHARS = 82
HEADLINE_LONG_MAX_CHARS = 118
HEADLINE_ABSOLUTE_MAX_CHARS = 132
SUMMARY_SOFT_MAX_CHARS = 320

PRIORITY_NEWS_KEYWORDS = {
    "anayasa",
    "bakan",
    "belediye",
    "cumhurbaşkanı",
    "cumhurbaskani",
    "dava",
    "deprem",
    "ekonomi",
    "emekli",
    "enflasyon",
    "faiz",
    "merkez bankasi",
    "piyasa",
    "borsa",
    "dolar",
    "euro",
    "kur",
    "altin",
    "vergi",
    "zam",
    "asgari",
    "butce",
    "ihracat",
    "ithalat",
    "gözaltı",
    "gozalti",
    "işçi",
    "isci",
    "kadın",
    "kadin",
    "mahkeme",
    "meclis",
    "operasyon",
    "parti",
    "savaş",
    "savas",
    "seçim",
    "secim",
    "soruşturma",
    "sorusturma",
    "toplum",
    "tutuklama",
    "yangın",
    "yangin",
}

MOJIBAKE_REPLACEMENTS = {
    "Ã‡": "Ç",
    "Ã§": "ç",
    "ÃĞ": "Ğ",
    "ÄŸ": "ğ",
    "Äž": "Ğ",
    "Ãœ": "Ü",
    "Ã¼": "ü",
    "Ã–": "Ö",
    "Ã¶": "ö",
    "Åž": "Ş",
    "ÅŸ": "ş",
    "Ä°": "İ",
    "Ä±": "ı",
    "â€™": "'",
    "â€œ": '"',
    "â€": '"',
    "â€": '"',
    "â€¦": "...",
    "â€“": "-",
    "â€”": "-",
    "ï»¿": "",
    "�": "",
}


def load_source_config() -> dict[str, Any]:
    if not SOURCE_CONFIG.exists():
        return {"sources": [], "defaults": {}}
    return json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))


def clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def load_runtime_defaults(config: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = (config or load_source_config()).get("defaults", {})
    status = str(raw.get("status", "draft")).strip()
    if status not in {"draft", "published"}:
        status = "draft"
    return {
        "limit": clamp_int(raw.get("limit", 60), 60, 1, MAX_FETCH_LIMIT),
        "max_import_per_cycle": clamp_int(raw.get("max_import_per_cycle", 8), 8, 1, MAX_IMPORT_PER_CYCLE),
        "status": status,
        "publish_site_after_import": bool(raw.get("publish_site_after_import", False)),
        "image_enrichment": bool(raw.get("image_enrichment", True)),
        "scan_interval_seconds": clamp_int(raw.get("scan_interval_seconds", 900), 900, 60, 86_400),
        "source_workers": clamp_int(raw.get("source_workers", DEFAULT_SOURCE_WORKERS), DEFAULT_SOURCE_WORKERS, 1, 16),
        "article_detail_workers": clamp_int(raw.get("article_detail_workers", DEFAULT_ARTICLE_DETAIL_WORKERS), DEFAULT_ARTICLE_DETAIL_WORKERS, 1, 24),
        "min_publish_score": clamp_int(raw.get("min_publish_score", DEFAULT_MIN_PUBLISH_SCORE), DEFAULT_MIN_PUBLISH_SCORE, 0, 100),
        "source_error_cooldown_seconds": clamp_int(raw.get("source_error_cooldown_seconds", 1_800), 1_800, 60, 86_400),
        "max_source_backoff_seconds": clamp_int(raw.get("max_source_backoff_seconds", 21_600), 21_600, 300, 172_800),
    }


def normalize_state(state: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(state or {})
    imported = data.get("imported_signatures", [])
    if not isinstance(imported, list):
        imported = []
    failures = data.get("source_failures", {})
    if not isinstance(failures, dict):
        failures = {}
    normalized_failures: dict[str, dict[str, Any]] = {}
    for key, value in failures.items():
        if not isinstance(value, dict):
            continue
        normalized_failures[str(key)] = {
            "failures": clamp_int(value.get("failures", 0), 0, 0, 1_000),
            "last_error": str(value.get("last_error", "")).strip(),
            "last_failed_at": str(value.get("last_failed_at", "")).strip(),
            "next_retry_at": str(value.get("next_retry_at", "")).strip(),
        }
    data["imported_signatures"] = [str(item).strip() for item in imported if str(item).strip()][-MAX_STATE_SIGNATURES:]
    data["source_failures"] = normalized_failures
    if not isinstance(data.get("last_source_status"), list):
        data["last_source_status"] = []
    return data


def source_state_key(source: dict[str, Any]) -> str:
    return slugify(str(source.get("name") or source.get("url") or "kaynak"))


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        try:
            parsed = email.utils.parsedate_to_datetime(text)
        except Exception:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone()


def source_backoff_seconds(failures: int, defaults: dict[str, Any]) -> int:
    base = defaults["source_error_cooldown_seconds"]
    return min(base * (2 ** max(0, failures - 1)), defaults["max_source_backoff_seconds"])


def source_cooldown_remaining(
    source: dict[str, Any],
    state: dict[str, Any],
    defaults: dict[str, Any],
    now: datetime,
) -> int:
    info = state.get("source_failures", {}).get(source_state_key(source), {})
    retry_at = parse_datetime(str(info.get("next_retry_at", "")).strip())
    if retry_at is None:
        return 0
    remaining = int((retry_at - now).total_seconds())
    return max(0, min(remaining, defaults["max_source_backoff_seconds"]))


def mark_source_failure(
    source: dict[str, Any],
    state: dict[str, Any],
    defaults: dict[str, Any],
    now: datetime,
    error: str,
) -> int:
    key = source_state_key(source)
    previous = state.setdefault("source_failures", {}).get(key, {})
    failures = clamp_int(previous.get("failures", 0), 0, 0, 1_000) + 1
    cooldown = source_backoff_seconds(failures, defaults)
    state["source_failures"][key] = {
        "failures": failures,
        "last_error": clean_text(error),
        "last_failed_at": now.isoformat(timespec="seconds"),
        "next_retry_at": (now + timedelta(seconds=cooldown)).isoformat(timespec="seconds"),
    }
    return cooldown


def clear_source_failure(source: dict[str, Any], state: dict[str, Any]) -> None:
    state.get("source_failures", {}).pop(source_state_key(source), None)


def fetch_latest_news(limit: int | None = None, *, state: dict[str, Any] | None = None) -> dict[str, Any]:
    config = load_source_config()
    defaults = load_runtime_defaults(config)
    state = normalize_state(state)
    now = datetime.now(timezone.utc).astimezone()
    sources = [source for source in config.get("sources", []) if source.get("enabled", True)]
    items: list[dict[str, Any]] = []
    status: list[dict[str, Any]] = []
    ready_sources: list[dict[str, Any]] = []
    limit = clamp_int(limit if limit is not None else defaults["limit"], defaults["limit"], 1, MAX_FETCH_LIMIT)

    for source in sources:
        cooldown_remaining = source_cooldown_remaining(source, state, defaults, now)
        if cooldown_remaining:
            status.append(
                {
                    "source": source.get("name", "Kaynak"),
                    "status": "cooldown",
                    "message": f"Kaynak geçici olarak beklemede, {cooldown_remaining} saniye sonra yeniden denenecek",
                    "retry_in_seconds": cooldown_remaining,
                }
            )
            continue
        ready_sources.append(source)

    with ThreadPoolExecutor(max_workers=defaults["source_workers"]) as executor:
        futures = {executor.submit(fetch_feed, source): source for source in ready_sources}
        for future in as_completed(futures):
            source = futures[future]
            try:
                fetched = future.result()
            except Exception as exc:  # noqa: BLE001 - surfaced in admin panel
                cooldown = mark_source_failure(source, state, defaults, now, str(exc))
                status.append(
                    {
                        "source": source.get("name", "Kaynak"),
                        "status": "error",
                        "message": str(exc),
                        "retry_in_seconds": cooldown,
                    }
                )
                continue
            items.extend(fetched)
            clear_source_failure(source, state)
            status.append({"source": source["name"], "status": "ok", "message": f"{len(fetched)} haber alındı"})

    deduped = dedupe_items(items)
    for item in deduped:
        item["news_score"] = news_item_score(item, now)
    deduped.sort(key=lambda item: (item.get("news_score", 0), item["published_sort"]), reverse=True)
    selected = deduped[:limit]

    with ThreadPoolExecutor(max_workers=defaults["article_detail_workers"]) as executor:
        futures = {executor.submit(fetch_article_details, item.get("link", "")): item for item in selected}
        for future in as_completed(futures):
            item = futures[future]
            try:
                item["details"] = future.result()
            except Exception:
                item["details"] = {"sentences": []}

    selected.sort(key=lambda item: (item.get("news_score", 0), item["published_sort"]), reverse=True)
    for index, item in enumerate(selected, start=1):
        item["rank"] = index
        item["variants"] = build_variants(item)
        item["published_sort"] = item["published_sort"].isoformat()
    return {
        "ok": True,
        "generated_at": now_iso(),
        "source_status": sorted(status, key=lambda item: str(item.get("source", ""))),
        "items": selected,
        "live_item_count": len(deduped),
        "state": state,
    }


def fetch_feed(source: dict[str, Any]) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        str(source["url"]),
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"},
    )
    with urllib.request.urlopen(request, timeout=SOURCE_FETCH_TIMEOUT) as response:
        payload = response.read()

    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return parse_loose_rss(payload, source)
    if root.tag.endswith("rss"):
        return parse_rss(root, source)
    if root.tag.endswith("feed"):
        return parse_atom(root, source)
    if root.tag.endswith("RDF"):
        return parse_rdf(root, source)
    return []


def parse_loose_rss(payload: bytes, source: dict[str, Any]) -> list[dict[str, Any]]:
    text = payload.decode("utf-8", errors="replace")
    text = repair_mojibake(text)
    item_blocks = re.findall(r"<item\b[^>]*>(.*?)</item>", text, flags=re.I | re.S)
    results: list[dict[str, Any]] = []
    for block in item_blocks:
        title = loose_tag_value(block, "title")
        link = loose_tag_value(block, "link")
        summary = clean_description(loose_tag_value(block, "description"))
        raw_category = loose_tag_value(block, "category")
        published_at, published_sort = parse_date(loose_tag_value(block, "pubDate") or loose_tag_value(block, "published"))
        results.append(make_item(source, title, link, summary, raw_category, published_at, published_sort, image_url=loose_image_url(block)))
    return [item for item in results if item]


def loose_tag_value(block: str, tag: str) -> str:
    match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", block, flags=re.I | re.S)
    if not match:
        return ""
    value = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", match.group(1), flags=re.S)
    return clean_description(value)


def loose_image_url(block: str) -> str:
    patterns = (
        r"<(?:media:)?(?:content|thumbnail)\b[^>]*\burl=[\"']([^\"']+)[\"']",
        r"<enclosure\b[^>]*\burl=[\"']([^\"']+)[\"'][^>]*(?:type=[\"']image/[^\"']+[\"'])?",
        r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']",
    )
    for pattern in patterns:
        match = re.search(pattern, block, flags=re.I | re.S)
        if match:
            return clean_text(html.unescape(match.group(1)))
    return ""


def element_local_name(node: ET.Element) -> str:
    return str(node.tag).rsplit("}", 1)[-1].lower()


def element_image_url(node: ET.Element) -> str:
    for child in node.iter():
        name = element_local_name(child)
        attrs = {str(key).lower(): str(value) for key, value in child.attrib.items()}
        if name in {"content", "thumbnail"} and attrs.get("url"):
            if name == "thumbnail" or attrs.get("medium") == "image" or str(attrs.get("type", "")).startswith("image/"):
                return clean_text(attrs["url"])
        if name == "enclosure" and attrs.get("url") and str(attrs.get("type", "")).startswith("image/"):
            return clean_text(attrs["url"])
        if name in {"image", "thumbnailurl"}:
            url = attrs.get("url") or attrs.get("href") or "".join(child.itertext())
            if url:
                return clean_text(url)
    return ""


def parse_rss(root: ET.Element, source: dict[str, Any]) -> list[dict[str, Any]]:
    channel = root.find("channel")
    if channel is None:
        return []
    results = []
    for item in channel.findall("item"):
        title = clean_text(item.findtext("title"))
        link = clean_text(item.findtext("link"))
        summary = clean_description(item.findtext("description") or "")
        raw_category = clean_text(item.findtext("category"))
        published_at, published_sort = parse_date(item.findtext("pubDate"))
        image_url = element_image_url(item)
        results.append(make_item(source, title, link, summary, raw_category, published_at, published_sort, image_url=image_url))
    return [item for item in results if item]


def parse_rdf(root: ET.Element, source: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for item in root.findall(".//{http://purl.org/rss/1.0/}item"):
        title = clean_text(item.findtext("{http://purl.org/rss/1.0/}title") or item.findtext("title"))
        link = clean_text(item.findtext("{http://purl.org/rss/1.0/}link") or item.findtext("link"))
        summary = clean_description(item.findtext("{http://purl.org/rss/1.0/}description") or item.findtext("description") or "")
        raw_category = clean_text(item.findtext("{http://purl.org/dc/elements/1.1/}subject") or "")
        published_at, published_sort = parse_date(item.findtext("{http://purl.org/dc/elements/1.1/}date") or "")
        image_url = element_image_url(item)
        results.append(make_item(source, title, link, summary, raw_category, published_at, published_sort, image_url=image_url))
    return [item for item in results if item]


def parse_atom(root: ET.Element, source: dict[str, Any]) -> list[dict[str, Any]]:
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns) or root.findall("entry")
    results = []
    for entry in entries:
        title = clean_text(find_atom_text(entry, "title"))
        link = atom_link(entry)
        summary = clean_description(find_atom_text(entry, "summary") or find_atom_text(entry, "content"))
        raw_category = atom_category(entry)
        published_at, published_sort = parse_date(find_atom_text(entry, "published") or find_atom_text(entry, "updated"))
        image_url = element_image_url(entry)
        results.append(make_item(source, title, link, summary, raw_category, published_at, published_sort, image_url=image_url))
    return [item for item in results if item]


def find_atom_text(entry: ET.Element, name: str) -> str:
    node = entry.find(f"{{http://www.w3.org/2005/Atom}}{name}")
    if node is None:
        node = entry.find(name)
    return "" if node is None else "".join(node.itertext())


def atom_link(entry: ET.Element) -> str:
    links = list(entry.findall("{http://www.w3.org/2005/Atom}link")) + list(entry.findall("link"))
    for link in links:
        rel = link.attrib.get("rel", "alternate")
        href = link.attrib.get("href", "")
        if href and rel == "alternate":
            return href.strip()
    if links:
        return links[0].attrib.get("href", "").strip()
    return ""


def atom_category(entry: ET.Element) -> str:
    node = entry.find("{http://www.w3.org/2005/Atom}category")
    if node is None:
        node = entry.find("category")
    if node is None:
        return ""
    return clean_text(node.attrib.get("term") or node.attrib.get("label") or "".join(node.itertext()))


def make_item(
    source: dict[str, Any],
    title: str,
    link: str,
    summary: str,
    raw_category: str,
    published_at: str,
    published_sort: datetime,
    *,
    image_url: str = "",
) -> dict[str, Any] | None:
    if not title or not link:
        return None
    if is_rejected_title(title):
        return None
    category = infer_category(raw_category, str(source.get("category", "")), link)
    item = {
        "source": source["name"],
        "source_url": source["url"],
        "source_priority": clamp_int(source.get("priority", 50), 50, 0, 100),
        "category": category,
        "raw_category": raw_category,
        "title": title,
        "link": link,
        "canonical_link": canonical_url(link),
        "summary": summary or title,
        "image_url": clean_text(image_url),
        "published_at": published_at,
        "published_sort": published_sort,
    }
    item["signature"] = signature_for(item)
    return item


def infer_category(raw_category: str, source_category: str, link: str) -> str:
    mapped_raw = map_category(raw_category)
    if raw_category and mapped_raw != "gundem":
        return mapped_raw
    lowered_link = clean_text(link).casefold()
    link_patterns = {
        "/spor": "spor",
        "/ekonomi": "ekonomi",
        "/dunya": "dunya",
        "/dünya": "dunya",
        "/teknoloji": "teknoloji",
        "/kultur": "kultur",
        "/kültür": "kultur",
        "/magazin": "kultur",
    }
    for pattern, category in link_patterns.items():
        if pattern in lowered_link:
            return category
    return map_category(source_category or raw_category or "gundem")


def canonical_url(value: str) -> str:
    text = clean_text(value)
    if not text:
        return ""
    parsed = urllib.parse.urlsplit(text)
    host = parsed.netloc.lower().removeprefix("www.")
    path = re.sub(r"/+$", "", parsed.path or "/")
    query_pairs = [
        (key, val)
        for key, val in urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
        if not key.lower().startswith(("utm_", "fbclid", "gclid", "yclid"))
    ]
    query = urllib.parse.urlencode(query_pairs)
    return urllib.parse.urlunsplit((parsed.scheme.lower() or "https", host, path, query, ""))


def title_tokens(title: str) -> set[str]:
    stopwords = {"olan", "icin", "için", "daha", "sonra", "şekilde", "haber", "son", "dakika", "ile", "bir", "ve"}
    return {
        slugify(word)
        for word in re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü0-9']{4,}", clean_text(title))
        if slugify(word) and slugify(word) not in stopwords
    }


def title_similarity(first: set[str], second: set[str]) -> float:
    if len(first) < 4 or len(second) < 4:
        return 0.0
    return len(first & second) / max(1, min(len(first), len(second)))


def merge_duplicate_item(primary: dict[str, Any], duplicate: dict[str, Any]) -> None:
    sources = list(primary.get("related_sources") or [])
    source = clean_text(str(duplicate.get("source") or ""))
    if source and source != primary.get("source") and source not in sources:
        sources.append(source)
    primary["related_sources"] = sources[:8]
    primary["source_count"] = 1 + len(primary["related_sources"])
    if len(clean_text(duplicate.get("summary", ""))) > len(clean_text(primary.get("summary", ""))):
        primary["summary"] = duplicate["summary"]
    if duplicate.get("published_sort") and duplicate["published_sort"] > primary.get("published_sort", duplicate["published_sort"]):
        primary["published_sort"] = duplicate["published_sort"]
        primary["published_at"] = duplicate.get("published_at", primary.get("published_at", ""))


def dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    title_index: list[tuple[set[str], dict[str, Any]]] = []
    deduped: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda value: value.get("published_sort", datetime.min.replace(tzinfo=timezone.utc)), reverse=True):
        url_key = canonical_url(str(item.get("canonical_link") or item.get("link") or ""))
        tokens = title_tokens(str(item.get("title") or ""))
        duplicate = by_url.get(url_key) if url_key else None
        if duplicate is None:
            duplicate = next((existing for existing_tokens, existing in title_index if title_similarity(tokens, existing_tokens) >= 0.78), None)
        if duplicate is not None:
            merge_duplicate_item(duplicate, item)
            continue
        item["source_count"] = 1
        item["related_sources"] = []
        if url_key:
            by_url[url_key] = item
        title_index.append((tokens, item))
        deduped.append(item)
    return deduped


def news_item_score(item: dict[str, Any], now: datetime) -> int:
    score = clamp_int(item.get("source_priority", 50), 50, 0, 100) // 2
    published = item.get("published_sort")
    if isinstance(published, datetime):
        age_minutes = max(0, int((now - published).total_seconds() / 60))
        if age_minutes <= 45:
            score += 65
        elif age_minutes <= 180:
            score += 50
        elif age_minutes <= 720:
            score += 30
        elif age_minutes <= 1440:
            score += 15
    category = str(item.get("category") or "")
    if category == "son-dakika":
        score += 36
    elif category == "gundem":
        score += 28
    elif category == "ekonomi":
        score += 32
    elif category == "dunya":
        score += 16
    text = clean_text(" ".join([str(item.get("title") or ""), str(item.get("summary") or "")])).casefold()
    score += min(36, sum(9 for keyword in PRIORITY_NEWS_KEYWORDS if keyword in text))
    if category == "ekonomi" and any(keyword in text for keyword in ("faiz", "enflasyon", "merkez bank", "borsa", "dolar", "altin", "altın", "vergi", "zam")):
        score += 18
    if any(keyword in text for keyword in ("meclis", "bakan", "parti", "belediye", "seçim", "secim", "cumhurbaşkanı", "cumhurbaskani")):
        score += 16
    score += min(18, max(0, int(item.get("source_count") or 1) - 1) * 6)
    if is_rejected_title(str(item.get("title") or "")):
        score -= 100
    return max(0, min(score, 220))


def fetch_article_details(url: str) -> dict[str, Any]:
    if not url:
        return {"sentences": []}
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=ARTICLE_FETCH_TIMEOUT) as response:
            payload = response.read(900_000)
            content_type = response.headers.get("content-type", "")
            final_url = response.geturl()
    except Exception:
        return {"sentences": []}

    charset = "utf-8"
    match = re.search(r"charset=([\w-]+)", content_type, re.I)
    if match:
        charset = match.group(1)
    try:
        page = payload.decode(charset, errors="replace")
    except LookupError:
        page = payload.decode("utf-8", errors="replace")

    page_title = extract_page_title(page)
    meta_description = extract_meta_description(page)
    jsonld_text = extract_jsonld_article_text(page)
    parser = ArticleTextParser(final_url)
    try:
        parser.feed(page)
    except Exception:
        pass
    candidates = [meta_description, jsonld_text, *parser.paragraphs]
    return {
        "title": page_title,
        "description": meta_description,
        "sentences": select_fact_sentences(candidates, max_sentences=MAX_ARTICLE_FACTS),
    }


class ArticleTextParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self._capture: str | None = None
        self._parts: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg", "form", "footer", "nav"}:
            self._capture = None
            self._parts = []
            return
        if tag in {"p", "h2", "blockquote"}:
            self._capture = tag
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if self._capture == tag:
            text = clean_text(" ".join(self._parts))
            if is_useful_fact(text):
                self.paragraphs.append(text)
            self._capture = None
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)


def extract_meta_description(page: str) -> str:
    patterns = [
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, page, re.I | re.S)
        if match:
            return clean_description(match.group(1))
    return ""


def extract_page_title(page: str) -> str:
    patterns = [
        (r'<meta[^>]+property=["\']og:title["\'][^>]+content=(["\'])(.*?)\1', 2),
        (r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=(["\'])(.*?)\1', 2),
        (r'<meta[^>]+content=(["\'])(.*?)\1[^>]+property=["\']og:title["\']', 2),
        (r"<title[^>]*>(.*?)</title>", 1),
    ]
    for pattern, group_index in patterns:
        match = re.search(pattern, page, re.I | re.S)
        if not match:
            continue
        title = clean_description(match.group(group_index))
        title = re.sub(r"\s+[-|]\s+[^-|]{2,45}$", "", title).strip()
        if title and not is_rejected_title(title):
            return title
    return ""


def extract_jsonld_article_text(page: str) -> str:
    matches = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page,
        re.I | re.S,
    )
    parts: list[str] = []
    for raw in matches:
        text = html.unescape(raw).strip()
        if not text:
            continue
        try:
            data = json.loads(text)
        except Exception:
            continue
        parts.extend(find_article_text_fields(data))
    return clean_text(" ".join(parts))


def find_article_text_fields(value: Any) -> list[str]:
    results: list[str] = []
    if isinstance(value, dict):
        article_type = value.get("@type")
        if isinstance(article_type, list):
            is_article = any(str(item).lower() in {"newsarticle", "article"} for item in article_type)
        else:
            is_article = str(article_type).lower() in {"newsarticle", "article"}
        if is_article:
            for key in ("description", "articleBody"):
                if value.get(key):
                    results.append(str(value[key]))
        for nested in value.values():
            results.extend(find_article_text_fields(nested))
    elif isinstance(value, list):
        for item in value:
            results.extend(find_article_text_fields(item))
    return results


def build_variants(item: dict[str, Any]) -> dict[str, str]:
    source_title = clean_text(item["title"]).strip()
    facts = article_facts(item)
    title = make_organic_title(source_title, facts, item.get("category", "gundem"), item.get("summary", ""))
    summary = make_spot(title, facts, item.get("summary", ""), item.get("category", "gundem"), source_title=source_title)
    category = category_label(item.get("category", "gundem"))
    neutral = f"{title} konusunda son bilgiler netleşti. {summary}"
    flow = f"{category.capitalize()} başlığında takip edilen gelişmede {summary}"
    spot = summary if summary != title else f"{title} gelişmesine ilişkin ayrıntılar netleşiyor."
    return {
        "title": title,
        "spot": normalize_sentence(spot),
        "neutral": normalize_sentence(neutral),
        "flow": normalize_sentence(flow),
    }


def editorial_profile_for(item: dict[str, Any]) -> str:
    text = clean_text(" ".join([str(item.get("title") or ""), str(item.get("summary") or "")])).casefold()
    if any(word in text for word in ("parti", "meclis", "bakan", "cumhurbaşkanı", "cumhurbaskani", "seçim", "secim", "belediye")):
        return "siyaset-manset"
    if any(word in text for word in ("dava", "mahkeme", "soruşturma", "sorusturma", "gözaltı", "gozalti", "tutuklama")):
        return "hukuk-gundem"
    if any(word in text for word in ("işçi", "isci", "emekli", "kadın", "kadin", "çocuk", "cocuk", "öğrenci", "ogrenci")):
        return "toplum-yasam"
    category = str(item.get("category") or "gundem")
    return {"son-dakika": "son-dakika", "ekonomi": "ekonomi", "dunya": "dis-haber", "teknoloji": "teknoloji", "spor": "spor"}.get(category, "gundem")


def make_organic_title(source_title: str, facts: list[str], category: str = "gundem", fallback: str = "") -> str:
    source_title = clean_text(source_title).strip()
    source_facts = editorial_fact_pack(facts, source_title) or editorial_fact_pack([fallback or source_title], source_title)
    source_based = source_based_headline(source_title, source_facts, category)
    candidates = [
        source_based,
        paraphrase_headline(source_title),
        headline_from_facts(source_title, source_facts, category),
        headline_from_facts(source_title, source_facts[1:], category) if len(source_facts) > 1 else "",
    ]
    for candidate in candidates:
        title = polish_headline(candidate)
        if is_usable_organic_title(title, source_title, allow_close=(candidate == source_based)):
            return finalize_headline(title, source_title, source_facts, category)
    fallback_title = polish_headline(paraphrase_headline(source_title) or source_title)
    if is_usable_organic_title(fallback_title, source_title, allow_close=True):
        return finalize_headline(fallback_title, source_title, source_facts, category)
    contextual_title = polish_headline(contextual_headline(source_title, category, source_facts))
    if is_usable_organic_title(contextual_title, source_title, allow_close=True):
        return finalize_headline(contextual_title, source_title, source_facts, category)
    safe_title = polish_headline(meaning_safe_headline(source_title, source_facts, category))
    if safe_title and title_preserves_meaning(safe_title, source_title) and not is_rejected_title(safe_title):
        return finalize_headline(safe_title, source_title, source_facts, category)
    faithful_title = polish_headline(source_title)
    if faithful_title and title_preserves_meaning(faithful_title, source_title) and not is_rejected_title(faithful_title) and not has_encoding_damage(faithful_title):
        return finalize_headline(faithful_title, source_title, source_facts, category)
    repaired = repair_title_fragment(source_title, source_title)
    if repaired and not is_rejected_title(repaired) and not has_encoding_damage(repaired):
        return polish_headline(repaired)
    return polish_headline(f"{category_label(category).capitalize()} gelişmesi")


def source_based_headline(source_title: str, facts: list[str], category: str) -> str:
    source = clean_source_headline(source_title)
    if not source:
        return ""
    lowered = source.casefold()
    if ":" in source:
        lead, tail = [part.strip(" .,:;") for part in source.split(":", 1)]
        if lead and tail:
            if re.search(r"\bdosyası$", lead.casefold()):
                return f"{lead[:-7].strip()} dosyasında {mid_sentence_tail(tail)}"
            return f"{lead}: {tail}"
    if "!" in source:
        lead, tail = [part.strip(" .,!;") for part in source.split("!", 1)]
        if lead and len(tail) >= 14:
            return f"{lead}: {lower_first(tail)}"
    if source.endswith("?"):
        core = source.rstrip("?").strip()
        if core.casefold().startswith(("9 soruda", "5 soruda", "10 soruda")):
            return f"{core}?"
        if len(core) >= 24:
            return f"{core}?"
    rewritten = light_source_headline_rewrite(source)
    if normalized_title(rewritten) != normalized_title(source):
        return rewritten
    if len(source) >= 28 and headline_has_complete_predicate(source) and not headline_tail_is_incomplete(source):
        return source
    if not headline_has_complete_predicate(source):
        completed = complete_nominal_headline(source)
        if completed:
            return completed
    detail = headline_detail_clause(source, facts)
    if detail and len(source) < 92:
        return f"{source}: {detail}"
    if not headline_has_complete_predicate(source) and len(facts) > 0:
        detail = fact_detail_for_headline(source, facts, category)
        if detail:
            return f"{source}: {detail}"
    if len(source) < 44:
        return contextual_headline(source, category, facts)
    if re.search(r"\b(yalanlama|soruşturma|operasyon|açıklama|uyarı|karar|rapor|analiz|çağrı|ödül|mesaj|tepki)$", lowered):
        return f"{source} gündemde"
    return source


def headline_allowed_max(source_title: str, facts: list[str] | None = None) -> int:
    source = clean_source_headline(source_title)
    lowered = source.casefold()
    long_signals = (
        "soruşturma",
        "iddianame",
        "duruşma",
        "mahkeme",
        "karar",
        "rapor",
        "bakanlık",
        "cumhurbaşkanı",
        "açıklama",
        "deprem",
        "operasyon",
        "tutuklama",
        "gözaltı",
    )
    fact_text = clean_text(" ".join(facts or []))
    if (
        len(source) > HEADLINE_TARGET_MAX_CHARS
        and (
            len(numeric_anchors(source)) >= 2
            or any(mark in source for mark in ("'", '"'))
            or any(signal in lowered for signal in long_signals)
            or len(semantic_anchors(f"{source} {fact_text}")) >= 5
        )
    ):
        return HEADLINE_LONG_MAX_CHARS
    return HEADLINE_TARGET_MAX_CHARS


def remove_headline_filler(value: str) -> str:
    text = clean_text(value).strip(" .,-;")
    replacements = [
        (r"\s+başlığı gündemde$", ""),
        (r"\s+sorusu gündemde$", ""),
        (r"\s+başlığında süreç hareketlendi$", " gündemde"),
        (r"\s+dosyasında dikkat çeken gelişme$", ""),
        (r"\s+yeniden gündemde$", " gündemde"),
        (r"\s+ayrıntıları netleşiyor$", " netleşti"),
        (r"\s+merak edilen başlıklar$", " öne çıktı"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.I)
    text = re.sub(r"\s+başlığında\s+", ": ", text, flags=re.I)
    text = re.sub(r"\s+dosyası dosyasında\b", " dosyasında", text, flags=re.I)
    return clean_text(text).strip(" .,-;")


def concise_headline(title: str, source_title: str, facts: list[str], category: str) -> str:
    original = repair_headline_flow(polish_headline(title))
    if not original:
        return original
    max_chars = headline_allowed_max(source_title, facts)
    if len(original) <= max_chars:
        return original

    candidates: list[str] = []
    filler_free = polish_headline(remove_headline_filler(original))
    candidates.append(filler_free)
    source_based = polish_headline(remove_headline_filler(source_based_headline(source_title, facts, category)))
    candidates.append(source_based)

    if ":" in filler_free:
        lead, tail = [part.strip(" .,:;") for part in filler_free.split(":", 1)]
        remaining = max(40, max_chars - len(lead) - 2)
        compact_tail = compact_headline(tail, max_chars=remaining)
        candidates.append(polish_headline(f"{lead}: {compact_tail}"))

    candidates.append(compact_headline(filler_free or original, max_chars=max_chars))
    candidates.append(compact_headline(original, max_chars=HEADLINE_LONG_MAX_CHARS))

    for candidate in candidates:
        candidate = repair_headline_flow(polish_headline(candidate))
        if not candidate:
            continue
        if len(candidate) > HEADLINE_LONG_MAX_CHARS:
            continue
        if headline_is_incomplete(candidate) or not headline_has_complete_predicate(candidate) or has_encoding_damage(candidate):
            continue
        if source_title and not title_preserves_meaning(candidate, source_title):
            continue
        return candidate

    if len(original) <= HEADLINE_ABSOLUTE_MAX_CHARS and not headline_is_incomplete(original):
        return original
    return compact_headline(original, max_chars=HEADLINE_ABSOLUTE_MAX_CHARS)


def mid_sentence_tail(value: str) -> str:
    text = clean_text(value).strip(" .,:;")
    if not text:
        return text
    first = re.match(r"[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü]+", text)
    if first and ("'" in first.group(0) or first.group(0).isupper()):
        return text
    first_word = first.group(0) if first else ""
    protected = {"ABD", "AB", "BM", "NATO", "İsrail", "İran", "Irak", "Suriye", "Türkiye", "İstanbul", "Ankara", "İzmir"}
    if first_word in protected:
        return text
    if text[0] == "İ":
        return "i" + text[1:]
    return text[0].lower() + text[1:]


def complete_nominal_headline(source: str) -> str:
    text = clean_source_headline(source)
    lowered = text.casefold()
    if re.search(r"\btebrik telefonu\b", lowered):
        return f"{text} geldi"
    if re.search(r"\b(mesajı|çağrısı)\b", lowered):
        return f"{text} paylaşıldı"
    if re.search(r"\b(ziyareti|teması|görüşmesi)\b", lowered):
        return f"{text} gerçekleşti"
    if re.search(r"\b(festival|şenlik|fuar|zirve|etkinlik|kongre|program)\b", lowered):
        return f"{text} başladı"
    if re.search(r"\b(ödül|nişan|plaket)\b", lowered):
        return f"{text} verildi"
    if re.search(r"\b(operasyon|baskın)\b", lowered):
        return f"{text} düzenlendi"
    if re.search(r"\b(soruşturma|dava|karar|izin)\b", lowered):
        return f"{text} gündemde"
    if re.search(r"\b(analiz|dezavantaj|tartışma|kriz|risk|çağrı|uyarı|açıklama|mesaj|tepki|iddia)\b", lowered):
        return f"{text} yeniden gündemde"
    if re.search(r"\b(heyecanı|coşkusu)\b", lowered):
        return f"{text} başladı"
    if len(text) >= 28:
        return f"{text} başlığı gündemde"
    return ""


def clean_source_headline(value: str) -> str:
    text = clean_text(value)
    text = re.sub(r"^son dakika[.!:…-]*\s*", "", text, flags=re.I)
    text = re.sub(r"\s+(Son dakika haberleri|Haberleri|Güncel Haberler)$", "", text, flags=re.I)
    text = re.sub(r"\bİşte\s+", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" .,-;")
    return text


def light_source_headline_rewrite(value: str) -> str:
    text = clean_source_headline(value)
    replacements = [
        (r"\bgörevden alındı\b", "görevinden alındı"),
        (r"\bgözaltına alındı\b", "gözaltı işlemi yapıldı"),
        (r"\btutuklandı\b", "cezaevine gönderildi"),
        (r"\bele geçirildi\b", "yakalandı"),
        (r"\bkatılacak\b", "yer alacak"),
        (r"\bbaşlıyor\b", "başlayacak"),
        (r"\bbekleniyor\b", "uyarısı yapıldı"),
        (r"\baçıklaması\b", "açıklaması gündemde"),
        (r"\banalizi\b", "analizinde yeni değerlendirme"),
    ]
    for pattern, replacement in replacements:
        updated = re.sub(pattern, replacement, text, flags=re.I)
        if normalized_title(updated) != normalized_title(text):
            return updated
    return text


def fact_detail_for_headline(title: str, facts: list[str], category: str) -> str:
    for fact in facts:
        sentence = remove_editorial_artifacts(apply_editorial_paraphrase_replacements(fact))
        for clause in split_rewrite_clauses(sentence):
            clause = clean_text(clause).strip(" .;:")
            if len(clause) < 22 or len(clause) > 82:
                continue
            if fact_is_weak_fragment(clause) or headline_is_incomplete(clause):
                continue
            if title_preserves_meaning(clause, title) or len(surface_anchor_terms(clause)) >= 2 or numeric_anchors(clause):
                return lower_first(clause)
    fallback = category_label(category)
    return f"{fallback} başlığında ayrıntılar netleşiyor"


def paraphrase_headline(source_title: str) -> str:
    text = clean_text(source_title)
    if not text:
        return ""
    text = re.sub(r"^son dakika[.!:…-]*\s*", "", text, flags=re.I)
    text = re.sub(r"\bİşte\s+", "", text, flags=re.I)
    text = re.sub(r"\bflaş\b", "dikkat çeken", text, flags=re.I)
    patterns = [
        (
            r"^Bu sözler\s+(.+?)'?[ae]\s+mı\?\s+(.+?)'dan\s+'([^']{3,90})'\s+mesajı$",
            r"\2'dan '\3' çıkışı",
        ),
        (r"^(.+?)\s+hakkında\s+tahliye\s+kararı$", r"\1 için tahliye kararı çıktı"),
        (r"^(.+?)\s+hakkında\s+yakalama\s+kararı\s+çıkarıldı$", r"\1 için yakalama kararı"),
        (r"^(.+?)\s+sona\s+erdi:\s+(.+?)\s+sınava\s+katıldı$", r"\1 tamamlandı: \2 sınavdaydı"),
        (r"^(.+?):\s*Cezalar\s+(.+?)\s+çıkabilir$", r"\1 dosyasında \2 varan ceza gündemde"),
        (r"^(.+?)\s+görevden\s+alındı$", r"\1 için görev değişimi"),
        (r"^(.+?)\s+satışında\s+skandal\s+iddia:\s+(.+)$", r"\1 satışında tartışma: \2"),
        (r"^Demir yollarında\s+(.+?)\s+ücretsiz hizmet$", r"Demir yollarında \1 ücretsiz ulaşım"),
        (r"^Annelik:\s*Deneyim mi,\s*performans mı\??$", "İdeal annelik baskısı yeniden tartışılıyor"),
        (r"^(.+?)'de mis kokulu festival$", r"\1'de çiçek festivali başladı"),
        (r"^İstanbul barajlarında son durum$", "İstanbul barajlarında doluluk oranı yükseldi"),
        (r"^Kılıçdaroğlu'na linç girişiminde bulunan kişi,\s*7 yıl sonra özür dileyip helallik istedi$", "Kılıçdaroğlu saldırısı dosyasında 7 yıl sonra özür"),
        (r"^Kusursuz aklama!\s*63 kişinin öldüğü Tutar Yapı Sitesi dosyasında kamu görevlilerine 'kusursuz' raporu$", "63 kişinin öldüğü Tutar Yapı Sitesi dosyasında 'kusursuz' raporu"),
        (r"^Kusursuz aklama!\s*63 kişinin öldüğü Tutar Yapı Sitesi.*$", "63 kişinin öldüğü Tutar Yapı Sitesi dosyasında rapor tartışması"),
        (r"^Türkiye gündemini sarsan bu linç girişimine karışan isimlerden\s+(.+)$", r"Kılıçdaroğlu saldırısı dosyasında \1 detayı"),
    ]
    for pattern, replacement in patterns:
        updated = re.sub(pattern, replacement, text, flags=re.I)
        if updated != text:
            text = updated
            break
    replacements = [
        (r"\bsona erdi\b", "tamamlandı"),
        (r"\bbaşladı\b", "açıldı"),
        (r"\bkatıldı\b", "yer aldı"),
        (r"\bgörevden alındı\b", "görevinden alındı"),
        (r"\byeni kare\b", "son görüntü"),
        (r"\bson durumunu paylaştı\b", "son durumunu aktardı"),
        (r"\bkarıştı\b", "hareketlendi"),
        (r"\bsert yanıt\b", "dikkat çeken yanıt"),
        (r"\bçağrısı\b", "mesajı"),
        (r"\bçıkışı\b", "mesajı"),
        (r"\bidamlarının\b", "idam edilişlerinin"),
        (r"\bfırsatı\b", "imkanı"),
        (r"\bücretsiz hizmet\b", "ücretsiz ulaşım"),
        (r"\bdestek\b", "kaynak"),
        (r"\brekor seviyeye yaklaştı\b", "rekor sınırına dayandı"),
        (r"\baçıklama\b", "duyuru"),
        (r"\bduyurdu\b", "açıkladı"),
        (r"\bgözaltına alındı\b", "gözaltı işlemi yapıldı"),
        (r"\btutuklandı\b", "cezaevine gönderildi"),
        (r"\byaralandı\b", "yaralı olarak kayda geçti"),
        (r"\bhayatını kaybetti\b", "yaşamını yitirdi"),
        (r"\bmahsur\b", "kapalı bölgede kaldı"),
        (r"\btepki\b", "açıklama"),
        (r"\bskandal iddia\b", "tartışmalı iddia"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.I)
    text = re.sub(r"\bdosyası\s+dosyasında\b", "dosyasında", text, flags=re.I)
    return text


def headline_from_facts(source_title: str, facts: list[str], category: str) -> str:
    if not facts:
        return ""
    lead = choose_lead_fact(source_title, facts)
    if not lead:
        return ""
    sentence = organic_rewrite_sentence(lead, source_title, category, index=0)
    sentence = remove_editorial_artifacts(sentence)
    sentence = re.sub(r"^(paylaşılan|yapılan)\s+açıklamada\s+", "", sentence, flags=re.I)
    sentence = re.sub(r"^aktarılan\s+bilgilere\s+göre\s+", "", sentence, flags=re.I)
    sentence = re.sub(r"\s+başlığıyla\s+ilgili\s+yeni\s+bilgiler\s+paylaşıldı\.?$", "", sentence, flags=re.I)
    clauses = split_rewrite_clauses(sentence)
    if len(clauses) >= 2:
        useful = [
            clause
            for clause in clauses
            if headline_clause_has_news_value(clause) and title_preserves_meaning(clause, source_title)
        ]
        if useful:
            sentence = max(useful[:3], key=lambda part: (headline_has_complete_predicate(part), has_news_verb(part), min(len(part), 112)))
    return sentence


def contextual_headline(source_title: str, category: str, facts: list[str]) -> str:
    core = paraphrase_headline(source_title)
    core = re.sub(r"[:;].*$", "", core).strip(" ,;:")
    core = compact_headline(core, max_chars=58)
    if not core:
        detail = compact_headline(headline_from_facts(source_title, facts, category), max_chars=58)
        core = detail or category_label(category)
    templates = [f"{core} dosyasında dikkat çeken gelişme", f"{core} başlığında süreç hareketlendi"]
    return next((item for item in templates if item), core)


def meaning_safe_headline(source_title: str, facts: list[str], category: str) -> str:
    source = clean_text(source_title)
    if not source:
        return ""
    if ":" in source:
        lead, tail = source.split(":", 1)
        terms = surface_anchor_terms(tail)
        if terms:
            joined = ", ".join(terms[:3])
            if "cemaat" in source.casefold() or "akreditasyon" in " ".join(facts).casefold():
                return f"AFAD akreditasyonunda {joined} tartışması"
            lead_core = compact_headline(paraphrase_headline(lead), max_chars=66)
            return f"{lead_core}: {joined}"
    for fact in facts:
        candidate = compact_headline(apply_editorial_paraphrase_replacements(fact), max_chars=104)
        if candidate and title_preserves_meaning(candidate, source):
            return candidate
    return source


def finalize_headline(title: str, source_title: str, facts: list[str], category: str) -> str:
    headline = repair_headline_flow(polish_headline(title))
    if (
        headline_is_incomplete(headline)
        or not headline_has_complete_predicate(headline)
        or has_encoding_damage(headline)
        or (source_title and not title_preserves_meaning(headline, source_title))
    ):
        safer = meaning_safe_headline(source_title, facts, category)
        headline = repair_headline_flow(polish_headline(safer or source_based_headline(source_title, facts, category) or source_title))
    if len(headline) < 48:
        expanded = expand_short_headline(headline, source_title, facts)
        if expanded and title_preserves_meaning(expanded, source_title):
            headline = expanded
    if headline_is_incomplete(headline) or not headline_has_complete_predicate(headline) or has_encoding_damage(headline):
        headline = repair_headline_flow(polish_headline(source_based_headline(source_title, facts, category) or source_title))
    source_candidate = repair_headline_flow(polish_headline(source_based_headline(source_title, facts, category) or source_title))
    if (
        source_candidate
        and len(headline) < 48
        and len(source_candidate) > len(headline) + 12
        and not headline_is_incomplete(source_candidate)
        and headline_has_complete_predicate(source_candidate)
        and not has_encoding_damage(source_candidate)
        and title_preserves_meaning(source_candidate, source_title)
    ):
        headline = source_candidate
    if headline_is_incomplete(headline):
        headline = repair_headline_flow(polish_headline(contextual_headline(source_title, category, facts)))
    concise = concise_headline(headline, source_title, facts, category)
    if (
        concise
        and not headline_is_incomplete(concise)
        and headline_has_complete_predicate(concise)
        and not has_encoding_damage(concise)
        and (not source_title or title_preserves_meaning(concise, source_title))
    ):
        headline = concise
    return headline


def expand_short_headline(title: str, source_title: str, facts: list[str]) -> str:
    detail = headline_detail_clause(title, facts)
    if not detail:
        return title
    candidate = polish_headline(f"{title}: {detail}")
    if 58 <= len(candidate) <= 138 and not headline_is_incomplete(candidate):
        return candidate
    return title


def headline_detail_clause(title: str, facts: list[str]) -> str:
    title_key = normalized_title(title)
    for fact in facts:
        sentence = remove_editorial_artifacts(apply_editorial_paraphrase_replacements(fact))
        for clause in split_rewrite_clauses(sentence):
            clause = clean_text(clause).strip(" .;:")
            if len(clause) < 24 or len(clause) > 86:
                continue
            if normalized_title(clause) in title_key or title_overlap_ratio(title, clause) > 0.58:
                continue
            if (
                fact_is_weak_fragment(clause)
                or headline_is_incomplete(clause)
                or not headline_has_complete_predicate(clause)
                or not headline_detail_has_value(clause)
            ):
                continue
            return lower_first(clause).rstrip(".")
    return ""


def headline_clause_has_news_value(value: str) -> bool:
    text = clean_text(value).strip(" .;:")
    return bool(text) and not fact_is_weak_fragment(text) and not headline_is_incomplete(text) and headline_has_complete_predicate(text)


def repair_headline_flow(title: str) -> str:
    text = clean_text(title).strip(" .,-;")
    text = re.sub(r"^Türkiye gündeminde\s+", "", text, flags=re.I)
    text = re.sub(r"^Son dakika akışında\s+", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    if text:
        text = uppercase_turkish_start(text)
    return text


def ends_with_abbreviation_fragment(value: str) -> bool:
    text = clean_text(value).strip()
    return bool(re.search(r"\b(?:Prof|Doç|Dr|Arş|Gör|Av|Op|Uzm|Yrd|No)\.$", text))


def headline_tail_is_incomplete(value: str) -> bool:
    text = clean_text(value).strip(" .")
    if not text:
        return True
    lowered = text.casefold()
    if ends_with_abbreviation_fragment(text):
        return True
    if re.search(
        r"\b(ve|ile|için|üzere|sonra|önce|geriye|karşı|tarafından|kapsamında|nedeniyle|dair|ilişkin|olarak|bulunan|edilen|verilen|yönelik|ise|iken|kadar|dek|değin|bugüne|bugüne kadar|doğruysa|değilse)$",
        lowered,
    ):
        return True
    if re.search(r"(dığını|diğini|duğunu|düğünü|acağını|eceğini|tığını|tiğini|tuğunu|tüğünü|ysa|yse)$", lowered):
        return True
    if re.search(r"\b(aktaran|belirten|söyleyen|kaydeden|duyuran|paylaşan|açıklayan)\s+[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü'’.-]{2,}$", text):
        return True
    if re.search(r"\b(üzerinden|ardından|sonrasında|öncesinde|karşısında|hakkında|arasında)\s+[a-zçğıöşü0-9'’.-]{2,28}$", lowered):
        return True
    return False


def headline_is_incomplete(title: str) -> bool:
    text = clean_text(title).strip(" .")
    if not text:
        return True
    lowered = text.casefold()
    if len(text) < 18:
        return True
    if ":" in text:
        tail = text.split(":", 1)[1].strip()
        if headline_tail_is_incomplete(tail):
            return True
    if re.search(
        r"\b(ve|ile|için|üzere|sonra|önce|geriye|karşı|tarafından|kapsamında|nedeniyle|dair|ilişkin|olarak|bulunan|edilen|verilen|yönelik|ise|iken|kadar|dek|değin|bugüne|bugüne kadar|doğruysa|değilse)$",
        lowered,
    ):
        return True
    if re.search(r"(dığını|diğini|duğunu|düğünü|acağını|eceğini|tığını|tiğini|tuğunu|tüğünü|ysa|yse)$", lowered):
        return True
    if re.search(
        r"\b(bulunduğu|olduğu|edildiği|yapıldığı|açıldığı|verildiği|kaldığı|yaşandığı|düzenlendiği|başladığı)\s+[a-zçğıöşü0-9'’.-]{2,32}$",
        lowered,
    ):
        return True
    if re.search(
        r"\b(aktaran|belirten|söyleyen|kaydeden|duyuran|paylaşan|açıklayan)\s+[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü'’.-]{2,}$",
        text,
    ):
        return True
    if re.search(r"\b(arasında|üzerinden|ardından|sonrasında|öncesinde|karşısında|hakkında)\s+[a-zçğıöşü0-9'’.-]{2,28}$", lowered):
        return True
    return False


def headline_has_complete_predicate(value: str) -> bool:
    text = clean_text(value).strip(" .;:")
    if not text:
        return False
    lowered = text.casefold()
    if ":" in text:
        lead, tail = [part.strip(" .;:") for part in text.split(":", 1)]
        if len(tail) >= 12 and not headline_tail_is_incomplete(tail) and (
            has_news_verb(tail)
            or re.search(r"\b(gündemde|masada|yolda|hazır|tamam|net|belli|açıklandı|başladı|sona erdi|devam ediyor)\b", tail.casefold())
            or (numeric_anchors(tail) and re.search(r"\b(artış|düşüş|zam|indirim|rekor|alarm|uyarı|karar|rapor|tartışma|kriz|dava|operasyon|gözaltı|tutuklama)\b", tail.casefold()))
        ):
            return True
        if lead and has_news_verb(lead) and not headline_tail_is_incomplete(tail):
            return True
    if "?" in text or "!" in text:
        return True
    if has_news_verb(text):
        return True
    if numeric_anchors(text) and re.search(r"\b(artış|düşüş|zam|indirim|rekor|alarm|uyarı|karar|rapor|tartışma|kriz|dava|operasyon|gözaltı|tutuklama)\b", lowered):
        return True
    if re.search(r"\b(gündemde|masada|yolda|hazır|tamam|net|belli|açıklandı|başladı|sona erdi|devam ediyor)\b", lowered):
        return True
    if re.search(r"\b\w+(dı|di|du|dü|tı|ti|tu|tü|dik|dık|duk|dük|tik|tık|tuk|tük|acak|ecek|ıyor|iyor|uyor|üyor|ar|er|mış|miş|muş|müş|landı|lendi|undu|ündü|ildi|ıldı)\b", lowered):
        return True
    if re.search(
        r"\b(yalanlama|soruşturma|operasyon|heyecanı|övgü|nişanı|açıklaması|analizi|ödülü|çağrısı|müebbet|emanet|tartışması|krizi|kararı|izni|uyarısı|mesajı|raporu|tepkisi)$",
        lowered,
    ):
        return True
    words = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü0-9'’.-]+", text)
    if len(words) <= 7 and len(surface_anchor_terms(text)) >= 2:
        return False
    return False


def headline_detail_has_value(value: str) -> bool:
    text = clean_text(value)
    if numeric_anchors(text):
        return True
    if re.search(r"\b(açıkladı|duyurdu|başladı|tamamlandı|yükseldi|düştü|çıktı|geldi|yaşandı|belirlendi|ele geçirildi|gözaltı|tutuklandı|ulaştı|imzalandı|yayımlandı|kararlaştırıldı)\b", text, re.I):
        return True
    return len(surface_anchor_terms(text)) >= 2


def surface_anchor_terms(value: str) -> list[str]:
    text = clean_text(value)
    terms: list[str] = []
    seen: set[str] = set()
    for phrase in re.findall(r"['\"]([^'\"]{3,60})['\"]", text):
        key = normalized_anchor(phrase)
        if key and key not in seen:
            seen.add(key)
            terms.append(phrase.strip())
    token_pattern = r"\b[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü.-]*(?:'[a-zçğıöşü]+)?\b"
    for token in re.findall(token_pattern, text):
        cleaned = token.strip(".,;: ")
        key = normalized_anchor(cleaned)
        if len(key) >= 3 and key not in seen and key not in {"gündem", "haberleri"}:
            seen.add(key)
            terms.append(cleaned)
        if len(terms) >= 5:
            break
    return terms


def is_usable_organic_title(title: str, source_title: str, *, allow_close: bool = False) -> bool:
    if not title or len(title) < 18:
        return False
    if is_rejected_title(title) or has_encoding_damage(title):
        return False
    if is_bad_headline_fragment(title):
        return False
    if not headline_has_complete_predicate(title):
        return False
    if re.search(r"\b(başlığında yeni|haber robotu|yeniden derlenerek|gelişmeye ilişkin bilgiler farklı kaynaklardan)\b", title, flags=re.I):
        return False
    if re.search(r"\b(başlığı gündemde|sorusu gündemde|dosyasında dikkat çeken gelişme)\b", title, flags=re.I):
        return False
    if re.search(r"^(kamuoyunda yer alan haberlere göre|kamuoyunda yer alan haberlere gore|kulislerde yer alan iddialara göre|kulislerde yer alan iddialara gore)\b", title, flags=re.I):
        return False
    if re.search(r"\b(yeni ayrıntılar netleşti|dosyasında yeni gelişme)$", title, flags=re.I):
        return False
    if not title_preserves_meaning(title, source_title):
        return False
    if not allow_close and headline_too_close(title, source_title):
        return False
    return True


def is_bad_headline_fragment(title: str) -> bool:
    text = clean_text(title).strip(" .")
    lowered = text.casefold()
    words = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü0-9'’.-]+", text)
    if len(words) > 18 and ":" not in text:
        return True
    if headline_is_incomplete(text):
        return True
    if re.search(
        r"(?:\b(?:aktaran|belirten|kaydeden|söyleyen|diyen|olduğunu|edildiğini|yaptığını|anlamına|kapsamında|nedeniyle)|dığını|diğini|duğunu|düğünü|tığını|tiğini|tuğunu|tüğünü|acağını|eceğini)$",
        lowered,
    ):
        return True
    if re.search(r"\b(aktaran|belirten|kaydeden)\s+[A-ZÇĞİÖŞÜ][a-zçğıöşü]+$", text):
        return True
    if re.search(r"\b(keşfettim|düşünüyorum|olmalıyız|bence|kanaatimce)\b", lowered):
        return True
    if len(words) >= 11 and not has_news_verb(text) and ":" not in text and "?" not in text:
        return True
    if not headline_has_complete_predicate(text):
        return True
    return False


def headline_too_close(candidate: str, source_title: str) -> bool:
    candidate_text = clean_text(candidate)
    source_text = clean_text(source_title)
    if not candidate_text or not source_text:
        return False
    if normalized_title(candidate_text) == normalized_title(source_text):
        return True
    ratio = SequenceMatcher(None, candidate_text.casefold(), source_text.casefold()).ratio()
    words_first = headline_word_set(candidate_text)
    words_second = headline_word_set(source_text)
    overlap = len(words_first & words_second) / max(1, min(len(words_first), len(words_second)))
    return ratio >= 0.92 or (overlap >= 0.9 and abs(len(candidate_text) - len(source_text)) <= 14)


def headline_word_set(value: str) -> set[str]:
    stop_words = {"son", "dakika", "haber", "yeni", "ilgili", "için", "ile", "olan", "oldu", "başlığı"}
    return {
        word
        for word in re.findall(r"[a-zçğıöşü0-9']{3,}", clean_text(value).casefold())
        if word not in stop_words
    }


def title_preserves_meaning(candidate: str, source_title: str) -> bool:
    source = clean_text(source_title)
    if not source:
        return True
    candidate_key = normalized_title(candidate)
    if not candidate_key:
        return False
    numeric = numeric_anchors(source)
    if numeric and not any(anchor in candidate_key for anchor in numeric):
        return False
    anchors = semantic_anchors(source)
    if not anchors:
        return True
    present = sum(1 for anchor in anchors if anchor in candidate_key)
    if len(anchors) <= 2:
        return present >= 1
    return present >= min(3, max(2, len(anchors) // 3))


def text_preserves_meaning(candidate: str, source_title: str, facts: list[str] | None = None) -> bool:
    source = clean_text(source_title)
    if not source:
        return True
    candidate_key = normalized_title(candidate)
    if not candidate_key:
        return False
    numeric = numeric_anchors(source)
    if numeric and not any(anchor in candidate_key for anchor in numeric):
        return False
    anchors = semantic_anchors(source)
    if not anchors:
        fact_anchors: set[str] = set()
        for fact in facts or []:
            fact_anchors.update(list(semantic_anchors(fact))[:4])
        anchors = fact_anchors
    if not anchors:
        return True
    present = sum(1 for anchor in anchors if anchor in candidate_key)
    if len(anchors) <= 2:
        return present >= 1
    return present >= min(4, max(2, len(anchors) // 3))


def semantic_anchors(value: str) -> set[str]:
    text = clean_text(value)
    anchors: set[str] = set()
    stop_words = {
        "son",
        "dakika",
        "haber",
        "gündem",
        "gundem",
        "yeni",
        "eski",
        "ilk",
        "sonra",
        "gün",
        "günler",
        "işte",
        "iddia",
        "iddiası",
        "açıklama",
        "mesaj",
        "mesajı",
        "detay",
        "ayrıntı",
        "dosya",
        "dosyası",
        "başlık",
        "temkinli",
        "şekilde",
        "olarak",
        "yoksa",
        "kötümser",
        "dürtüsel",
        "iyimser",
        "olmalıyız",
    }
    anchors.update(numeric_anchors(text))
    for phrase in re.findall(r"['\"]([^'\"]{3,80})['\"]", text):
        phrase_key = normalized_title(phrase)
        if len(phrase_key) >= 8:
            anchors.add(phrase_key)
    for token in re.findall(r"\b[A-ZÇĞİÖŞÜ]{2,}(?:'[a-zçğıöşü]+)?\b", text):
        key = normalized_anchor(token)
        if key and key not in stop_words:
            anchors.add(key)
    proper_pattern = r"\b[A-ZÇĞİÖŞÜ][a-zçğıöşü]+(?:'[a-zçğıöşü]+)?\b"
    proper_tokens = re.findall(proper_pattern, text)
    for token in proper_tokens:
        key = normalized_anchor(token)
        if len(key) >= 3 and key not in stop_words:
            anchors.add(key)
    for match in re.finditer(rf"(?:{proper_pattern})(?:\s+(?:{proper_pattern})){1,3}", text):
        key = normalized_title(match.group(0))
        if len(key) >= 8:
            anchors.add(key)
    if not anchors:
        for word in re.findall(r"[a-zçğıöşü0-9']{5,}", text.casefold()):
            key = normalized_anchor(word)
            if key and key not in stop_words:
                anchors.add(key)
            if len(anchors) >= 4:
                break
    return anchors


def numeric_anchors(value: str) -> set[str]:
    return {
        normalized_title(match.group(0))
        for match in re.finditer(r"\b\d+(?:[.,]\d+)?\b", clean_text(value))
        if normalized_title(match.group(0))
    }


def normalized_anchor(value: str) -> str:
    text = clean_text(value)
    text = re.sub(r"'[a-zçğıöşü]+$", "", text, flags=re.I)
    return normalized_title(text)


def polish_headline(value: str) -> str:
    title = clean_text(value)
    title = remove_editorial_artifacts(title)
    title = re.sub(r"\s+([:!?])", r"\1", title)
    title = re.sub(r"\.{2,}", "...", title)
    title = title.strip(" .,-;")
    title = compact_headline(title, max_chars=HEADLINE_ABSOLUTE_MAX_CHARS)
    if title:
        title = uppercase_turkish_start(title)
    return title


def compact_headline(value: str, *, max_chars: int = 96) -> str:
    title = clean_text(value).strip(" .,-;")
    if len(title) <= max_chars:
        return title
    clauses = [part.strip(" ,;:") for part in re.split(r"\s*[,;]\s+|\s+-\s+", title) if part.strip(" ,;:")]
    for clause in clauses:
        if 36 <= len(clause) <= max_chars and not headline_is_incomplete(clause) and headline_has_complete_predicate(clause):
            return clause
    compact = title[:max_chars].rsplit(" ", 1)[0].strip(" ,;:")
    if headline_is_incomplete(compact):
        compact = re.sub(
            r"\s+\S{1,16}\s*$",
            "",
            compact,
        ).strip(" ,;:")
    return compact


def has_news_verb(value: str) -> bool:
    return bool(
        re.search(
            r"\b(açıkladı|duyurdu|paylaştı|belirlendi|netleşti|başladı|tamamlandı|tamamladı|görüştü|yükseldi|düştü|çıktı|geldi|yaşandı|gündemde|masada|istedi|diledi|hazırlandı|düzenlendi|yapıldı|yaptı|başvurdu|uygulandı|uzaklaştırıldı|açıldı|açtı|kapatıldı|ertelendi|sunuldu|verildi|aldı|ulaştı|vurguladı|aktardı|bildirdi|söyledi|dile getirdi|dinledi|inceledi|yürüttü|değerlendirdi|sürdü|sürdürdü|güncellenecek|yayımlandı|yayımladı|belirtildi|kayda geçti|öne çıktı)\b",
            clean_text(value),
            flags=re.I,
        )
    )


def article_quality_metrics(item: dict[str, Any], title: str, summary: str, body: list[str]) -> dict[str, Any]:
    body_text = clean_text(" ".join(body))
    word_count = len(re.findall(r"\w+", body_text))
    source_facts = article_facts(item)
    fact_count = len(source_facts)
    source_count = int(item.get("source_count") or 1)
    copy_flags = source_copy_flags([summary, *body], source_facts)
    score = 0
    score += min(28, max(0, len(body_text) - 320) // 24)
    score += min(24, len(body) * 6)
    score += min(20, fact_count * 3)
    score += min(12, max(0, source_count - 1) * 4)
    if len(summary) >= 90:
        score += 8
    if is_generic_spot(summary):
        score -= 25
    if not has_encoding_damage(" ".join([title, summary, body_text])):
        score += 8
    if is_robotic_note(body_text):
        score -= 30
    if is_rejected_title(title):
        score -= 50
    source_title = clean_text(item.get("source_title") or item.get("title") or "")
    title_meaning_ok = title_preserves_meaning(title, source_title) if source_title else True
    article_meaning_ok = text_preserves_meaning(" ".join([title, summary, body_text]), source_title, source_facts) if source_title else True
    summary_complete_ok = sentence_is_complete(summary)
    body_complete_ok = body_has_complete_sentences(body)
    story_meaning_ok = story_preserves_required_meaning(title, summary, body, source_title, source_facts) if source_title else True
    if source_title and not headline_too_close(title, source_title):
        score += 6
    elif source_title:
        score -= 10
    if title_meaning_ok:
        score += 8
    else:
        score -= 35
    if article_meaning_ok:
        score += 8
    else:
        score -= 35
    if summary_complete_ok:
        score += 6
    else:
        score -= 25
    if body_complete_ok:
        score += 8
    else:
        score -= 30
    if story_meaning_ok:
        score += 6
    else:
        score -= 35
    if copy_flags:
        score -= min(36, copy_flags * 12)
    score = max(0, min(100, score))
    return {
        "quality_score": score,
        "word_count": word_count,
        "fact_count": fact_count,
        "source_count": source_count,
        "editorial_profile": editorial_profile_for(item),
        "source_copy_flags": copy_flags,
        "title_meaning_ok": str(bool(title_meaning_ok)).lower(),
        "article_meaning_ok": str(bool(article_meaning_ok)).lower(),
        "summary_complete_ok": str(bool(summary_complete_ok)).lower(),
        "body_complete_ok": str(bool(body_complete_ok)).lower(),
        "story_meaning_ok": str(bool(story_meaning_ok)).lower(),
        "editorial_policy": ORIGINALITY_POLICY,
    }


def item_to_article(item: dict[str, Any], status: str = "draft", *, min_publish_score: int = DEFAULT_MIN_PUBLISH_SCORE) -> dict[str, Any]:
    facts = article_facts(item)
    source_title = clean_text(item.get("source_title") or item["title"])
    category = item.get("category", "gundem")
    title = make_organic_title(source_title, facts, category, item.get("summary", ""))
    title = repair_title_fragment(title, source_title)
    summary = normalize_sentence(make_spot(title, facts, item.get("summary", ""), category, source_title=source_title))
    summary = enforce_source_distinction([summary], facts, source_title, category)[0]
    body = compose_news_body(item, facts, display_title=title, source_title=source_title)
    quality_item = dict(item)
    quality_item["source_title"] = source_title
    quality = article_quality_metrics(quality_item, title, summary, body)
    requested_status = status if status in {"draft", "published"} else "draft"
    article_status = requested_status
    if requested_status == "published" and not is_publishable_article(
        title,
        summary,
        body,
        min_quality_score=min_publish_score,
        quality_score=quality["quality_score"],
        source_title=source_title,
        facts=facts,
    ):
        article_status = "draft"
    feed_image = clean_text(str(item.get("image_url") or ""))
    article = {
        "slug": slugify(title),
        "category": item.get("category") or "gundem",
        "title": title,
        "summary": summary,
        "body": body,
        "author": NEWSROOM_AUTHOR,
        "published_at": item.get("published_at") or now_iso(),
        "modified_at": now_iso(),
        "image": feed_image or default_image_for_category(item.get("category", "gundem")),
        "image_alt": title,
        "image_provider": "feed-image" if feed_image else "category-default",
        "image_source_url": feed_image,
        "tags": [tag for tag in [item.get("source", ""), item.get("category", ""), source_tag(item.get("source", ""))] if tag],
        "status": article_status,
        "source_name": item.get("source", ""),
        "source_url": item.get("link", ""),
        "source_title": source_title,
        "source_feed": item.get("source_url", ""),
        "source_published_at": item.get("published_at", ""),
        "automation_signature": item.get("signature", signature_for(item)),
        "imported_at": now_iso(),
        "news_score": str(item.get("news_score", "")),
        "related_sources": item.get("related_sources", []),
        "publish_decision": article_status if article_status == "published" else "draft-quality-gate",
    }
    article.update(quality)
    return article


def unique_article_slug(base_slug: str, articles: list[dict[str, Any]], current_index: int) -> str:
    existing = {str(article.get("slug") or "") for index, article in enumerate(articles) if index != current_index}
    slug = slugify(base_slug) or f"haber-{int(time.time())}"
    if slug not in existing:
        return slug
    for counter in range(2, 200):
        candidate = f"{slug}-{counter}"
        if candidate not in existing:
            return candidate
    return f"{slug}-{int(time.time())}"


def repair_draft_articles_from_sources(
    *,
    site_id: str = "turkiye-gundemi",
    limit: int = 60,
    publish_site: bool = True,
    min_publish_score: int = DEFAULT_MIN_PUBLISH_SCORE,
) -> dict[str, Any]:
    articles = load_articles(site_id)
    repaired: list[dict[str, Any]] = []
    kept_draft: list[dict[str, Any]] = []
    checked = 0

    for index, article in enumerate(articles):
        if checked >= limit:
            break
        if article.get("status") != "draft":
            continue
        flags = publication_blocking_flags(article)
        if not flags and "title_fragment" not in str(article.get("quality_flags") or ""):
            continue
        source_url = str(article.get("source_url") or "").strip()
        if not source_url:
            kept_draft.append({"slug": article.get("slug"), "reason": "source_url yok"})
            continue

        checked += 1
        details = fetch_article_details(source_url)
        source_title = clean_text(details.get("title") or article.get("source_title") or article.get("title") or "")
        source_summary = clean_text(details.get("description") or article.get("summary") or source_title)
        item = {
            "source": article.get("source_name") or "Kaynak",
            "source_url": article.get("source_feed") or "",
            "link": source_url,
            "title": source_title,
            "source_title": source_title,
            "summary": source_summary,
            "category": article.get("category") or "gundem",
            "published_at": article.get("source_published_at") or article.get("published_at") or now_iso(),
            "published_sort": datetime.now(timezone.utc),
            "details": details,
            "source_priority": 88 if article.get("category") in {"gundem", "son-dakika", "ekonomi"} else 70,
            "source_count": article.get("source_count") or 1,
            "related_sources": article.get("related_sources") or [],
        }
        rebuilt = item_to_article(item, status="published", min_publish_score=min_publish_score)
        repaired_title = repair_title_fragment(str(rebuilt.get("title") or ""), source_title)
        if repaired_title != rebuilt.get("title"):
            facts = article_facts(item)
            rebuilt["title"] = repaired_title
            rebuilt["slug"] = slugify(repaired_title)
            rebuilt["summary"] = normalize_sentence(make_spot(repaired_title, facts, source_summary, item["category"], source_title=source_title))
            rebuilt["summary"] = enforce_source_distinction([rebuilt["summary"]], facts, source_title, item["category"])[0]
            rebuilt["body"] = compose_news_body(item, facts, display_title=repaired_title, source_title=source_title)
            quality_item = dict(item)
            quality_item["source_title"] = source_title
            rebuilt.update(article_quality_metrics(quality_item, repaired_title, rebuilt["summary"], rebuilt["body"]))

        old_image = str(article.get("image") or "")
        if old_image and "/assets/images/news/" in old_image:
            rebuilt["image"] = old_image
        rebuilt["slug"] = unique_article_slug(str(rebuilt.get("slug") or rebuilt.get("title") or article.get("slug")), articles, index)
        rebuilt["repair_source_slug"] = article.get("slug", "")
        rebuilt["modified_at"] = now_iso()

        if rebuilt.get("status") == "published" and is_publication_safe(rebuilt):
            rebuilt["publish_decision"] = "repaired-from-source"
            articles[index] = rebuilt
            repaired.append({"old_slug": article.get("slug"), "slug": rebuilt.get("slug"), "title": rebuilt.get("title")})
        else:
            rebuilt["status"] = "draft"
            rebuilt["publish_decision"] = "draft-repair-needs-editor"
            rebuilt["quality_flags"] = ", ".join(article_quality_flags(rebuilt))
            articles[index] = rebuilt
            kept_draft.append({"slug": rebuilt.get("slug"), "reason": rebuilt.get("quality_flags", "kalite kontrolü")})

    if repaired or kept_draft:
        save_articles(site_id, articles)

    public_dir = ""
    if publish_site and repaired:
        public_dir = str(generate_site(site_id))

    return {
        "ok": True,
        "checked": checked,
        "repaired_count": len(repaired),
        "kept_draft_count": len(kept_draft),
        "repaired": repaired,
        "kept_draft": kept_draft[:80],
        "public_dir": public_dir,
    }


def import_news(
    *,
    site_id: str = "turkiye-gundemi",
    limit: int | None = None,
    max_items: int | None = None,
    status: str | None = None,
    publish_site: bool | None = None,
    enrich_images: bool | None = None,
) -> dict[str, Any]:
    defaults = load_runtime_defaults()
    resolved_limit = clamp_int(limit if limit is not None else defaults["limit"], defaults["limit"], 1, MAX_FETCH_LIMIT)
    resolved_max_items = clamp_int(
        max_items if max_items is not None else defaults["max_import_per_cycle"],
        defaults["max_import_per_cycle"],
        1,
        MAX_IMPORT_PER_CYCLE,
    )
    resolved_status = str(status or defaults["status"]).strip()
    if resolved_status not in {"draft", "published"}:
        resolved_status = defaults["status"]
    resolved_publish_site = defaults["publish_site_after_import"] if publish_site is None else bool(publish_site)
    resolved_enrich_images = defaults["image_enrichment"] if enrich_images is None else bool(enrich_images)
    state = load_state()
    payload = fetch_latest_news(limit=resolved_limit, state=state)
    state = normalize_state(payload.pop("state", state))
    known = set(state.get("imported_signatures", []))
    existing = load_articles(site_id)
    known.update(str(item.get("automation_signature", "")) for item in existing if item.get("automation_signature"))
    known.update(str(item.get("source_url", "")) for item in existing if item.get("source_url"))
    known.update(canonical_url(str(item.get("source_url", ""))) for item in existing if item.get("source_url"))

    imported = []
    skipped = []
    for item in payload["items"]:
        if len(imported) >= resolved_max_items:
            break
        sig = item.get("signature", "")
        link = str(item.get("link") or "")
        link_key = canonical_url(link)
        if sig in known or link in known or link_key in known:
            skipped.append({"title": item["title"], "reason": "zaten var"})
            continue
        article = upsert_article(site_id, item_to_article(item, status=resolved_status, min_publish_score=defaults["min_publish_score"]))
        if resolved_enrich_images:
            image_result = enrich_article_image(site_id, article, force=False)
            article = image_result["article"]
            if image_result.get("updated"):
                article = upsert_article(site_id, article)
        visual_result = generate_related_visual(site_id, article, force=False)
        article = visual_result["article"]
        if visual_result.get("updated"):
            article = upsert_article(site_id, article)
        imported.append(article)
        known.add(sig)
        known.add(link)
        known.add(link_key)

    state["imported_signatures"] = sorted(known)[-MAX_STATE_SIGNATURES:]
    state["last_import_at"] = now_iso()
    state["last_source_status"] = payload.get("source_status", [])
    state["last_cycle"] = {
        "site_id": site_id,
        "limit": resolved_limit,
        "max_items": resolved_max_items,
        "status": resolved_status,
        "publish_site": resolved_publish_site,
        "enrich_images": resolved_enrich_images,
        "min_publish_score": defaults["min_publish_score"],
        "source_workers": defaults["source_workers"],
        "article_detail_workers": defaults["article_detail_workers"],
        "imported_count": len(imported),
        "skipped_count": len(skipped),
        "live_item_count": payload.get("live_item_count", 0),
        "generated_at": payload.get("generated_at"),
    }
    save_state(state)

    public_dir = None
    if resolved_publish_site and imported:
        public_dir = str(generate_site(site_id))
    return {
        "ok": True,
        "generated_at": payload["generated_at"],
        "imported_count": len(imported),
        "skipped_count": len(skipped),
        "imported": imported,
        "skipped": skipped,
        "source_status": payload.get("source_status", []),
        "public_dir": public_dir,
    }


def load_state() -> dict[str, Any]:
    path = project_path(str(STATE_PATH.relative_to(ROOT)))
    if not path.exists():
        return normalize_state({"imported_signatures": []})
    return normalize_state(json.loads(path.read_text(encoding="utf-8")))


def save_state(state: dict[str, Any]) -> None:
    path = project_path(str(STATE_PATH.relative_to(ROOT)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalize_state(state), ensure_ascii=False, indent=2), encoding="utf-8")


def run_loop(
    *,
    site_id: str = "turkiye-gundemi",
    limit: int | None = None,
    max_items: int | None = None,
    status: str | None = None,
    publish_site: bool | None = None,
    enrich_images: bool | None = None,
    heal_network: bool = True,
    interval_seconds: int | None = None,
) -> int:
    defaults = load_runtime_defaults()
    sleep_seconds = clamp_int(
        interval_seconds if interval_seconds is not None else defaults["scan_interval_seconds"],
        defaults["scan_interval_seconds"],
        60,
        86_400,
    )
    while True:
        try:
            network_result = heal_network_runtime(site_id, apply_config=True, publish_site=False, generate_dns_files=True) if heal_network else None
            result = import_news(
                site_id=site_id,
                limit=limit,
                max_items=max_items,
                status=status,
                publish_site=publish_site,
                enrich_images=enrich_images,
            )
            if network_result:
                result["network"] = network_result
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 - daemon mode should keep running
            result = {"ok": False, "generated_at": now_iso(), "error": str(exc)}
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        time.sleep(sleep_seconds)


def article_facts(item: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    details = item.get("details") or {}
    if isinstance(details, dict):
        candidates.extend(str(part) for part in details.get("sentences", []) if part)
        if details.get("description"):
            candidates.append(str(details["description"]))
    candidates.append(str(item.get("summary", "")))
    facts = select_fact_sentences(candidates, title=item.get("title", ""), max_sentences=MAX_ARTICLE_FACTS)
    return facts or [normalize_sentence(item["title"])]


def make_spot(
    title: str,
    facts: list[str],
    fallback: str = "",
    category: str = "gundem",
    *,
    source_title: str | None = None,
) -> str:
    reference_title = clean_text(source_title or title)
    source_facts = editorial_fact_pack(facts, reference_title) or editorial_fact_pack([fallback or reference_title], reference_title)
    if not source_facts:
        preserving = meaning_preserving_sentence(reference_title, facts, category) or reference_title
        if is_generic_spot(preserving):
            preserving = f"{reference_title} konusu gündemde; haberin ayrıntıları kaynaklardan gelen bilgilerle netleşiyor"
        return compact_summary(apply_editorial_paraphrase_replacements(preserving), title, max_chars=380)
    summary = compose_organic_summary(title, category, source_facts)
    return ensure_organic_spot(summary, title, reference_title, category, source_facts)


def ensure_organic_spot(summary: str, title: str, source_title: str, category: str, facts: list[str]) -> str:
    spot = remove_editorial_artifacts(summary)
    title_key = normalized_title(title)
    source_key = normalized_title(source_title)
    spot_key = normalized_title(spot)
    if spot_key in {title_key, source_key} or headline_too_close(spot, source_title):
        lead = headline_from_facts(source_title, facts, category)
        if lead and not headline_too_close(lead, source_title):
            spot = lead.rstrip(".")
        else:
            spot = meaning_preserving_sentence(source_title, facts, category) or title
    generic_spot = is_generic_spot(spot)
    if generic_spot or not text_preserves_meaning(spot, source_title, facts):
        preserving = meaning_preserving_sentence(source_title, facts, category)
        if preserving:
            spot = preserving if generic_spot else f"{preserving} {spot}"
    spot = re.sub(rf"^{re.escape(title)}\s+başlığında\s+", "", spot, flags=re.I)
    spot = re.sub(rf"^{re.escape(source_title)}\s+başlığında\s+", "", spot, flags=re.I)
    spot = compact_summary(repair_organic_sentence_flow(spot), title, max_chars=380)
    if not sentence_is_complete(spot):
        for fact in facts:
            candidate = compact_summary(repair_organic_sentence_flow(fact), title, max_chars=380)
            if sentence_is_complete(candidate) and text_preserves_meaning(candidate, source_title, facts):
                return candidate
        preserving = meaning_preserving_sentence(source_title, facts, category)
        if preserving and sentence_is_complete(preserving):
            return compact_summary(preserving, title, max_chars=380)
    return spot


def is_generic_spot(value: str) -> bool:
    text = clean_text(value)
    return bool(
        re.search(
            r"\b(gelişmeye ilişkin (?:yeni )?bilgiler|gelişmeye ilişkin yeni bilgiler paylaşıldı|ayrıntılar .* takip ediliyor|haberinde öne çıkan bilgiler|ayrıntılar netleşiyor)\b",
            text,
            flags=re.I,
        )
    )


def compose_news_body(
    item: dict[str, Any],
    facts: list[str],
    *,
    display_title: str | None = None,
    source_title: str | None = None,
) -> list[str]:
    title = clean_text(display_title or item["title"]).strip()
    reference_title = clean_text(source_title or item["title"]).strip()
    category_slug = item.get("category", "gundem")
    facts = editorial_fact_pack(facts, reference_title)
    if not facts:
        facts = editorial_fact_pack([item.get("summary") or reference_title], reference_title)

    body = compose_organic_body(title, category_slug, facts)

    while len(body) < MIN_PUBLIC_PARAGRAPHS:
        extra = organic_context_paragraph(title, category_slug, facts, len(body))
        if not extra or any(is_near_duplicate_sentence(extra, existing) for existing in body):
            break
        body.append(extra)

    distinct = enforce_source_distinction(dedupe_paragraphs(body), facts, reference_title, category_slug)
    distinct = restore_missing_meaning(distinct, title, reference_title, facts, category_slug)
    distinct = polish_story_flow(distinct, title, facts, category_slug)
    return [paragraph for paragraph in distinct if paragraph]


def restore_missing_meaning(
    paragraphs: list[str],
    display_title: str,
    source_title: str,
    facts: list[str],
    category: str,
) -> list[str]:
    full_text = " ".join([display_title, *paragraphs])
    if text_preserves_meaning(full_text, source_title, facts):
        return paragraphs
    preserving = meaning_preserving_sentence(source_title, facts, category)
    if not preserving:
        return paragraphs
    if any(is_near_duplicate_sentence(preserving, paragraph) for paragraph in paragraphs):
        return paragraphs
    return [preserving, *paragraphs]


def organic_context_paragraph(title: str, category: str, facts: list[str], index: int) -> str:
    useful = [fact for fact in facts if clean_text(fact) and title_overlap_ratio(title, fact) < 0.82]
    if useful:
        fact = useful[index % len(useful)]
        sentence = repair_organic_sentence_flow(apply_editorial_paraphrase_replacements(remove_dateline_fragment(fact)))
        if sentence and not fact_is_weak_fragment(sentence):
            return normalize_sentence(sentence)
    return ""


def polish_story_flow(paragraphs: list[str], title: str, facts: list[str], category: str) -> list[str]:
    cleaned: list[str] = []
    seen_sentences: list[str] = []
    for paragraph in paragraphs:
        sentences: list[str] = []
        for sentence in split_sentences(paragraph):
            fixed = repair_organic_sentence_flow(sentence)
            if not fixed or fact_is_weak_fragment(fixed):
                continue
            if not sentence_is_complete(normalize_sentence(fixed)):
                continue
            if any(is_near_duplicate_sentence(fixed, existing) for existing in seen_sentences):
                continue
            sentences.append(fixed)
            seen_sentences.append(fixed)
        if sentences:
            cleaned.append(normalize_sentence(" ".join(sentences)))
    while len(cleaned) < MIN_PUBLIC_PARAGRAPHS:
        extra = organic_context_paragraph(title, category, facts, len(cleaned))
        if not extra:
            break
        if any(is_near_duplicate_sentence(extra, existing) for existing in cleaned):
            extra = organic_context_paragraph(title, category, facts, len(cleaned) + 7)
        if not extra or any(is_near_duplicate_sentence(extra, existing) for existing in cleaned):
            break
        cleaned.append(extra)
    attempts = 0
    while len(clean_text(" ".join(cleaned))) < MIN_PUBLIC_BODY_CHARS and len(cleaned) < 8 and attempts < 5:
        extra = organic_context_paragraph(title, category, facts, len(cleaned) + 11 + attempts)
        attempts += 1
        if not extra:
            break
        if any(is_near_duplicate_sentence(extra, existing) for existing in cleaned):
            continue
        cleaned.append(extra)
    result = dedupe_paragraphs(cleaned)
    filler = 0
    while len(result) < MIN_PUBLIC_PARAGRAPHS and filler < 8:
        extra = organic_context_paragraph(title, category, facts, len(result) + 23 + filler)
        filler += 1
        if not extra:
            break
        if any(is_near_duplicate_sentence(extra, existing) for existing in result):
            continue
        result.append(extra)
    return result


def repair_organic_sentence_flow(value: str) -> str:
    text = remove_editorial_artifacts(value)
    replacements = [
        (r"\bulaşıma açılması\.\s+Devamında\s+", "ulaşıma açıldı. "),
        (r"\btemizlenmesi\.\s+Devamında\s+", "temizlendi. "),
        (r"^Devamında\s+", ""),
        (r"\bDevamında\s+", "Ayrıca "),
        (r"\bkaydederek\.?$", "kaydetti."),
        (r"\bbelirterek\.?$", "belirtti."),
        (r"\baktararak\.?$", "aktardı."),
        (r"\baktaran\.?$", "aktardı."),
        (r"\bbildirerek\.?$", "bildirdi."),
        (r"\bvurgulayarak\.?$", "vurguladı."),
        (r"\bdile getirerek\.?$", "dile getirdi."),
        (r"\bifade ederek\.?$", "ifade etti."),
        (r"\bgündem gündemindeki\b", "gündemdeki"),
        (r"\b(.+?)\s+da haberin önemli ayrıntıları arasında\.?$", r"\1"),
        (r"\b(.+?)\s+iken da haberin önemli ayrıntıları arasında\.?", r"\1."),
        (r"\b(.+?)\s+da haberin önemli ayrıntıları arasında\.\s*", r"\1. "),
        (r"\b(.+?)\s+da haberin öne çıkan ayrıntıları arasında\.?$", r"\1"),
        (r"\b(.+?)\s+dosyada öne çıkan başlıklar arasında\.?$", r"\1"),
        (r"\b(.+?)\s+başlığı da dosyada yer aldı\.?$", r"\1"),
        (r"\bBu başlıkla bağlantılı olarak\s+", ""),
        (r"\bgelişme yakından takip ediliyor\.?$", "süreçle ilgili yeni açıklamalar bekleniyor."),
        (r"\bbaşlığı gündemde takip ediliyor\.?$", "gündemde takip ediliyor."),
        (r"\s+başlığı\s+gündemde\s+", " gündemde "),
        (r"\bhiç bir\b", "hiçbir"),
        (r"\bİlkbahar\b", "ilkbahar"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.I)
    text = re.sub(r",\s*\.", ".", text)
    text = re.sub(
        r"\b[^.!?]{10,220}?\b(?:kaydederek|belirterek|aktararak|bildirerek|vurgulayarak|eleştirerek|dile getirerek|ifade ederek),?\.\s*",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"\s+\.", ".", text)
    text = re.sub(r"\.\s*\.", ".", text)
    return clean_text(text)


def meaning_preserving_sentence(source_title: str, facts: list[str], category: str) -> str:
    title = clean_text(source_title)
    if not title:
        return ""
    anchors = semantic_anchors(title) | numeric_anchors(title)
    best_fact = ""
    best_score = -1
    for fact in facts:
        fact_text = clean_text(fact)
        if not fact_text:
            continue
        fact_key = normalized_title(fact_text)
        score = sum(1 for anchor in anchors if anchor in fact_key)
        if score > best_score:
            best_score = score
            best_fact = fact_text
    if best_fact and (best_score > 0 or not anchors or is_question_style_title(title)):
        sentence = apply_editorial_paraphrase_replacements(remove_dateline_fragment(best_fact))
        sentence = remove_editorial_artifacts(sentence)
        return normalize_sentence(sentence)
    if not is_rejected_title(title):
        context = "gündemde" if category in {"gundem", "son-dakika"} else f"{category_label(category)} gündeminde"
        return normalize_sentence(f"{title} başlığı {context} takip ediliyor")
    return ""


def is_question_style_title(value: str) -> bool:
    text = clean_text(value).casefold()
    return "?" in text or bool(re.search(r"\b(mi|mı|mu|mü|miyiz|mıyız|muyuz|müyüz)\b", text))


def chunk_facts(facts: list[str], *, size: int = 2) -> list[list[str]]:
    chunks: list[list[str]] = []
    rest = [fact for fact in facts if clean_text(fact)]
    while rest:
        chunks.append(rest[:size])
        rest = rest[size:]
    return chunks


def compose_organic_summary(title: str, category: str, facts: list[str]) -> str:
    lead_fact = choose_lead_fact(title, facts)
    second_fact = next((fact for fact in facts if fact != lead_fact and title_overlap_ratio(title, fact) < 0.78), "")
    first = organic_rewrite_sentence(lead_fact, title, category, index=0)
    parts = [first]
    if second_fact and len(first) < 185:
        second = organic_rewrite_sentence(second_fact, title, category, index=1)
        if second and not is_near_duplicate_sentence(first, second):
            parts.append(second)
    summary = " ".join(part for part in parts if part)
    if not summary:
        summary = f"{category_context(category).capitalize()} gelişmeye ilişkin bilgiler kamuoyuna yansıdı"
    summary = remove_editorial_artifacts(summary)
    summary = compact_summary(summary, title, max_chars=380)
    if source_text_too_close(summary, facts):
        summary = organic_fallback_summary(title, category, facts)
    return normalize_sentence(summary)


def compose_organic_body(title: str, category: str, facts: list[str]) -> list[str]:
    ordered = order_facts_for_story(title, facts)
    paragraphs: list[str] = []
    used: set[str] = set()
    for index, chunk in enumerate(chunk_facts(ordered, size=2)):
        sentences: list[str] = []
        for fact in chunk:
            key = normalized_title(fact)
            if not key or key in used:
                continue
            used.add(key)
            rewritten = organic_rewrite_sentence(fact, title, category, index=index + len(sentences))
            if rewritten and not any(is_near_duplicate_sentence(rewritten, existing) for existing in sentences):
                sentences.append(rewritten)
        paragraph = remove_editorial_artifacts(" ".join(sentences))
        if paragraph:
            paragraphs.append(normalize_sentence(paragraph))
        if len(paragraphs) >= 6:
            break
    paragraphs = [repair_organic_paragraph(paragraph, title, category) for paragraph in paragraphs]
    return dedupe_paragraphs([paragraph for paragraph in paragraphs if paragraph])


def order_facts_for_story(title: str, facts: list[str]) -> list[str]:
    lead = choose_lead_fact(title, facts)
    remaining = [fact for fact in facts if fact != lead]
    useful = [fact for fact in remaining if not fact_is_weak_fragment(fact)]
    weak = [fact for fact in remaining if fact_is_weak_fragment(fact)]
    return [lead, *useful, *weak]


def organic_rewrite_sentence(value: str, title: str, category: str, *, index: int = 0) -> str:
    original = refine_fact_sentence(value)
    original = remove_title_prefix(original, title)
    original = remove_dateline_fragment(original)
    if not original:
        return ""
    quote = rewrite_quote_fact(original)
    if quote:
        return quote
    text = apply_editorial_paraphrase_replacements(original)
    text = remove_editorial_artifacts(text)
    text = heal_incomplete_organic_sentence(text, title, category)
    return normalize_sentence(text)


def reframe_organic_sentence(value: str, title: str, category: str, *, index: int = 0) -> str:
    text = remove_dateline_fragment(apply_editorial_paraphrase_replacements(value))
    clauses = [clause for clause in split_rewrite_clauses(text) if not fact_is_weak_fragment(clause)]
    if len(clauses) >= 2:
        first = lower_first(clauses[0].rstrip("."))
        second = lower_first(clauses[-1].rstrip("."))
        templates = [
            "{first_cap}. Ayrıca {second}",
            "{second}. İlk bilgilerde {first} vurgusu öne çıktı",
            "{first_cap}. Buna paralel olarak {second}",
        ]
        return normalize_sentence(templates[index % len(templates)].format(first=first, first_cap=uppercase_turkish_start(first), second=second))
    cleaned = clauses[0] if clauses else text
    if title_overlap_ratio(title, cleaned) > 0.7:
        return normalize_sentence(organic_fallback_summary(title, category, [cleaned]))
    return normalize_sentence(cleaned)


def organic_fallback_summary(title: str, category: str, facts: list[str]) -> str:
    context = category_context(category)
    detail = ""
    for fact in facts:
        cleaned = remove_dateline_fragment(remove_title_prefix(fact, title))
        if cleaned and title_overlap_ratio(title, cleaned) < 0.65:
            detail = cleaned
            break
    if detail:
        return normalize_sentence(apply_editorial_paraphrase_replacements(detail))
    return normalize_sentence(f"{context.capitalize()} gelişmeye ilişkin yeni bilgiler paylaşıldı")


def repair_organic_paragraph(paragraph: str, title: str, category: str) -> str:
    text = remove_editorial_artifacts(paragraph)
    text = repair_organic_sentence_flow(text)
    text = re.sub(r"\b([A-Za-zÇĞİÖŞÜçğıöşü0-9'’.-]+)\.\s+Devamında\s+", r"\1. ", text)
    text = re.sub(r"\s+başlığı,\s*", " başlığı ", text)
    text = re.sub(r"\bTürkiye gündeminde Türkiye gündeminde\b", "Türkiye gündeminde", text, flags=re.I)
    text = re.sub(r"\bSüreçle ilgili ikinci başlıkta\s*", "", text, flags=re.I)
    text = re.sub(r"\bHabere konu olan gelişmede\s*", "", text, flags=re.I)
    text = re.sub(r"\bAyrıntılara göre\s*", "", text, flags=re.I)
    if fact_is_weak_fragment(text):
        return organic_fallback_summary(title, category, [text])
    return normalize_sentence(text)


def remove_editorial_artifacts(value: str) -> str:
    text = clean_text(value)
    artifacts = [
        (r"\bTürkiye Gündemi tarafından yeniden derlenerek (?:aktarıldı|paylaşıldı)\.?", ""),
        (r"^\s*['\"]?[^.?!]{0,260}?\s+başlığında yeni ayrıntılar netleşti\.?\s*['\"]?$", ""),
        (r"\b[^.;!?]{8,180}?\s+başlığında yeni ayrıntılar netleşti\.?\s*", ""),
        (r"^\s*başlığında yeni ayrıntılar netleşti\.?\s*", ""),
        (r"^\s*yeni ayrıntılar netleşti\.?\s*", ""),
        (r"^\s*yeni bilgiler paylaşıldı\.?\s*", ""),
        (r"\bGelişmenin arka planında\s+([^.;]+?)\s+ayrıntısı yer aldı\b", r"\1"),
        (r"\bBu gelişmede\s+([^.;]+?)\s+bilgisi de (?:paylaşıldı|öne çıktı)\b", r"\1"),
        (r"\b[a-zçğıöşüA-ZÇĞİÖŞÜ0-9 .'-]+ kaynaklı bilgilerde öne çıkan başlık,?\s*", ""),
        (r"\bTürkiye gündeminde öne çıkan gelişmede\s*", ""),
        (r"\bson dakika akışında öne çıkan gelişmede\s*", ""),
        (r"\bdış haberler dosyasında öne çıkan gelişmede\s*", ""),
        (r"\bekonomi başlığında öne çıkan gelişmede\s*", ""),
        (r"\bteknoloji gündeminde öne çıkan gelişmede\s*", ""),
        (r"\bspor gündeminde öne çıkan gelişmede\s*", ""),
        (r"\bkültür sanat akışında öne çıkan gelişmede\s*", ""),
        (r"\bBu ayrıntı Türkiye gündeminde öne çıktı\.?", ""),
        (r"\bSüreç,\s*([^.;]+?)\s+bilgisiyle birlikte takip ediliyor\b", r"\1"),
        (r"\bgelişmenin çıkış noktasında\s*([^.;]+?)\s+ayrıntısı yer aldı\b", r"\1"),
        (r"\bbilgisi öne çıktı\b", "bilgisi paylaşıldı"),
        (r"\bbilgisi dikkat çekti\b", "ayrıntısı dikkat çekti"),
        (r"\bbilgisi paylaşıldı\b", "bilgisi paylaşıldı"),
        (r"\bgelişmesi gündeme geldi\b", "gelişmesi kayda geçti"),
        (r"\bkonu ([^.;]+?) çerçevesinde yeni ayrıntılarla takip ediliyor\b", r"\1 başlığıyla ilgili ayrıntılar takip ediliyor"),
    ]
    for pattern, replacement in artifacts:
        text = re.sub(pattern, replacement, text, flags=re.I)
    text = re.sub(r"\s+\.", ".", text)
    text = re.sub(r"\.\s*\.", ".", text)
    text = re.sub(r"\s+", " ", text).strip(" ,;")
    return text


def remove_dateline_fragment(value: str) -> str:
    text = clean_text(value)
    text = re.sub(r"^\d{1,2}\.\d{1,2}\.\d{4}\.?\s*", "", text)
    text = re.sub(r"^[A-ZÇĞİÖŞÜ][a-zçğıöşü]+;\s*", "", text)
    return clean_text(text)


def heal_incomplete_organic_sentence(value: str, title: str, category: str) -> str:
    text = clean_text(value)
    if fact_is_weak_fragment(text):
        return organic_fallback_summary(title, category, [text])
    text = re.sub(r"\b([A-ZÇĞİÖŞÜ][a-zçğıöşü]+)\.\s+Devamında\s+", r"\1. ", text)
    text = re.sub(r"\b([A-ZÇĞİÖŞÜ][a-zçğıöşü]+)\s+bilgisi\b", r"\1'e ilişkin bilgi", text)
    return clean_text(text)


def fact_is_weak_fragment(value: str) -> bool:
    text = clean_text(value).strip(" .;:")
    if not text:
        return True
    if re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{4}", text):
        return True
    words = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü0-9'’.-]+", text)
    if len(words) <= 3 and len(text) < 32:
        return True
    if re.search(r"\b(başlığı|ayrıntısı|bilgisi)$", text.casefold()) and len(words) < 7:
        return True
    lowered = text.casefold()
    if re.search(
        r"\b(kaydederek|belirterek|aktararak|aktaran|bildirerek|vurgulayarak|dile getirerek|ifade ederek|açılması|edilmesi|yapılması|verilmesi|bulunması|temizlenmesi)$",
        lowered,
    ):
        return True
    return False


def compose_original_lead(title: str, category: str, lead_fact: str, source_name: str = "") -> str:
    context = category_context(category)
    rewritten = rewrite_fact_sentence(lead_fact or title, title, category, index=0, role="lead")
    source_clause = f" {source_name} kaynaklı bilgilerde öne çıkan başlık, Türkiye Gündemi tarafından yeniden derlenerek aktarıldı." if source_name else ""
    lead = f"{context.capitalize()} öne çıkan gelişmede {lower_first(rewritten).rstrip('.')}.{source_clause}"
    return normalize_sentence(lead)


def compose_original_detail(title: str, category: str, facts: list[str], index: int) -> str:
    rewritten = [rewrite_fact_sentence(fact, title, category, index=index + offset, role="detail") for offset, fact in enumerate(facts)]
    rewritten = [part.rstrip(".") for part in rewritten if clean_text(part)]
    if not rewritten:
        return ""
    if len(rewritten) == 1:
        templates = [
            "Ayrıntılarda {first}",
            "Gelişmenin devamında {first}",
            "Başlığa ilişkin aktarımlarda {first} bilgisi paylaşıldı",
        ]
        return normalize_sentence(templates[index % len(templates)].format(first=lower_first(rewritten[0])))
    templates = [
        "Ayrıntılara göre {first}. Bunun yanında {second}",
        "Süreçle ilgili ikinci başlıkta {first}; ayrıca {second}",
        "Habere konu olan gelişmede {first}. Aktarılan diğer bilgi ise {second}",
    ]
    return normalize_sentence(
        templates[index % len(templates)].format(first=lower_first(rewritten[0]), second=lower_first(rewritten[1]))
    )


def rewrite_fact_sentence(value: str, title: str, category: str, *, index: int = 0, role: str = "detail") -> str:
    original = refine_fact_sentence(value)
    if not original:
        return ""
    transformed = apply_editorial_paraphrase_replacements(original)
    quoted = rewrite_quote_fact(transformed)
    if quoted:
        return normalize_sentence(quoted)
    clauses = split_rewrite_clauses(transformed)
    if len(clauses) >= 2 and is_incomplete_rewrite_clause(clauses[0]):
        clauses = [clean_text(f"{clauses[0]} {clauses[1]}"), *clauses[2:]]
    context = category_context(category)
    if len(clauses) >= 2:
        first = lower_first(clauses[0].rstrip("."))
        last = lower_first(clauses[-1].rstrip("."))
        middle = lower_first(clauses[1].rstrip(".")) if len(clauses) > 2 else ""
        templates = [
            "{first_cap}. Ayrıca {last}",
            "{last}. İlk bilgilerde {first} vurgusu öne çıktı",
            "{last}. {first_cap} başlığı da dosyada yer aldı",
            "{first}; bu gelişmeyle birlikte {last}",
        ]
        text = templates[index % len(templates)].format(first=first, first_cap=uppercase_turkish_start(first), last=last, middle=middle)
        if middle and index % 2 == 0:
            text = f"{text}; ayrıca {middle}"
    else:
        core = lower_first(clauses[0].rstrip(".") if clauses else transformed.rstrip("."))
        templates = [
            "{core}; bu ayrıntı {context} öne çıktı",
            "{context} {core} ayrıntısı dikkat çekti",
            "Aktarılan bilgilere göre {core}; gelişme yakından takip ediliyor",
            "{core} başlığı, son haber akışında yeni bir ayrıntı olarak kayda geçti",
        ]
        text = templates[(index + (1 if role == "spot" else 0)) % len(templates)].format(core=core, context=context)
    text = normalize_sentence(text)
    if source_text_too_close(text, [original]):
        text = reframe_too_close_sentence(original, title, category, index=index)
    return normalize_sentence(text)


def choose_lead_fact(title: str, facts: list[str]) -> str:
    for fact in facts:
        if title_overlap_ratio(title, fact) < 0.45 and '"' not in fact and len(clean_text(fact)) >= 80:
            return fact
    for fact in facts:
        if title_overlap_ratio(title, fact) < 0.45:
            return fact
    return facts[0] if facts else title


def title_overlap_ratio(title: str, text: str) -> float:
    title_words = {
        word
        for word in re.findall(r"[a-zçğıöşü0-9']{4,}", clean_text(title).casefold())
        if word not in {"haber", "son", "dakika", "yeni", "ilgili", "başlığı"}
    }
    text_words = set(re.findall(r"[a-zçğıöşü0-9']{4,}", clean_text(text).casefold()))
    if not title_words:
        return 0.0
    return len(title_words & text_words) / max(1, len(title_words))


def is_incomplete_rewrite_clause(value: str) -> bool:
    text = clean_text(value).casefold().rstrip(".")
    if not text:
        return True
    if re.search(r"\b(iken|olarak|için|üzere|sonra|önce|nedeniyle|sırasında)$", text):
        return True
    if re.search(r"\b(de|da|te|ta|nda|nde|daki|deki)$", text):
        return True
    return False


def apply_editorial_paraphrase_replacements(value: str) -> str:
    text = clean_text(value)
    replacements = [
        (r"\bbelirtti\b", "dile getirdi"),
        (r"\bbelirterek\b", "kaydederek"),
        (r"\baçıkladı\b", "duyurdu"),
        (r"\baçıklandı\b", "kamuoyuna bildirildi"),
        (r"\byazılı değerlendirmede bulundu\b", "yazılı açıklama yaptı"),
        (r"\bifade etti\b", "dile getirdi"),
        (r"\bifadesini kullandı\b", "sözleriyle dikkat çekti"),
        (r"\bifadesi kullanıldı\b", "sözleri kayda geçti"),
        (r"\bkaydetti\b", "aktardı"),
        (r"\bsöyledi\b", "dile getirdi"),
        (r"\bbildirildi\b", "paylaşıldı"),
        (r"\bbildirdi\b", "paylaştı"),
        (r"\bvurguladı\b", "kaydetti"),
        (r"\banımsattı\b", "hatırlattı"),
        (r"\bbilgisini veren\b", "aktaran"),
        (r"\bbilgisini paylaştı\b", "bilgi verdi"),
        (r"\bUlaştırma ve Altyapı Bakanı Abdulkadir Uraloğlu\b", "Bakan Abdulkadir Uraloğlu"),
        (r"\biniş yaptı\b", "indi"),
        (r"\bİstanbul'a geldi\b", "İstanbul'a ulaştı"),
        (r"\bgeniş bir heyetle\b", "geniş heyetiyle"),
        (r"\bresmi temaslar kapsamında\b", "resmi temaslar için"),
        (r"\b14 yıl aradan sonra gerçekleşen ziyaret kapsamında\b", "14 yıl sonra yapılan programda"),
        (r"\byeni iş birliği fırsatları ele alınacak\b", "yeni iş birliği başlıkları masaya yatırılacak"),
        (r"\bbir araya geldi\b", "görüştü"),
        (r"\bsevk edildi\b", "gönderildi"),
        (r"\bgözaltına alındı\b", "gözaltı işlemi uygulandı"),
        (r"\byaralandı\b", "yaralı olarak kayda geçti"),
        (r"\bhayatını kaybetti\b", "yaşamını yitirdi"),
        (r"\bmeydana geldi\b", "yaşandı"),
        (r"\btespit edildi\b", "belirlendi"),
        (r"\bkontrolden çıkan\b", "hakimiyeti kaybedilen"),
        (r"\bkaza yerine\b", "olay bölgesine"),
        (r"\bihbar üzerine\b", "bildirim sonrası"),
        (r"\bekipleri sevk edildi\b", "ekipleri bölgeye yönlendirildi"),
        (r"\bgündeme geldi\b", "öne çıktı"),
        (r"\bson dakika\b", "son haber"),
        (r"\baktarıldı\b", "paylaşıldı"),
        (r"\byapılan açıklamada\b", "paylaşılan açıklamada"),
        (r"\biddia edildi\b", "iddiası kamuoyuna yansıdı"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.I)
    return clean_text(text)


def rewrite_quote_fact(value: str) -> str:
    text = clean_text(value)
    match = re.search(r"(.{8,120}?),\s*\"([^\"]{6,180})\"\s*(?:sözleriyle dikkat çekti|dile getirdi|dedi|ifadesini kullandı)", text, flags=re.I)
    if not match:
        return ""
    speaker, quote = match.groups()
    speaker = clean_text(speaker)
    quote = clean_text(quote)
    speaker = re.sub(r"^(Sosyal medya hesabından\s+)?Yaşadıklarını anlatan\s+", "", speaker, flags=re.I).strip(" ,")
    speaker = re.sub(r"^Sosyal medya hesabından\s+", "", speaker, flags=re.I).strip(" ,")
    if not speaker:
        speaker = "Açıklamada"
    return f"{speaker} aktarımında \"{quote}\" sözleri öne çıktı"


def split_rewrite_clauses(value: str) -> list[str]:
    text = clean_text(value)
    parts = [part.strip(" ,;:") for part in re.split(r"\s*[,;]\s+|\s+-\s+", text) if part.strip(" ,;:")]
    if len(parts) <= 1 and len(text) > 190:
        parts = [part.strip(" ,;:") for part in re.split(r"\s+(?:ve|ancak|ayrıca|bunun üzerine)\s+", text, maxsplit=2) if part.strip(" ,;:")]
    return [clean_text(part) for part in parts if clean_text(part)] or [text]


def reframe_too_close_sentence(value: str, title: str, category: str, *, index: int = 0) -> str:
    clauses = split_rewrite_clauses(apply_editorial_paraphrase_replacements(value))
    context = category_context(category)
    headline = lower_first(title).rstrip(".")
    if len(clauses) >= 2:
        return normalize_sentence(
            f"{context.capitalize()} {lower_first(clauses[-1]).rstrip('.')}; konu {headline} çerçevesinde yeni ayrıntılarla takip ediliyor"
        )
    return normalize_sentence(
        f"{context.capitalize()} {headline} başlığı öne çıkarken, gelişmeye ilişkin bilgiler farklı kaynaklardan gelen aktarımlarla netleşti"
    )


def enforce_source_distinction(paragraphs: list[str], source_facts: list[str], title: str, category: str) -> list[str]:
    distinct: list[str] = []
    for index, paragraph in enumerate(paragraphs):
        candidate = normalize_sentence(paragraph)
        if source_text_too_close(candidate, source_facts):
            candidate = organic_rewrite_sentence(candidate, title, category, index=index)
        if source_text_too_close(candidate, source_facts):
            candidate = reframe_organic_sentence(candidate, title, category, index=index)
        distinct.append(candidate)
    return dedupe_paragraphs(distinct)


def source_text_too_close(candidate: str, source_facts: list[str]) -> bool:
    candidate_text = clean_text(candidate)
    candidate_key = normalized_title(candidate_text)
    if not candidate_key:
        return False
    for source in source_facts:
        source_text = clean_text(source)
        source_key = normalized_title(source_text)
        if len(source_key) < 50:
            continue
        if (source_key in candidate_key or candidate_key in source_key) and (
            min(len(source_key), len(candidate_key)) / max(1, max(len(source_key), len(candidate_key))) > 0.86
        ):
            return True
        if source_copy_ratio(candidate_text, source_text) >= SOURCE_COPY_RATIO_LIMIT:
            return True
    return False


def source_copy_ratio(candidate: str, source: str) -> float:
    first = clean_text(candidate).casefold()
    second = clean_text(source).casefold()
    if not first or not second:
        return 0.0
    return SequenceMatcher(None, first, second).ratio()


def source_copy_flags(output_parts: list[str], source_facts: list[str]) -> int:
    flags = 0
    for part in output_parts:
        if source_text_too_close(part, source_facts):
            flags += 1
    return flags


def originality_note_paragraph(category: str) -> str:
    context = category_context(category)
    return normalize_sentence(
        f"{context.capitalize()} izlenen gelişme, yeni bilgiler geldikçe editoryal süzgeçten geçirilerek güncellenecek"
    )


def editorial_fact_pack(facts: list[str], title: str) -> list[str]:
    packed: list[str] = []
    seen: set[str] = set()
    title_key = normalized_title(title)
    for fact in facts:
        sentence = refine_fact_sentence(fact)
        sentence = remove_title_prefix(sentence, title)
        if not is_useful_fact(sentence):
            continue
        if packed and (starts_with_lowercase(sentence) or ends_with_incomplete_clause(packed[-1])):
            combined = normalize_sentence(f"{packed[-1].rstrip('.')} {sentence}")
            packed[-1] = combined
            seen.add(normalized_title(combined))
            continue
        key = normalized_title(sentence)
        if not key or key == title_key or key in seen:
            continue
        if any(is_near_duplicate_sentence(sentence, existing) for existing in packed):
            continue
        seen.add(key)
        packed.append(normalize_sentence(sentence))
        if len(packed) >= MAX_ARTICLE_FACTS:
            break
    return packed


def remove_title_prefix(sentence: str, title: str) -> str:
    text = clean_text(sentence)
    title_text = clean_text(title).rstrip(".!?")
    if not text or not title_text:
        return text
    if text.casefold().startswith(title_text.casefold()):
        rest = text[len(title_text) :].lstrip(" .,:;-")
        if len(rest) >= 35:
            return normalize_sentence(rest)
    title_key = normalized_title(title_text)
    text_key = normalized_title(text)
    if title_key and text_key.startswith(title_key) and len(text_key) > len(title_key) + 30:
        parts = split_rewrite_clauses(text)
        for part in parts[1:]:
            if len(part) >= 35:
                return normalize_sentence(part)
    return text


def refine_fact_sentence(value: str) -> str:
    text = strip_section_label(clean_text(value))
    text = re.sub(r'"[A-ZÇĞİÖŞÜ0-9, .!?]{18,}"\s*', "", text)
    replacements = [
        (r"^Edinilen bilgiye göre,\s*", ""),
        (r"^Alınan bilgiye göre,\s*", ""),
        (r"^Habere göre,\s*", ""),
        (r"^Gelen son dakika haberine göre,\s*", ""),
        (r"\bbaşlığı gündeme taşındı\b", "gündeme geldi"),
        (r"\bgündem gündeminde\b", "gündemde"),
        (r"\bson dakika gündeminde\b", "son dakika akışında"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.I)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return clean_text(text)


def strip_section_label(value: str) -> str:
    text = clean_text(value)
    match = re.match(r"^([A-ZÇĞİÖŞÜ'\"., ]{8,70})\s+(.+)$", text)
    if not match:
        return text
    label, rest = match.groups()
    letters = [char for char in label if char.isalpha()]
    if not letters:
        return text
    uppercase = sum(1 for char in letters if char.upper() == char and char.lower() != char)
    if uppercase / len(letters) > 0.78:
        return clean_text(rest)
    return text


def starts_with_lowercase(value: str) -> bool:
    text = clean_text(value)
    if not text:
        return False
    first = text[0]
    return first.isalpha() and first.lower() == first and first.upper() != first


def ends_with_incomplete_clause(value: str) -> bool:
    lowered = clean_text(value).casefold()
    return bool(re.search(r"\b(dığını|diğini|duğunu|düğünü|acağını|eceğini|olduğunu|bulunduğunu)\.$", lowered))


def sentence_is_complete(value: str, *, allow_question: bool = True) -> bool:
    text = clean_text(value).strip()
    if not text:
        return False
    if has_encoding_damage(text) or has_unbalanced_quotes(text):
        return False
    if re.search(r",\s*\.|\bDevamında\b", text, flags=re.I):
        return False
    if re.search(
        r"\b(kaydederek|belirterek|aktararak|bildirerek|vurgulayarak|eleştirerek|dile getirerek|ifade ederek),?\s*\.$",
        text,
        flags=re.I,
    ):
        return False
    if ends_with_abbreviation_fragment(text):
        return False
    visible = text.lstrip("\"'“”‘’([{")
    if visible and visible[0].isalpha() and visible[0].lower() == visible[0] and visible[0].upper() != visible[0]:
        return False
    if text[-1] not in ".!?" and not (allow_question and text.endswith("?")):
        return False
    if text[-1] in ",;:":
        return False
    lowered = text.rstrip(".!?").casefold().strip()
    if not lowered:
        return False
    if re.search(
        r"\b(ve|ile|için|üzere|sonra|önce|tarafından|kapsamında|nedeniyle|dair|ilişkin|olarak|bulunan|edilen|verilen|yönelik|ise|iken|ardından|hakkında|üzerinden|kadar|dek|değin|bugüne|bugüne kadar)$",
        lowered,
    ):
        return False
    if re.search(
        r"(dığını|diğini|duğunu|düğünü|acağını|eceğini|olduğunu|bulunduğunu|yapıldığını|edildiğini|açıldığını|verildiğini)$",
        lowered,
    ):
        return False
    words = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü0-9']+", text)
    if len(words) < 5:
        return False
    return True


def text_has_complete_sentences(value: str) -> bool:
    sentences = split_sentences(value) or [clean_text(value)]
    useful = [sentence for sentence in sentences if clean_text(sentence)]
    if not useful:
        return False
    return all(sentence_is_complete(sentence) for sentence in useful)


def body_has_complete_sentences(body: list[str]) -> bool:
    if not body:
        return False
    for paragraph in body:
        text = clean_text(paragraph)
        if not sentence_is_complete(text):
            return False
        if not text_has_complete_sentences(text):
            return False
    return True


def story_preserves_required_meaning(title: str, summary: str, body: list[str], source_title: str, facts: list[str] | None = None) -> bool:
    source = clean_text(source_title)
    if not source:
        return True
    full_text = clean_text(" ".join([title, summary, *body]))
    if not text_preserves_meaning(full_text, source, facts):
        return False
    source_key = normalized_title(source)
    full_key = normalized_title(full_text)
    numeric = numeric_anchors(source)
    if numeric and not all(anchor in full_key for anchor in numeric):
        return False
    anchors = semantic_anchors(source)
    for fact in facts or []:
        anchors.update(list(semantic_anchors(fact))[:3])
    anchors = {anchor for anchor in anchors if anchor and anchor not in numeric}
    if not anchors:
        return True
    present = sum(1 for anchor in anchors if anchor in full_key)
    if len(anchors) <= 2:
        return present >= 1
    if len(source_key) <= 32:
        return present >= 1
    return present >= min(5, max(2, len(anchors) // 3))


def context_paragraph(category: str) -> str:
    label = category_label(category)
    return normalize_sentence(
        f"Konu {label} başlığında izlenirken, olayın seyri ve resmi açıklamalar geldikçe ayrıntılar netleşecek"
    )


def is_publishable_article(
    title: str,
    summary: str,
    body: list[str],
    *,
    min_quality_score: int = DEFAULT_MIN_PUBLISH_SCORE,
    quality_score: int | None = None,
    source_title: str = "",
    facts: list[str] | None = None,
) -> bool:
    if is_rejected_title(title):
        return False
    if has_encoding_damage(title) or headline_is_incomplete(title) or not headline_has_complete_predicate(title):
        return False
    if not sentence_is_complete(summary):
        return False
    if is_generic_spot(summary):
        return False
    full_text = clean_text(" ".join([summary, *body]))
    if has_encoding_damage(full_text):
        return False
    if len(body) < MIN_PUBLIC_PARAGRAPHS:
        return False
    if len(clean_text(" ".join(body))) < MIN_PUBLIC_BODY_CHARS:
        return False
    if not body_has_complete_sentences(body):
        return False
    if source_title and not story_preserves_required_meaning(title, summary, body, source_title, facts):
        return False
    if any(is_robotic_note(paragraph) for paragraph in body):
        return False
    if quality_score is not None and quality_score < min_quality_score:
        return False
    return True


def select_fact_sentences(
    values: list[str],
    *,
    title: str = "",
    max_sentences: int = MAX_ARTICLE_FACTS,
) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    title_key = normalized_title(title)
    for value in values:
        for sentence in split_sentences(clean_description(value)):
            sentence = normalize_sentence(sentence)
            if not is_useful_fact(sentence):
                continue
            key = normalized_title(sentence)
            if not key or key in seen or key == title_key:
                continue
            seen.add(key)
            results.append(sentence)
            if len(results) >= max_sentences:
                return results
    return results


def split_sentences(value: str) -> list[str]:
    text = clean_text(value)
    if not text:
        return []
    raw_parts = re.split(r"(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜ0-9])", text)
    raw_parts = merge_unbalanced_quotes(raw_parts)
    parts: list[str] = []
    for part in raw_parts:
        part = clean_text(part)
        if len(part) > 360:
            pieces = [chunk.strip(" ,;:") for chunk in re.split(r"\s*[;]\s*|\s+-\s+", part) if chunk.strip()]
            parts.extend(pieces or [part])
        else:
            parts.append(part)
    merged: list[str] = []
    for part in parts:
        if merged and should_attach_to_previous(merged[-1]):
            merged[-1] = clean_text(f"{merged[-1]} {part}")
        else:
            merged.append(part)
    return merged


def merge_unbalanced_quotes(parts: list[str]) -> list[str]:
    merged: list[str] = []
    buffer = ""
    for part in parts:
        buffer = clean_text(f"{buffer} {part}") if buffer else clean_text(part)
        if has_unbalanced_quotes(buffer):
            continue
        merged.append(buffer)
        buffer = ""
    if buffer:
        if merged:
            merged[-1] = clean_text(f"{merged[-1]} {buffer}")
        else:
            merged.append(buffer)
    return merged


def has_unbalanced_quotes(value: str) -> bool:
    text = clean_text(value)
    straight = text.count('"') % 2 == 1
    curly = (text.count("“") + text.count("”")) % 2 == 1
    return straight or curly


def should_attach_to_previous(value: str) -> bool:
    text = clean_text(value)
    if re.search(r"\b\d+\.$", text):
        return True
    if re.search(r"\b[A-ZÇĞİÖŞÜ]\.$", text):
        return True
    return text.endswith(("Dr.", "Prof.", "Doç.", "Cad.", "Sok.", "Mah.", "No."))


def is_useful_fact(text: str) -> bool:
    value = clean_text(text)
    if len(value) < 35:
        return False
    if len(value) > 780:
        return False
    if re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{4}\.?", value):
        return False
    lowered = value.casefold()
    if re.search(r"\b\d+\.$", value):
        return False
    if re.search(r"\b(bir|ve|ile|için|olarak|diye|şöyle)\.$", lowered):
        return False
    if has_unbalanced_quotes(value):
        return False
    if re.search(r"\b(şunları|şu ifadeleri|şöyle)\s+(söyledi|dedi|konuştu|kaydetti|ifade etti)\.?$", lowered):
        return False
    if value.lstrip().startswith(("*", "•", "-")):
        return False
    if value.endswith("...") and len(value) < 120:
        return False
    if re.search(r"\b(dığını|diğini|duğunu|düğünü|acağını|eceğini)\.$", lowered) and len(value) < 150:
        return False
    if has_encoding_damage(value):
        return False
    if looks_like_section_heading(value):
        return False
    bad_patterns = [
        "çerez",
        "cookie",
        "gizlilik",
        "kullanım koşulları",
        "reklam",
        "abone",
        "bildirim",
        "whatsapp",
        "telegram",
        "son dakika haberleri",
        "tüm hakları",
        "kaynak gösterilerek",
        "iktibas edilemez",
        "kitapları indirimli",
        "indirimli fiyat",
        "keşfedin",
        "favori ürün",
        "alışveriş",
        "sepete",
        "e-bülten",
        "bültene üye",
        "t. c.",
        "t.c.",
        "sulh hukuk",
        "satış memurluğu",
        "icra dairesi",
        "esas no",
        "karar no",
        "ilan.gov.tr",
        "uyap",
        "resmi ilan",
        "ilan portalı",
        "astroloji",
        "burç yorum",
    ]
    return not any(pattern in lowered for pattern in bad_patterns)


def is_rejected_title(title: str) -> bool:
    lowered = clean_text(title).casefold()
    patterns = [
        "son dakika deprem mi oldu",
        "az önce deprem nerede oldu",
        "yakınımdaki depremler",
        "deprem mi oldu",
        "az önce deprem",
        "son depremler",
        "kandilli ve afad",
        "t. c.",
        "t.c.",
        "sulh hukuk",
        "satış memurluğu",
        "icra dairesi",
        "esas no",
        "karar no",
        "resmi ilan",
        "ilan.gov.tr",
        "burç yorum",
        "günlük burç",
    ]
    return any(pattern in lowered for pattern in patterns)


def looks_like_section_heading(value: str) -> bool:
    text = clean_text(value).strip(" :")
    if len(text) > 80:
        return False
    letters = [char for char in text if char.isalpha()]
    if len(letters) < 8:
        return False
    uppercase = sum(1 for char in letters if char.upper() == char and char.lower() != char)
    return uppercase / len(letters) > 0.82


def is_robotic_note(value: str) -> bool:
    lowered = clean_text(value).casefold()
    patterns = [
        "haber robotu",
        "robot",
        "otomasyon",
        "bu içerik gerçek haber akışına uygun",
        "editoryal panel",
        "json",
        "markdown",
        "yayın iskeleti",
        "metadata üret",
        "llms.txt",
        "yeni bilgi geldikçe",
        "haber metni güncellenerek",
        "zaman çizelgesi",
        "ilgili kurum açıklamaları",
        "haber akışında ayrıca takip",
        "metin güncel bilgilerle genişletilecek",
        "ayrıntılar okura sade bir akışla",
        "resmi açıklamalar, sahadaki bilgiler",
        "kişi, kurum ve zaman bilgileri",
        "gelişmenin tarafları",
        "olası yeni açıklamalar",
        "haber akışı genişletilecek",
        "yeni veri, açıklama veya karar",
        "gündemindeki bu gelişmede",
    ]
    return any(pattern in lowered for pattern in patterns)


def is_near_duplicate_sentence(candidate: str, existing: str) -> bool:
    first = {
        word
        for word in re.findall(r"[a-zçğıöşü0-9']{4,}", candidate.casefold())
        if word not in {"olan", "için", "daha", "sonra", "şekilde", "belirtti", "bildirdi"}
    }
    second = {
        word
        for word in re.findall(r"[a-zçğıöşü0-9']{4,}", existing.casefold())
        if word not in {"olan", "için", "daha", "sonra", "şekilde", "belirtti", "bildirdi"}
    }
    if len(first) < 5 or len(second) < 5:
        return False
    overlap = len(first & second) / max(1, min(len(first), len(second)))
    return overlap > 0.72


def join_sentences(sentences: list[str]) -> str:
    return " ".join(normalize_sentence(sentence) for sentence in sentences if sentence)


def dedupe_paragraphs(paragraphs: list[str]) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for paragraph in paragraphs:
        key = normalized_title(paragraph)
        if not key or key in seen:
            continue
        seen.add(key)
        results.append(paragraph)
    return results


def lower_first(value: str) -> str:
    text = clean_text(value)
    if not text:
        return text
    first_word = re.match(r"([A-ZÇĞİÖŞÜ][a-zçğıöşü]+(?:'[a-zçğıöşü]+)?)", text)
    lowerable = {
        "Ayrıntı",
        "Ayrıntılar",
        "Aktarılan",
        "Alınan",
        "Başlığa",
        "Bu",
        "Gelen",
        "Gelişme",
        "Gelişmede",
        "Gelişmenin",
        "Habere",
        "İlk",
        "Konu",
        "Olay",
        "Paylaşılan",
        "Süreç",
        "Süreçte",
        "Ünlü",
        "Yaşadıklarını",
        "Yeni",
    }
    if first_word and first_word.group(1).split("'", 1)[0] not in lowerable:
        return text
    return text[0].lower() + text[1:]


def clean_source_name(value: str) -> str:
    name = clean_text(value).replace(" RSS", "")
    return name or "kaynak"


def source_tag(value: str) -> str:
    name = clean_source_name(value)
    if not name:
        return ""
    return slugify(name).replace("-", " ")


def category_label(value: str) -> str:
    labels = {
        "son-dakika": "son dakika",
        "gundem": "gündem",
        "ekonomi": "ekonomi",
        "dunya": "dünya",
        "teknoloji": "teknoloji",
        "spor": "spor",
        "kultur": "kültür",
    }
    return labels.get(value, "gündem")


def category_context(value: str) -> str:
    contexts = {
        "son-dakika": "son dakika akışında",
        "gundem": "Türkiye gündeminde",
        "ekonomi": "ekonomi başlığında",
        "dunya": "dış haberler dosyasında",
        "teknoloji": "teknoloji gündeminde",
        "spor": "spor gündeminde",
        "kultur": "kültür sanat akışında",
        "dosya": "dosya bölümünde",
    }
    return contexts.get(str(value or ""), "Türkiye gündeminde")


def signature_for(item: dict[str, Any]) -> str:
    raw = "|".join([item.get("source", ""), item.get("title", ""), item.get("link", ""), item.get("published_at", "")])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalized_title(title: str) -> str:
    return re.sub(r"\W+", "", title.casefold())


def parse_date(raw: str | None) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc).astimezone()
    if not raw:
        return now.isoformat(timespec="seconds"), now
    value = raw.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        try:
            parsed = email.utils.parsedate_to_datetime(value)
        except Exception:
            parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone()
    if parsed > now + timedelta(minutes=5):
        parsed = now
    return parsed.isoformat(timespec="seconds"), parsed


def clean_description(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return clean_text(text)


def clean_text(value: str | None) -> str:
    text = repair_mojibake(value or "")
    text = text.replace("\xa0", " ")
    text = text.replace("“", '"').replace("”", '"').replace("’", "'")
    text = re.sub(r"(^|\s)\|+\s*", r"\1", text)
    text = re.sub(r"\b(\d{1,2})\.\s+(\d{2})\b", r"\1.\2", text)
    text = re.sub(r"\b(\d+),\s+(\d+)\b", r"\1,\2", text)
    text = re.sub(r"(?<=[.!?])(?=[A-ZÇĞİÖŞÜ])", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;])(?=\S)", r"\1 ", text)
    text = re.sub(r"\b(\d+),\s+(\d+)\b", r"\1,\2", text)
    text = repair_turkish_flow(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def repair_turkish_flow(value: str) -> str:
    text = str(value or "")
    flow_repairs = [
        (r"\bgündem gündeminde\b", "gündemde"),
        (r"\baBD\b", "ABD"),
        (r"\baKP\b", "AKP"),
        (r"\baYM\b", "AYM"),
        (r"\baFAD\b", "AFAD"),
        (r"dığı aktaran\b", "dığını aktaran"),
        (r"diği aktaran\b", "diğini aktaran"),
        (r"duğu aktaran\b", "duğunu aktaran"),
        (r"düğü aktaran\b", "düğünü aktaran"),
        (r"tığı aktaran\b", "tığını aktaran"),
        (r"tiği aktaran\b", "tiğini aktaran"),
        (r"tuğu aktaran\b", "tuğunu aktaran"),
        (r"tüğü aktaran\b", "tüğünü aktaran"),
        (r"\bolduğunu dikkat çekti\b", "olduğuna dikkat çekti"),
        (r"\bgerektiğini dikkat çekti\b", "gerektiğine dikkat çekti"),
        (r"\bIlkbahar\b", "İlkbahar"),
        (r"\bIstanbul\b", "İstanbul"),
        (r"\bIzmir\b", "İzmir"),
        (r"\bran'a\b", "İran'a"),
        (r"\bveklet sava\b", "vekâlet savaşı"),
        (r"\bHikye Armaan yarn\b", "Hikâye Armağanı yarın"),
        (r"\bSait Faik Hikye Armaan\b", "Sait Faik Hikâye Armağanı"),
    ]
    for pattern, replacement in flow_repairs:
        text = re.sub(pattern, replacement, text, flags=re.I)
    return text


def repair_mojibake(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if re.search(r"(?:[\u00c3\u00c4\u00c5][\u0080-\u00bfA-Za-z]|\u00e2[\u0080-\u00bf\u20ac]|\u00ef\u00bb\u00bf)", text):
        try:
            fixed = text.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
            if turkish_text_score(fixed) >= turkish_text_score(text):
                text = fixed
        except Exception:
            pass
    for bad, good in MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(bad, good)
    return text


def turkish_text_score(value: str) -> int:
    text = str(value or "")
    good = sum(text.count(char) for char in "çğıöşüÇĞİÖŞÜ")
    bad = sum(text.count(marker) for marker in ("Ã", "Ä", "Å", "â", "�"))
    return good - (bad * 4)


def has_encoding_damage(value: str) -> bool:
    text = str(value or "")
    if any(marker in text for marker in ("Ã", "Ä", "Å", "�")):
        return True
    if re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]\?[A-Za-zÇĞİÖŞÜçğıöşü]", text):
        return True
    if re.search(r"(^|\s)\?[A-Za-zÇĞİÖŞÜçğıöşü]", text):
        return True
    return bool(re.search(r"\b\w+\?\w+\b", text))


def uppercase_turkish_start(value: str) -> str:
    text = clean_text(value)
    if not text:
        return ""
    first = text[0]
    if first == "i":
        return "İ" + text[1:]
    return first.upper() + text[1:]


def normalize_sentence(value: str) -> str:
    text = clean_text(value)
    text = re.sub(r":\s*\.", ".", text)
    text = uppercase_turkish_start(text)
    if text and text[-1] not in ".!?":
        text += "."
    return text


def compact_summary(summary: str, title: str, max_chars: int = SUMMARY_SOFT_MAX_CHARS) -> str:
    text = clean_text(summary)
    if not text:
        return title
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    chosen: list[str] = []
    seen: set[str] = set()
    title_key = normalized_title(title)
    for sentence in sentences or [text]:
        key = normalized_title(sentence)
        if not key or key in seen:
            continue
        seen.add(key)
        if title_key and key == title_key:
            continue
        next_text = " ".join(chosen + [sentence])
        if len(next_text) > max_chars and chosen:
            break
        chosen.append(sentence)
        if len(" ".join(chosen)) >= max_chars:
            break
    compact = " ".join(chosen) or text
    if len(compact) > max_chars:
        bounded: list[str] = []
        for sentence in split_sentences(compact):
            next_text = " ".join(bounded + [sentence])
            if len(next_text) > max_chars and bounded:
                break
            if sentence_is_complete(sentence):
                bounded.append(sentence)
            if len(" ".join(bounded)) >= max_chars:
                break
        if bounded:
            compact = " ".join(bounded)
    return normalize_sentence(compact)


def map_category(value: str) -> str:
    slug = slugify(value)
    mapping = {
        "turkiye": "gundem",
        "gundem": "gundem",
        "son-dakika": "son-dakika",
        "ekonomi": "ekonomi",
        "dunya": "dunya",
        "spor": "spor",
        "teknoloji": "teknoloji",
        "bilim-teknoloji": "teknoloji",
        "bilim-teknoloji-haberleri": "teknoloji",
        "kultur-sanat": "kultur",
        "kultur": "kultur",
        "magazin": "kultur",
        "medya": "kultur",
        "yasam": "gundem",
        "saglik": "gundem",
        "egitim": "gundem",
        "politika": "gundem",
        "guncel": "gundem",
    }
    return mapping.get(slug, "gundem")


def main(argv: list[str] | None = None) -> int:
    defaults = load_runtime_defaults()
    parser = argparse.ArgumentParser(description="Turkiye Gundemi haber robotu.")
    parser.add_argument("--site", default="turkiye-gundemi")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-items", type=int)
    parser.add_argument("--status", choices=["draft", "published"])
    parser.add_argument("--publish-site", dest="publish_site", action="store_true")
    parser.add_argument("--no-publish-site", dest="publish_site", action="store_false")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int)
    parser.add_argument("--scan-only", action="store_true")
    parser.add_argument("--enrich-images", dest="enrich_images", action="store_true")
    parser.add_argument("--no-enrich-images", dest="enrich_images", action="store_false")
    parser.add_argument("--backfill-images", action="store_true")
    parser.add_argument("--force-images", action="store_true")
    parser.add_argument("--no-network-heal", action="store_true")
    parser.set_defaults(publish_site=None, enrich_images=None)
    args = parser.parse_args(argv)
    if args.scan_only:
        print(json.dumps(fetch_latest_news(limit=args.limit), ensure_ascii=False, indent=2))
        return 0
    if args.backfill_images:
        print(
            json.dumps(
                apply_related_visuals(
                    site_id=args.site,
                    force=args.force_images,
                    only_missing=not args.force_images,
                    publish_site=args.publish_site if args.publish_site is not None else False,
                    limit=args.max_items,
                )
                if not args.enrich_images
                else enrich_existing_articles(
                    site_id=args.site,
                    force=args.force_images,
                    only_missing=not args.force_images,
                    publish_site=args.publish_site if args.publish_site is not None else False,
                    limit=args.max_items,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.loop:
        return run_loop(
            site_id=args.site,
            limit=args.limit,
            max_items=args.max_items,
            status=args.status,
            publish_site=args.publish_site,
            enrich_images=args.enrich_images,
            heal_network=not args.no_network_heal,
            interval_seconds=args.interval_seconds or defaults["scan_interval_seconds"],
        )
    print(
        json.dumps(
            import_news(
                site_id=args.site,
                limit=args.limit,
                max_items=args.max_items,
                status=args.status,
                publish_site=args.publish_site,
                enrich_images=args.enrich_images,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
