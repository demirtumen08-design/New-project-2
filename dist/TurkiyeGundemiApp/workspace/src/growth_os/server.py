from __future__ import annotations

import argparse
import base64
import hmac
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .audit import audit_site
from .config import ROOT, get_site, load_config, project_path, save_config
from .content_store import delete_article, load_articles, slugify, upsert_article
from .dnsgen import generate as generate_dns
from .image_enrichment import enrich_existing_articles
from .news_automation import fetch_latest_news, import_news
from .runtime_network import heal_network_runtime, runtime_status
from .autonomous_daemon import run_cycle as run_autonomous_cycle
from .sitegen import generate as generate_site


class GrowthHandler(BaseHTTPRequestHandler):
    server_version = "GrowthOS/0.1"

    def site_at_root(self) -> bool:
        return bool(getattr(self.server, "site_at_root", False))

    def protected_path(self, path: str) -> bool:
        if path.startswith("/api/") or path == "/admin":
            return True
        return path == "/" and not self.site_at_root()

    def require_auth(self, path: str) -> bool:
        password = os.environ.get("GROWTH_OS_ADMIN_PASSWORD", "")
        if not password or not self.protected_path(path):
            return True
        header = self.headers.get("Authorization", "")
        prefix = "Basic "
        if not header.startswith(prefix):
            self.auth_challenge()
            return False
        try:
            decoded = base64.b64decode(header[len(prefix) :], validate=True).decode("utf-8")
            username, supplied = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError):
            self.auth_challenge()
            return False
        expected_user = os.environ.get("GROWTH_OS_ADMIN_USER", "admin")
        if hmac.compare_digest(username, expected_user) and hmac.compare_digest(supplied, password):
            return True
        self.auth_challenge()
        return False

    def auth_challenge(self) -> None:
        body = b"Authentication required"
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Growth OS Admin"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.write_body(body)

    def write_body(self, data: bytes) -> None:
        if self.command != "HEAD":
            self.wfile.write(data)

    def send_text(self, body: str, status: int = 200, content_type: str = "text/html; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.write_body(data)

    def send_file(self, path: Path) -> None:
        resolved = path.resolve()
        if not resolved.exists() or not resolved.is_file():
            self.send_text("Not found", 404, "text/plain; charset=utf-8")
            return
        data = resolved.read_bytes()
        content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=60")
        self.end_headers()
        self.write_body(data)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if not self.require_auth(path):
            return
        if path == "/healthz":
            self.send_text("ok", content_type="text/plain; charset=utf-8")
            return
        if path == "/":
            if self.site_at_root():
                self.send_public_file("")
                return
            self.send_text(render_dashboard())
            return
        if path == "/admin":
            self.send_text(render_admin())
            return
        if path == "/api/sites":
            self.send_text(json.dumps(load_config(), ensure_ascii=False), content_type="application/json; charset=utf-8")
            return
        if path == "/api/articles":
            site = parse_qs(parsed.query).get("site", ["turkiye-gundemi"])[0]
            self.send_text(json.dumps(load_articles(site), ensure_ascii=False, indent=2), content_type="application/json; charset=utf-8")
            return
        if path == "/api/site-config":
            site_id = parse_qs(parsed.query).get("site", ["turkiye-gundemi"])[0]
            self.send_text(json.dumps(get_site(site_id), ensure_ascii=False, indent=2), content_type="application/json; charset=utf-8")
            return
        if path == "/api/audit":
            site = parse_qs(parsed.query).get("site", ["medyafaresi"])[0]
            try:
                payload = audit_site(site)
            except Exception as exc:  # noqa: BLE001 - API should return readable error
                self.send_text(json.dumps({"error": str(exc)}, ensure_ascii=False), 500, "application/json; charset=utf-8")
                return
            self.send_text(json.dumps(payload, ensure_ascii=False, indent=2), content_type="application/json; charset=utf-8")
            return
        if path == "/api/news-scan":
            limit = int(parse_qs(parsed.query).get("limit", ["18"])[0] or "18")
            try:
                payload = fetch_latest_news(limit=limit)
            except Exception as exc:  # noqa: BLE001 - admin should see source error
                self.send_text(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), 500, "application/json; charset=utf-8")
                return
            self.send_text(json.dumps(payload, ensure_ascii=False, indent=2), content_type="application/json; charset=utf-8")
            return
        if path == "/api/runtime-network":
            try:
                payload = runtime_status()
            except Exception as exc:  # noqa: BLE001 - admin should see network error
                self.send_text(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), 500, "application/json; charset=utf-8")
                return
            self.send_text(json.dumps(payload, ensure_ascii=False, indent=2), content_type="application/json; charset=utf-8")
            return
        if path.startswith("/turkiye-gundemi"):
            relative = path.removeprefix("/turkiye-gundemi").strip("/")
            self.send_public_file(relative)
            return
        relative = path.strip("/")
        public_dir = project_path(get_site("turkiye-gundemi")["public_dir"]).resolve()
        target = (public_dir / relative).resolve()
        if target.exists() or (target / "index.html").exists():
            self.send_public_file(relative)
            return
        self.send_text("Not found", 404, "text/plain; charset=utf-8")

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler API
        self.do_GET()

    def send_public_file(self, relative: str) -> None:
        public_dir = project_path(get_site("turkiye-gundemi")["public_dir"]).resolve()
        target = (public_dir / relative).resolve()
        if not relative or relative.endswith("/") or target.is_dir():
            target = (target / "index.html").resolve()
        if public_dir != target and public_dir not in target.parents:
            self.send_text("Not found", 404, "text/plain; charset=utf-8")
            return
        self.send_file(target)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if not self.require_auth(path):
            return
        try:
            payload = self.read_json()
            if path == "/api/articles":
                site = payload.pop("site", "turkiye-gundemi")
                article = upsert_article(site, payload)
                self.send_text(json.dumps({"ok": True, "article": article}, ensure_ascii=False), content_type="application/json; charset=utf-8")
                return
            if path == "/api/delete-article":
                site = payload.get("site", "turkiye-gundemi")
                deleted = delete_article(site, str(payload.get("slug", "")))
                self.send_text(json.dumps({"ok": deleted}, ensure_ascii=False), content_type="application/json; charset=utf-8")
                return
            if path == "/api/publish":
                site = payload.get("site", "turkiye-gundemi")
                out = generate_site(site)
                self.send_text(json.dumps({"ok": True, "public_dir": str(out)}, ensure_ascii=False), content_type="application/json; charset=utf-8")
                return
            if path == "/api/dns-generate":
                site = payload.get("site", "turkiye-gundemi")
                primary_ip = str(payload.get("primary_ip", "")).strip()
                secondary_ip = str(payload.get("secondary_ip", "")).strip() or None
                out = generate_dns(site, primary_ip, secondary_ip)
                self.send_text(json.dumps({"ok": True, "dns_dir": str(out)}, ensure_ascii=False), content_type="application/json; charset=utf-8")
                return
            if path == "/api/site-config":
                update_site_config(payload)
                self.send_text(json.dumps({"ok": True}, ensure_ascii=False), content_type="application/json; charset=utf-8")
                return
            if path == "/api/news-import":
                out = import_news(
                    site_id=payload.get("site", "turkiye-gundemi"),
                    limit=int(payload.get("limit", 18)),
                    max_items=int(payload.get("max_items", 3)),
                    status=str(payload.get("status", "draft")),
                    publish_site=bool(payload.get("publish_site", False)),
                    enrich_images=bool(payload.get("enrich_images", False)),
                )
                self.send_text(json.dumps(out, ensure_ascii=False, indent=2), content_type="application/json; charset=utf-8")
                return
            if path == "/api/enrich-images":
                out = enrich_existing_articles(
                    site_id=payload.get("site", "turkiye-gundemi"),
                    force=bool(payload.get("force", False)),
                    only_missing=not bool(payload.get("force", False)),
                    publish_site=bool(payload.get("publish_site", False)),
                    limit=int(payload.get("limit", 0) or 0) or None,
                )
                self.send_text(json.dumps(out, ensure_ascii=False, indent=2), content_type="application/json; charset=utf-8")
                return
            if path == "/api/network-heal":
                out = heal_network_runtime(
                    site_id=payload.get("site", "turkiye-gundemi"),
                    apply_config=bool(payload.get("apply_config", True)),
                    publish_site=bool(payload.get("publish_site", False)),
                    generate_dns_files=bool(payload.get("generate_dns", True)),
                    prefer_public_ip=None if payload.get("prefer_public_ip") is None else bool(payload.get("prefer_public_ip")),
                )
                self.send_text(json.dumps(out, ensure_ascii=False, indent=2), content_type="application/json; charset=utf-8")
                return
            if path == "/api/autonomous-cycle":
                out = run_autonomous_cycle(
                    site_id=payload.get("site", "turkiye-gundemi"),
                    limit=int(payload.get("limit", 18)),
                    max_items=int(payload.get("max_items", 3)),
                    status=str(payload.get("status", "published")),
                    publish_site=bool(payload.get("publish_site", True)),
                    enrich_images=bool(payload.get("enrich_images", True)),
                    heal_network=bool(payload.get("heal_network", True)),
                    prefer_public_ip=None if payload.get("prefer_public_ip") is None else bool(payload.get("prefer_public_ip")),
                )
                self.send_text(json.dumps(out, ensure_ascii=False, indent=2), content_type="application/json; charset=utf-8")
                return
        except Exception as exc:  # noqa: BLE001 - API response should expose actionable error
            self.send_text(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), 400, "application/json; charset=utf-8")
            return
        self.send_text("Not found", 404, "text/plain; charset=utf-8")

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def update_site_config(payload: dict) -> None:
    site_id = payload.get("site", "turkiye-gundemi")
    config = load_config()
    site = config["sites"][site_id]
    for key in ("name", "domain", "base_url"):
        if key in payload:
            site[key] = str(payload[key]).strip()
    if "theme" in payload and isinstance(payload["theme"], dict):
        site.setdefault("theme", {}).update({key: str(value).strip() for key, value in payload["theme"].items()})
    if "categories" in payload:
        categories = []
        seen_slugs: set[str] = set()
        raw = payload["categories"]
        if isinstance(raw, str):
            lines = [line.strip() for line in raw.splitlines() if line.strip()]
            for line in lines:
                if "|" in line:
                    slug, name = [part.strip() for part in line.split("|", 1)]
                else:
                    name = line
                    slug = line
                normalized_slug = slugify(slug or name)
                if not name or normalized_slug in seen_slugs:
                    continue
                seen_slugs.add(normalized_slug)
                categories.append({"slug": normalized_slug, "name": name})
        elif isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or item.get("slug") or "").strip()
                normalized_slug = slugify(str(item.get("slug") or name).strip())
                if not name or normalized_slug in seen_slugs:
                    continue
                seen_slugs.add(normalized_slug)
                categories.append({"slug": normalized_slug, "name": name})
        if categories:
            site["categories"] = categories
    save_config(config)


