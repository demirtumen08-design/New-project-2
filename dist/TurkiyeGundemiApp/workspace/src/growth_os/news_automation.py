from __future__ import annotations

import argparse
import email.utils
import hashlib
import html
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .config import ROOT, project_path
from .content_store import load_articles, now_iso, slugify, upsert_article
from .image_enrichment import enrich_article_image, enrich_existing_articles
from .runtime_network import heal_network_runtime
from .sitegen import generate as generate_site


USER_AGENT = "Mozilla/5.0 (compatible; TurkiyeGundemiBot/1.0; +https://turkiyegundemi.com)"
SOURCE_CONFIG = ROOT / "config" / "news_sources.json"
STATE_PATH = ROOT / "content" / "turkiye-gundemi" / "news_automation_state.json"
ARTICLE_FETCH_TIMEOUT = 12
MAX_ARTICLE_FACTS = 9
MIN_PUBLIC_BODY_CHARS = 520
MIN_PUBLIC_PARAGRAPHS = 3
NEWSROOM_AUTHOR = "Türkiye Gündemi Haber Merkezi"

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
        "limit": clamp_int(raw.get("limit", 18), 18, 1, 50),
        "max_import_per_cycle": clamp_int(raw.get("max_import_per_cycle", 3), 3, 1, 20),
        "status": status,
        "publish_site_after_import": bool(raw.get("publish_site_after_import", False)),
        "image_enrichment": bool(raw.get("image_enrichment", True)),
        "scan_interval_seconds": clamp_int(raw.get("scan_interval_seconds", 900), 900, 60, 86_400),
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
    data["imported_signatures"] = [str(item).strip() for item in imported if str(item).strip()][-1_000:]
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
    limit = clamp_int(limit if limit is not None else defaults["limit"], defaults["limit"], 1, 50)

    for source in sources:
        cooldown_remaining = source_cooldown_remaining(source, state, defaults, now)
        if cooldown_remaining:
            status.append(
                {
                    "source": source.get("name", "Kaynak"),
                    "status": "cooldown",
                    "message": f"Kaynak gecici olarak beklemede, {cooldown_remaining} saniye sonra yeniden denenecek",
                    "retry_in_seconds": cooldown_remaining,
                }
            )
            continue
        try:
            fetched = fetch_feed(source)
            items.extend(fetched)
            clear_source_failure(source, state)
            status.append({"source": source["name"], "status": "ok", "message": f"{len(fetched)} haber alındı"})
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

    deduped = dedupe_items(items)
    deduped.sort(key=lambda item: item["published_sort"], reverse=True)
    selected = deduped[:limit]
    for index, item in enumerate(selected, start=1):
        item["details"] = fetch_article_details(item.get("link", ""))
        item["rank"] = index
        item["variants"] = build_variants(item)
        item["published_sort"] = item["published_sort"].isoformat()
    return {
        "ok": True,
        "generated_at": now_iso(),
        "source_status": status,
        "items": selected,
        "live_item_count": len(deduped),
        "state": state,
    }


def fetch_feed(source: dict[str, Any]) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        str(source["url"]),
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = response.read()

    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return parse_loose_rss(payload, source)
    if root.tag.endswith("rss"):
        return parse_rss(root, source)
    if root.tag.endswith("feed"):
        return parse_atom(root, source)
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
        results.append(make_item(source, title, link, summary, raw_category, published_at, published_sort))
    return [item for item in results if item]


