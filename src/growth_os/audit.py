from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .config import ROOT, get_site, project_path


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/124 Safari/537.36 GrowthOS/0.1"
)


class HtmlSignals(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._in_title = False
        self.meta: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.scripts: list[dict[str, str]] = []
        self.images: list[dict[str, str]] = []
        self.headings: list[tuple[str, str]] = []
        self._open_heading: str | None = None
        self._heading_text: list[str] = []
        self.json_ld_blocks: list[str] = []
        self._script_type = ""
        self._script_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.lower(): value or "" for key, value in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            self.meta.append(attr)
        elif tag == "link":
            self.links.append(attr)
        elif tag == "script":
            self.scripts.append(attr)
            self._script_type = attr.get("type", "")
            self._script_text = []
        elif tag == "img":
            self.images.append(attr)
        elif tag in {"h1", "h2", "h3"}:
            self._open_heading = tag
            self._heading_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            if "ld+json" in self._script_type:
                self.json_ld_blocks.append("".join(self._script_text).strip())
            self._script_type = ""
            self._script_text = []
        elif self._open_heading == tag:
            text = " ".join(" ".join(self._heading_text).split())
            self.headings.append((tag, text))
            self._open_heading = None
            self._heading_text = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data.strip()
        if self._script_type:
            self._script_text.append(data)
        if self._open_heading:
            text = data.strip()
            if text:
                self._heading_text.append(text)

    def meta_content(self, key: str) -> str:
        key = key.lower()
        for item in self.meta:
            if item.get("name", "").lower() == key or item.get("property", "").lower() == key:
                return item.get("content", "")
        return ""


@dataclass
class PageAudit:
    url: str
    final_url: str
    status: int
    bytes: int
    elapsed_ms: int
    title_len: int
    description_len: int
    h1_count: int
    h2_count: int
    scripts: int
    blocking_scripts: int
    stylesheets: int
    images: int
    images_without_alt: int
    lazy_images: int
    json_ld_blocks: int
    json_ld_types: list[str]
    canonical: str
    amphtml: str
    cache_control: str
    cf_cache_status: str
    server: str
    external_domains: list[str]
    recommendations: list[str]


def fetch(url: str, accept: str = "text/html,application/xhtml+xml") -> tuple[str, int, dict[str, str], bytes, int]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": accept,
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
        },
    )
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=35) as response:
        body = response.read()
        elapsed = int((time.perf_counter() - start) * 1000)
        headers = {key.lower(): value for key, value in response.headers.items()}
        return response.geturl(), response.status, headers, body, elapsed


def absolute_domain(base: str, value: str) -> str:
    joined = urllib.parse.urljoin(base, value)
    return urllib.parse.urlparse(joined).netloc


def json_ld_types(blocks: list[str]) -> list[str]:
    found: list[str] = []
    for block in blocks:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                value = item.get("@type") or item.get("type")
                if isinstance(value, list):
                    found.extend(str(part) for part in value)
                elif value:
                    found.append(str(value))
    return found


def build_recommendations(
    signals: HtmlSignals,
    headers: dict[str, str],
    body: bytes,
    thresholds: dict[str, Any],
    page_kind: str,
) -> list[str]:
    recs: list[str] = []
    html_kb = len(body) / 1024
    budget_key = "article_html_kb" if page_kind == "article" else "homepage_html_kb"
    budget = int(thresholds.get(budget_key, 180))
    if html_kb > budget:
        recs.append(f"HTML boyutu {html_kb:.0f} KB; hedef {budget} KB altina indirilmeli.")
    blocking_scripts = sum(1 for script in signals.scripts if "async" not in script and "defer" not in script)
    max_blocking = int(thresholds.get("max_blocking_scripts", 10))
    if blocking_scripts > max_blocking:
        recs.append(f"{blocking_scripts} potansiyel bloklayici script var; hedef {max_blocking} veya alti.")
    if signals.title and len(signals.title) > 70:
        recs.append("Title uzun; mobil SERP icin 50-65 karakter araligina cekilmeli.")
    if not signals.meta_content("description"):
        recs.append("Meta description eksik.")
    elif len(signals.meta_content("description")) > 170:
        recs.append("Meta description uzun; 140-165 karakter bandi hedeflenmeli.")
    if sum(1 for tag, _ in signals.headings if tag == "h1") != 1:
        recs.append("Sayfada tam bir adet H1 olmali.")
    images_without_alt = sum(1 for image in signals.images if not image.get("alt"))
    if signals.images and images_without_alt / max(1, len(signals.images)) > 0.05:
        recs.append("Gorsellerde alt metin kapsami dusuk; haber gorselleri icin aciklayici alt metin uretin.")
    if "no-store" in headers.get("cache-control", "").lower():
        recs.append("Cache-Control icinde no-store var; haber ana sayfasi icin edge cache ile tarayici cache ayrilmali.")
    if page_kind == "article" and "NewsArticle" not in json_ld_types(signals.json_ld_blocks) and "Article" not in json_ld_types(signals.json_ld_blocks):
        recs.append("Article/NewsArticle JSON-LD bulunmuyor.")
    return recs