def render_dashboard() -> str:
    docs = (ROOT / "docs" / "medyafaresi-audit.md").as_posix()
    return f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Medyafaresi Growth OS</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: #171717; background: #f7f7f8; }}
    header {{ padding: 24px max(20px, calc((100vw - 1120px) / 2)); background: #111827; color: white; }}
    h1 {{ margin: 0; font-size: 32px; letter-spacing: 0; }}
    main {{ width: min(1120px, calc(100vw - 32px)); margin: 24px auto; display: grid; gap: 18px; grid-template-columns: 1fr 1fr; }}
    section {{ background: white; border: 1px solid #d0d5dd; border-radius: 8px; padding: 18px; }}
    h2 {{ margin: 0 0 10px; font-size: 20px; }}
    p {{ color: #475467; }}
    a, button {{ color: #0f4c81; font-weight: 700; }}
    button {{ border: 1px solid #0f4c81; background: white; border-radius: 6px; padding: 10px 12px; cursor: pointer; }}
    pre {{ white-space: pre-wrap; background: #101828; color: #e4e7ec; border-radius: 8px; padding: 14px; max-height: 460px; overflow: auto; grid-column: 1 / -1; }}
    @media (max-width: 800px) {{ main {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header>
    <h1>Medyafaresi Growth OS</h1>
    <p>Teknik audit, site uretimi ve self-hosted yayin altyapisi icin yerel kontrol paneli.</p>
  </header>
  <main>
    <section>
      <h2>Yonetim Paneli</h2>
      <p>Turkiye Gundemi haberlerini, site ayarlarini ve yayinlamayi buradan yonetin.</p>
      <a href="/admin">Admin panelini ac</a>
    </section>
    <section>
      <h2>Medyafaresi Audit</h2>
      <p>Canli sayfa, sitemap, cache, schema ve rakip sinyallerini olcer.</p>
      <button onclick="runAudit('medyafaresi')">Audit calistir</button>
    </section>
    <section>
      <h2>Turkiye Gundemi</h2>
      <p>Duzenlenebilir icerikten uretilmis statik siteyi ac.</p>
      <a href="/turkiye-gundemi/">Siteyi ac</a>
    </section>
    <section>
      <h2>Dokuman</h2>
      <p>Yerel audit ve yol haritasi dosyasi: {docs}</p>
    </section>
    <section>
      <h2>API</h2>
      <p><code>/api/audit?site=medyafaresi</code> ve <code>/api/sites</code> endpointleri hazir.</p>
    </section>
    <pre id="out">Hazir.</pre>
  </main>
  <script>
    async function runAudit(site) {{
      const out = document.getElementById('out');
      out.textContent = 'Audit calisiyor...';
      const res = await fetch('/api/audit?site=' + encodeURIComponent(site));
      out.textContent = JSON.stringify(await res.json(), null, 2);
    }}
  </script>
</body>
</html>"""


def render_admin() -> str:
    return """<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Turkiye Gundemi Admin</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: Arial, Helvetica, sans-serif; color: #171717; background: #f5f6f8; }
    header { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 18px max(20px, calc((100vw - 1280px) / 2)); background: #0f172a; color: #fff; }
    h1, h2 { margin: 0; letter-spacing: 0; }
    main { width: min(1280px, calc(100vw - 28px)); margin: 18px auto 32px; display: grid; grid-template-columns: 330px 1fr; gap: 16px; }
    section, aside { background: #fff; border: 1px solid #d0d5dd; border-radius: 8px; padding: 16px; }
    label { display: block; font-size: 13px; font-weight: 700; margin: 12px 0 5px; color: #344054; }
    input, textarea, select { width: 100%; border: 1px solid #c7ced8; border-radius: 6px; padding: 10px; font: inherit; }
    textarea { min-height: 120px; resize: vertical; }
    button, .link-button { border: 1px solid #0f4c81; background: #0f4c81; color: #fff; border-radius: 6px; padding: 9px 12px; font-weight: 700; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; justify-content: center; }
    button.secondary { background: #fff; color: #0f4c81; }
    button.danger { background: #b42318; border-color: #b42318; }
    .row { display: flex; gap: 8px; flex-wrap: wrap; }
    .row > * { flex: 1; }
    .article-list { list-style: none; padding: 0; margin: 12px 0 0; display: grid; gap: 8px; }
    .article-list button { width: 100%; text-align: left; justify-content: flex-start; background: #fff; color: #171717; border-color: #d0d5dd; }
    .badge { display: inline-flex; align-items: center; border: 1px solid #d0d5dd; border-radius: 999px; padding: 2px 8px; font-size: 12px; color: #344054; background: #fff; }
    .badge.draft { color: #92400e; border-color: #f5c542; background: #fffbeb; }
    .muted { color: #667085; font-size: 13px; }
    .tabs { display: flex; gap: 8px; margin-bottom: 14px; }
    .tabs button { background: #fff; color: #0f4c81; }
    .tabs button.active { background: #0f4c81; color: #fff; }
    .hidden { display: none; }
    .news-results { display: grid; gap: 10px; margin-top: 14px; }
    .news-card { border: 1px solid #d0d5dd; border-radius: 8px; padding: 12px; background: #f8fafc; }
    .news-card h3 { margin: 6px 0; font-size: 17px; }
    pre { white-space: pre-wrap; background: #101828; color: #e4e7ec; border-radius: 8px; padding: 12px; max-height: 220px; overflow: auto; }
    @media (max-width: 900px) { main { grid-template-columns: 1fr; } header { align-items: flex-start; flex-direction: column; } }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Türkiye Gündemi Admin</h1>
      <div class="muted">Haberleri ve site ayarlarını düzenleyip statik siteye yayınlayın.</div>
    </div>
    <div class="row">
      <a class="link-button" href="/turkiye-gundemi/" target="_blank">Siteyi ac</a>
      <button onclick="publishSite()">Yayinla</button>
    </div>
  </header>
  <main>
    <aside>
      <div class="row">
        <button onclick="newArticle()">Yeni Haber</button>
        <button class="secondary" onclick="loadAll()">Yenile</button>
      </div>
      <ul id="articleList" class="article-list"></ul>
    </aside>
    <section>
      <div class="tabs">
        <button id="tabArticle" class="active" onclick="showTab('article')">Haber</button>
        <button id="tabNews" onclick="showTab('news')">Haber Robotu</button>
        <button id="tabSettings" onclick="showTab('settings')">Site Ayarları</button>
        <button id="tabDns" onclick="showTab('dns')">DNS</button>
        <button id="tabOutput" onclick="showTab('output')">Cikti</button>
      </div>
      <form id="articleForm" onsubmit="saveArticle(event)">
        <div class="row">
          <div><label>Baslik</label><input id="title" required></div>
          <div><label>Slug</label><input id="slug"></div>
        </div>
        <div class="row">
          <div><label>Kategori</label><select id="category"></select></div>
          <div><label>Yazar</label><input id="author"></div>
        </div>
        <label>Ozet</label><textarea id="summary"></textarea>
        <label>Haber metni</label><textarea id="body" style="min-height:220px"></textarea>
        <div class="row">
          <div><label>Görsel yolu</label><input id="image" placeholder="/assets/images/ankara.png"></div>
          <div><label>Görsel alt metni</label><input id="image_alt"></div>
        </div>
        <div class="row">
          <div><label>Yayin tarihi</label><input id="published_at"></div>
          <div><label>Durum</label><select id="status"><option value="published">Yayinda</option><option value="draft">Taslak</option></select></div>
          <div><label>Etiketler</label><input id="tags" placeholder="gundem, ekonomi"></div>
        </div>
        <div class="row">
          <div><label>Kaynak adi</label><input id="source_name"></div>
          <div><label>Kaynak URL</label><input id="source_url"></div>
        </div>
        <div class="row" style="margin-top:14px">
          <button type="submit">Kaydet</button>
          <button type="button" class="danger" onclick="deleteCurrent()">Sil</button>
        </div>
      </form>
      <form id="newsForm" class="hidden" onsubmit="importNews(event)">
        <p class="muted">RSS kaynaklarını tarar, kopya haberleri ayıklar, haber metni oluşturur. Kaynak görseli ekleme telif kontrolü gerektirdiği için isteğe bağlıdır.</p>
        <div class="row">
          <div><label>Tarama limiti</label><input id="newsLimit" type="number" min="1" max="50" value="18"></div>
          <div><label>İçeriğe alınacak yeni haber</label><input id="newsMax" type="number" min="1" max="20" value="3"></div>
          <div><label>Aktarma durumu</label><select id="newsStatus"><option value="published" selected>Yayında</option><option value="draft">Taslak</option></select></div>
        </div>
        <label><input id="newsPublishSite" type="checkbox" checked style="width:auto; margin-right:8px">İçeriğe aldıktan sonra statik siteyi yayınla</label>
        <label><input id="newsEnrichImages" type="checkbox" style="width:auto; margin-right:8px">Kaynak görseli tara ve yerel olarak ekle</label>
        <div class="row" style="margin-top:14px">
          <button type="button" class="secondary" onclick="scanNews()">Kaynakları Tara</button>
          <button type="button" class="secondary" onclick="healNetwork()">IP/Ağ Ön Hazırlığı</button>
          <button type="button" class="secondary" onclick="runAutonomousCycle()">Otonom Döngü Testi</button>
          <button type="button" class="secondary" onclick="enrichImages()">Arşiv Görsellerini Tara</button>
          <button type="submit">Haberleri İçeriğe Al</button>
        </div>
        <div id="newsResults" class="news-results"></div>
      </form>
      <form id="settingsForm" class="hidden" onsubmit="saveSettings(event)">
        <div class="row">
          <div><label>Site adi</label><input id="siteName"></div>
          <div><label>Domain</label><input id="domain"></div>
        </div>
        <label>Base URL</label><input id="baseUrl">
        <div class="row">
          <div><label>Primary renk</label><input id="primary"></div>
          <div><label>Accent renk</label><input id="accent"></div>
        </div>
        <label>Kategoriler</label>
        <textarea id="categories" placeholder="slug | Gorunen ad"></textarea>
        <p class="muted">Her satir: <code>slug | Gorunen ad</code>. Ornek: <code>gundem | Gundem</code></p>
        <button type="submit">Ayarlari Kaydet</button>
      </form>
      <form id="dnsForm" class="hidden" onsubmit="generateDns(event)">
        <label>Primary DNS / Model B IPv4</label>
        <input id="primaryIp" placeholder="1.2.3.4">
        <label>Secondary DNS IPv4</label>
        <input id="secondaryIp" placeholder="5.6.7.8">
        <p class="muted">Üretim için ns2 farklı bir sunucu/IP olmalı. Tek IP ile test yapılabilir ama önerilmez.</p>
        <button type="submit">DNS Zone Üret</button>
      </form>
      <pre id="output" class="hidden">Hazir.</pre>
    </section>
  </main>
  <script>
    let articles = [];
    let settings = null;
    let scannedNews = null;
    let currentSlug = '';
    const $ = id => document.getElementById(id);
    function log(value) { $('output').textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2); }
    function showTab(name) {
      $('articleForm').classList.toggle('hidden', name !== 'article');
      $('newsForm').classList.toggle('hidden', name !== 'news');
      $('settingsForm').classList.toggle('hidden', name !== 'settings');
      $('dnsForm').classList.toggle('hidden', name !== 'dns');
      $('output').classList.toggle('hidden', name !== 'output');
      $('tabArticle').classList.toggle('active', name === 'article');
      $('tabNews').classList.toggle('active', name === 'news');
      $('tabSettings').classList.toggle('active', name === 'settings');
      $('tabDns').classList.toggle('active', name === 'dns');
      $('tabOutput').classList.toggle('active', name === 'output');
    }
    async function api(url, options) {
      const res = await fetch(url, options);
      const contentType = res.headers.get('content-type') || '';
      const isJson = contentType.includes('application/json');
      const data = isJson ? await res.json() : await res.text();
      if (!res.ok) {
        const message = isJson && data && data.error
          ? data.error
          : (typeof data === 'string' && data.trim() ? data.trim() : 'Islem basarisiz');
        throw new Error(message);
      }
      if (isJson && data && data.ok === false) throw new Error(data.error || 'Islem basarisiz');
      return data;
    }
    async function loadAll() {
      articles = await api('/api/articles?site=turkiye-gundemi');
      settings = await api('/api/site-config?site=turkiye-gundemi');
      renderList();
      renderCategories();
      fillSettings();
      if (articles[0]) fillArticle(articles[0]);
    }
    function renderList() {
      $('articleList').innerHTML = articles.map(a => {
        const status = a.status || 'published';
        const label = status === 'draft' ? 'Taslak' : 'Yayinda';
        return `<li><button onclick="selectArticle('${a.slug.replaceAll("'", "\\'")}')"><strong>${escapeHtml(a.title)}</strong><br><span class="muted">${escapeHtml(a.category)} - ${escapeHtml(a.published_at || '')}</span><br><span class="badge ${status === 'draft' ? 'draft' : ''}">${label}</span></button></li>`;
      }).join('');
    }
    function renderCategories() {
      $('category').innerHTML = (settings.categories || []).map(c => `<option value="${escapeHtml(c.slug)}">${escapeHtml(c.name)}</option>`).join('');
    }
    function fillSettings() {
      $('siteName').value = settings.name || '';
      $('domain').value = settings.domain || '';
      $('baseUrl').value = settings.base_url || '';
      $('primary').value = (settings.theme || {}).primary || '';
      $('accent').value = (settings.theme || {}).accent || '';
      $('categories').value = (settings.categories || []).map(c => `${c.slug} | ${c.name}`).join('\\n');
    }
    function selectArticle(slug) {
      const article = articles.find(a => a.slug === slug);
      if (article) fillArticle(article);
    }
    function fillArticle(article) {
      currentSlug = article.slug || '';
      $('title').value = article.title || '';
      $('slug').value = article.slug || '';
      $('category').value = article.category || 'gundem';
      $('author').value = article.author || '';
      $('summary').value = article.summary || '';
      $('body').value = Array.isArray(article.body) ? article.body.join('\\n\\n') : (article.body || '');
      $('image').value = article.image || '';
      $('image_alt').value = article.image_alt || '';
      $('published_at').value = article.published_at || '';
      $('status').value = article.status || 'published';
      $('tags').value = Array.isArray(article.tags) ? article.tags.join(', ') : (article.tags || '');
      $('source_name').value = article.source_name || '';
      $('source_url').value = article.source_url || '';
      showTab('article');
    }
    function newArticle() {
      currentSlug = '';
      $('articleForm').reset();
      $('category').value = (settings.categories && settings.categories[0] && settings.categories[0].slug) || 'gundem';
      $('author').value = 'Türkiye Gündemi Haber Merkezi';
      $('image').value = '/assets/images/ankara.png';
      showTab('article');
    }
    async function saveArticle(event) {
      event.preventDefault();
      const payload = {
        site: 'turkiye-gundemi',
        title: $('title').value,
        slug: $('slug').value || currentSlug,
        category: $('category').value,
        author: $('author').value,
        summary: $('summary').value,
        body: $('body').value,
        image: $('image').value,
        image_alt: $('image_alt').value,
        published_at: $('published_at').value,
        status: $('status').value,
        tags: $('tags').value,
        source_name: $('source_name').value,
        source_url: $('source_url').value
      };
      const data = await api('/api/articles', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
      log(data);
      await loadAll();
      fillArticle(data.article);
      showTab('output');
    }
    async function deleteCurrent() {
      if (!currentSlug || !confirm('Bu haberi silmek istiyor musunuz?')) return;
      const data = await api('/api/delete-article', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({site:'turkiye-gundemi', slug: currentSlug})});
      log(data);
      currentSlug = '';
      await loadAll();
      showTab('output');
    }
    async function saveSettings(event) {
      event.preventDefault();
      const payload = {
        site: 'turkiye-gundemi',
        name: $('siteName').value,
        domain: $('domain').value,
        base_url: $('baseUrl').value,
        theme: { primary: $('primary').value, accent: $('accent').value },
        categories: $('categories').value
      };
      const data = await api('/api/site-config', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
      log(data);
      await loadAll();
      showTab('output');
    }
    async function publishSite() {
      const data = await api('/api/publish', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({site:'turkiye-gundemi'})});
      log(data);
      showTab('output');
    }
    async function scanNews() {
      $('newsResults').innerHTML = '<p class="muted">Kaynaklar taranıyor...</p>';
      scannedNews = await api('/api/news-scan?limit=' + encodeURIComponent($('newsLimit').value || '18'));
      renderNewsResults(scannedNews);
    }
    function renderNewsResults(payload) {
      const sourceStatus = payload.source_status || [];
      const status = sourceStatus.map(item => `<span class="badge ${item.status === 'error' ? 'draft' : ''}">${escapeHtml(item.source)}: ${escapeHtml(item.status)}</span>`).join(' ');
      const diagnostic = sourceStatus.length === 0
        ? '<p class="muted">Kaynak listesi yüklenemedi. EXE yanındaki workspace/config/news_sources.json dosyasını kontrol edin.</p>'
        : '';
      const cards = (payload.items || []).slice(0, 12).map(item => `
        <article class="news-card">
          <div class="muted">${escapeHtml(item.source)} - ${escapeHtml(item.category)} - ${escapeHtml(item.published_at || '')}</div>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml((item.variants && item.variants.spot) || item.summary || '')}</p>
          <a href="${escapeHtml(item.link)}" target="_blank" rel="noopener noreferrer">Kaynak haberi ac</a>
        </article>
      `).join('');
      $('newsResults').innerHTML = `<div>${status}</div>${diagnostic}${cards || '<p class="muted">Haber bulunamadı.</p>'}`;
    }
    async function importNews(event) {
      event.preventDefault();
      const payload = {
        site: 'turkiye-gundemi',
        limit: Number($('newsLimit').value || 18),
        max_items: Number($('newsMax').value || 3),
        status: $('newsStatus').value,
        publish_site: $('newsPublishSite').checked,
        enrich_images: $('newsEnrichImages').checked
      };
      const data = await api('/api/news-import', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
      log(data);
      await loadAll();
      if (data.imported && data.imported[0]) fillArticle(data.imported[0]);
      showTab('output');
    }
    async function enrichImages(force = false) {
      const payload = {
        site: 'turkiye-gundemi',
        limit: Number($('newsLimit').value || 18),
        publish_site: $('newsPublishSite').checked,
        force
      };
      const data = await api('/api/enrich-images', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
      log(data);
      await loadAll();
      showTab('output');
    }
    async function healNetwork() {
      const data = await api('/api/network-heal', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({site:'turkiye-gundemi', publish_site:$('newsPublishSite').checked, generate_dns:true})});
      log(data);
      showTab('output');
    }
    async function runAutonomousCycle() {
      const payload = {
        site: 'turkiye-gundemi',
        limit: Number($('newsLimit').value || 18),
        max_items: Number($('newsMax').value || 3),
        status: $('newsStatus').value,
        publish_site: $('newsPublishSite').checked,
        enrich_images: $('newsEnrichImages').checked,
        heal_network: true
      };
      const data = await api('/api/autonomous-cycle', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
      log(data);
      await loadAll();
      showTab('output');
    }
    async function generateDns(event) {
      event.preventDefault();
      const data = await api('/api/dns-generate', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({site:'turkiye-gundemi', primary_ip:$('primaryIp').value, secondary_ip:$('secondaryIp').value})});
      log(data);
      showTab('output');
    }
    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }
    loadAll().catch(err => log(err.message));
  </script>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Growth OS local server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--site-at-root", action="store_true", help="Serve Turkiye Gundemi at / and keep admin at /admin")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), GrowthHandler)
    server.site_at_root = args.site_at_root or os.environ.get("GROWTH_OS_SITE_AT_ROOT") == "1"
    print(f"Serving Growth OS on http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