def loose_tag_value(block: str, tag: str) -> str:
    match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", block, flags=re.I | re.S)
    if not match:
        return ""
    value = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", match.group(1), flags=re.S)
    return clean_description(value)


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
        results.append(make_item(source, title, link, summary, raw_category, published_at, published_sort))
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
        results.append(make_item(source, title, link, summary, raw_category, published_at, published_sort))
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
) -> dict[str, Any] | None:
    if not title or not link:
        return None
    if is_rejected_title(title):
        return None
    category = infer_category(raw_category, str(source.get("category", "")), link)
    item = {
        "source": source["name"],
        "source_url": source["url"],
        "category": category,
        "raw_category": raw_category,
        "title": title,
        "link": link,
        "summary": summary or title,
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


def dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        key = item.get("link") or normalized_title(item.get("title", ""))
        key = hashlib.sha256(key.encode("utf-8")).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


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

    meta_description = extract_meta_description(page)
    jsonld_text = extract_jsonld_article_text(page)
    parser = ArticleTextParser(final_url)
    try:
        parser.feed(page)
    except Exception:
        pass
    candidates = [meta_description, jsonld_text, *parser.paragraphs]
    return {
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
    title = clean_text(item["title"]).strip()
    facts = article_facts(item)
    summary = make_spot(title, facts, item.get("summary", ""))
    category = category_label(item.get("category", "gundem"))
    neutral = f"{title} konusunda son bilgiler netleşti. {summary}"
    flow = f"{category.capitalize()} başlığında takip edilen gelişmede {summary}"
    spot = summary if summary != title else f"{title} gelişmesine ilişkin ayrıntılar netleşiyor."
    return {
        "spot": normalize_sentence(spot),
        "neutral": normalize_sentence(neutral),
        "flow": normalize_sentence(flow),
    }


def item_to_article(item: dict[str, Any], status: str = "draft") -> dict[str, Any]:
    facts = article_facts(item)
    title = clean_text(item["title"])
    summary = normalize_sentence(item.get("variants", {}).get("spot") or make_spot(title, facts, item.get("summary", "")))
    body = compose_news_body(item, facts)
    requested_status = status if status in {"draft", "published"} else "draft"
    article_status = requested_status
    if requested_status == "published" and not is_publishable_article(title, summary, body):
        article_status = "draft"
    return {
        "slug": slugify(title),
        "category": item.get("category") or "gundem",
        "title": title,
        "summary": summary,
        "body": body,
        "author": NEWSROOM_AUTHOR,
        "published_at": item.get("published_at") or now_iso(),
        "modified_at": now_iso(),
        "image": "/assets/images/ankara.png",
        "image_alt": title,
        "tags": [tag for tag in [item.get("source", ""), item.get("category", ""), source_tag(item.get("source", ""))] if tag],
        "status": article_status,
        "source_name": item.get("source", ""),
        "source_url": item.get("link", ""),
        "source_feed": item.get("source_url", ""),
        "source_published_at": item.get("published_at", ""),
        "automation_signature": item.get("signature", signature_for(item)),
        "imported_at": now_iso(),
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
    resolved_limit = clamp_int(limit if limit is not None else defaults["limit"], defaults["limit"], 1, 50)
    resolved_max_items = clamp_int(
        max_items if max_items is not None else defaults["max_import_per_cycle"],
        defaults["max_import_per_cycle"],
        1,
        20,
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

    imported = []
    skipped = []
    for item in payload["items"]:
        if len(imported) >= resolved_max_items:
            break
        sig = item.get("signature", "")
        if sig in known or item.get("link") in known:
            skipped.append({"title": item["title"], "reason": "zaten var"})
            continue
        article = upsert_article(site_id, item_to_article(item, status=resolved_status))
        if resolved_enrich_images:
            image_result = enrich_article_image(site_id, article, force=False)
            article = image_result["article"]
            if image_result.get("updated"):
                article = upsert_article(site_id, article)
        imported.append(article)
        known.add(sig)
        known.add(item.get("link", ""))

    state["imported_signatures"] = sorted(known)[-1000:]
    state["last_import_at"] = now_iso()
    state["last_source_status"] = payload.get("source_status", [])
    state["last_cycle"] = {
        "site_id": site_id,
        "limit": resolved_limit,
        "max_items": resolved_max_items,
        "status": resolved_status,
        "publish_site": resolved_publish_site,
        "enrich_images": resolved_enrich_images,
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


def make_spot(title: str, facts: list[str], fallback: str = "") -> str:
    source_text = " ".join(facts[:2]) or fallback or title
    spot = compact_summary(source_text, title, max_chars=340)
    if normalized_title(spot) == normalized_title(title):
        return normalize_sentence(f"{title} başlığına ilişkin ilk bilgiler kamuoyuna yansıdı")
    return normalize_sentence(spot)


def compose_news_body(item: dict[str, Any], facts: list[str]) -> list[str]:
    title = clean_text(item["title"]).strip()
    category = category_label(item.get("category", "gundem"))
    facts = editorial_fact_pack(facts, title)
    if not facts:
        facts = editorial_fact_pack([item.get("summary") or title], title)

    body: list[str] = []
    first_chunk_size = 2 if len(facts) > 1 and len(facts[0]) < 145 else 1
    chunks = [facts[:first_chunk_size]]
    rest = facts[first_chunk_size:]
    while rest:
        chunks.append(rest[:2])
        rest = rest[2:]

    for chunk in chunks[:5]:
        paragraph = normalize_sentence(join_sentences(chunk))
        if paragraph:
            body.append(paragraph)

    if len(body) < MIN_PUBLIC_PARAGRAPHS:
        body.append(context_paragraph(category))

    return [paragraph for paragraph in dedupe_paragraphs(body) if paragraph]


def editorial_fact_pack(facts: list[str], title: str) -> list[str]:
    packed: list[str] = []
    seen: set[str] = set()
    title_key = normalized_title(title)
    for fact in facts:
        sentence = refine_fact_sentence(fact)
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


def context_paragraph(category: str) -> str:
    label = category_label(category)
    return normalize_sentence(
        f"Konu {label} başlığında izlenirken, olayın seyri ve resmi açıklamalar geldikçe ayrıntılar netleşecek"
    )


def is_publishable_article(title: str, summary: str, body: list[str]) -> bool:
    if is_rejected_title(title):
        return False
    full_text = clean_text(" ".join([summary, *body]))
    if has_encoding_damage(full_text):
        return False
    if len(body) < MIN_PUBLIC_PARAGRAPHS:
        return False
    if len(clean_text(" ".join(body))) < MIN_PUBLIC_BODY_CHARS:
        return False
    if any(is_robotic_note(paragraph) for paragraph in body):
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
    raw_parts = re.split(r"(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜ])", text)
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
    if len(value) > 520:
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


def signature_for(item: dict[str, Any]) -> str:
    raw = "|".join([item.get("source", ""), item.get("title", ""), item.get("link", ""), item.get("published_at", "")])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalized_title(title: str) -> str:
    return re.sub(r"\W+", "", title.casefold())


def parse_date(raw: str | None) -> tuple[str, datetime]:
    if not raw:
        now = datetime.now(timezone.utc).astimezone()
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
    return parsed.isoformat(timespec="seconds"), parsed


def clean_description(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return clean_text(text)


def clean_text(value: str | None) -> str:
    text = repair_mojibake(value or "")
    text = text.replace("\xa0", " ")
    text = text.replace("“", '"').replace("”", '"').replace("’", "'")
    text = re.sub(r"\b(\d{1,2})\.\s+(\d{2})\b", r"\1.\2", text)
    text = re.sub(r"(?<=[.!?])(?=[A-ZÇĞİÖŞÜ])", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;])(?=\S)", r"\1 ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def repair_mojibake(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if any(marker in text for marker in ("Ã", "Ä", "Å", "â", "ï»¿")):
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
    return bool(re.search(r"\b\w+\?\w+\b", text))


def normalize_sentence(value: str) -> str:
    text = clean_text(value)
    text = re.sub(r":\s*\.", ".", text)
    if text and text[-1] not in ".!?":
        text += "."
    return text


def compact_summary(summary: str, title: str, max_chars: int = 260) -> str:
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
        compact = compact[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."
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
                enrich_existing_articles(
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