def audit_page(url: str, thresholds: dict[str, Any] | None = None, page_kind: str = "homepage") -> PageAudit:
    thresholds = thresholds or {}
    final_url, status, headers, body, elapsed = fetch(url)
    html = body.decode("utf-8", "replace")
    signals = HtmlSignals()
    signals.feed(html)
    canonical = next((item.get("href", "") for item in signals.links if item.get("rel", "").lower() == "canonical"), "")
    amphtml = next((item.get("href", "") for item in signals.links if item.get("rel", "").lower() == "amphtml"), "")
    stylesheets = [item for item in signals.links if "stylesheet" in item.get("rel", "").lower()]
    external_domains = sorted(
        {
            absolute_domain(final_url, item.get("src") or item.get("href") or "")
            for item in [*signals.scripts, *signals.images, *stylesheets]
            if item.get("src") or item.get("href")
        }
    )
    external_domains = [domain for domain in external_domains if domain]
    blocking_scripts = sum(1 for script in signals.scripts if "async" not in script and "defer" not in script)
    return PageAudit(
        url=url,
        final_url=final_url,
        status=status,
        bytes=len(body),
        elapsed_ms=elapsed,
        title_len=len(signals.title),
        description_len=len(signals.meta_content("description")),
        h1_count=sum(1 for tag, _ in signals.headings if tag == "h1"),
        h2_count=sum(1 for tag, _ in signals.headings if tag == "h2"),
        scripts=len(signals.scripts),
        blocking_scripts=blocking_scripts,
        stylesheets=len(stylesheets),
        images=len(signals.images),
        images_without_alt=sum(1 for image in signals.images if not image.get("alt")),
        lazy_images=sum(1 for image in signals.images if image.get("loading") == "lazy"),
        json_ld_blocks=len(signals.json_ld_blocks),
        json_ld_types=json_ld_types(signals.json_ld_blocks),
        canonical=canonical,
        amphtml=amphtml,
        cache_control=headers.get("cache-control", ""),
        cf_cache_status=headers.get("cf-cache-status", ""),
        server=headers.get("server", ""),
        external_domains=external_domains,
        recommendations=build_recommendations(signals, headers, body, thresholds, page_kind),
    )


def count_sitemap_urls(url: str) -> dict[str, Any]:
    try:
        final_url, status, headers, body, elapsed = fetch(url, accept="application/xml,text/xml,*/*")
    except (urllib.error.URLError, TimeoutError) as exc:
        return {"url": url, "error": str(exc)}
    text = body.decode("utf-8", "replace")
    loc_count = len(re.findall(r"<loc>", text, re.IGNORECASE))
    sitemap_count = len(re.findall(r"<sitemap>", text, re.IGNORECASE))
    latest = re.findall(r"<lastmod>(.*?)</lastmod>", text, re.IGNORECASE)
    return {
        "url": url,
        "final_url": final_url,
        "status": status,
        "bytes": len(body),
        "elapsed_ms": elapsed,
        "loc_count": loc_count,
        "sitemap_count": sitemap_count,
        "latest_lastmod": latest[:3],
    }


def first_article_from_sitemap(url: str) -> str:
    try:
        _, _, _, body, _ = fetch(url, accept="application/xml,text/xml,*/*")
    except (urllib.error.URLError, TimeoutError):
        return ""
    text = body.decode("utf-8", "replace")
    for match in re.findall(r"<loc>(.*?)</loc>", text, re.IGNORECASE):
        if "/haber/" in match or "/foto-galeri/" in match:
            return match.strip()
    return ""


def audit_site(site_id: str) -> dict[str, Any]:
    site = get_site(site_id)
    base = site["base_url"].rstrip("/") + "/"
    article_url = first_article_from_sitemap(site.get("sitemaps", [""])[0]) if site.get("sitemaps") else ""
    result: dict[str, Any] = {
        "site": {"id": site_id, "name": site["name"], "base_url": site["base_url"]},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "homepage": asdict(audit_page(base, site.get("thresholds", {}))),
        "sample_article": asdict(audit_page(article_url, site.get("thresholds", {}), "article")) if article_url else None,
        "sitemaps": [count_sitemap_urls(url) for url in site.get("sitemaps", [])],
        "competitors": [],
    }
    for competitor in site.get("competitors", [])[:5]:
        try:
            result["competitors"].append(asdict(audit_page(competitor.rstrip("/") + "/", site.get("thresholds", {}))))
        except Exception as exc:  # noqa: BLE001 - audit should keep going
            result["competitors"].append({"url": competitor, "error": str(exc)})
    return result


def print_summary(data: dict[str, Any]) -> None:
    home = data["homepage"]
    article = data.get("sample_article")
    print(f"{data['site']['name']} audit")
    print(f"- URL: {home['final_url']}")
    print(f"- HTML: {home['bytes'] / 1024:.0f} KB, scripts: {home['scripts']} ({home['blocking_scripts']} blocking-ish), images: {home['images']}")
    print(f"- Cache: {home['cache_control']} / CF: {home['cf_cache_status']}")
    print(f"- JSON-LD: {home['json_ld_types']}")
    if home["recommendations"]:
        print("- Oneriler:")
        for rec in home["recommendations"]:
            print(f"  - {rec}")
    if article:
        print(f"- Ornek makale: {article['bytes'] / 1024:.0f} KB, scripts: {article['scripts']} ({article['blocking_scripts']} blocking-ish), JSON-LD: {article['json_ld_types']}")
        if article["recommendations"]:
            print("- Makale onerileri:")
            for rec in article["recommendations"]:
                print(f"  - {rec}")
    print("- Sitemap:")
    for item in data["sitemaps"]:
        print(f"  - {item.get('url')}: loc={item.get('loc_count')} sitemap={item.get('sitemap_count')} bytes={item.get('bytes')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a configured news portal.")
    parser.add_argument("--site", default="medyafaresi", help="Site id from config/sites.json")
    parser.add_argument("--write", help="Directory to write JSON report")
    parser.add_argument("--json", action="store_true", help="Print full JSON")
    args = parser.parse_args(argv)

    data = audit_site(args.site)
    if args.write:
        out_dir = project_path(args.write)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{args.site}-audit.json"
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report written: {out_path}")
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print_summary(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
