from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import get_site, project_path
from .content_store import load_articles
from .image_enrichment import apply_related_visuals
from .sitegen import generate as generate_site


STATE_RELATIVE_PATH = "content/turkiye-gundemi/production_operator_state.json"
NEWS_STATE_RELATIVE_PATH = "content/turkiye-gundemi/news_automation_state.json"
MANAGED_UNITS = ("growth-os.service", "growth-os-newsbot.timer")
MANAGED_DIRS = ("config", "content", "sites", "reports")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone()


def run_command(parts: list[str], timeout: int = 30) -> dict[str, Any]:
    try:
        completed = subprocess.run(parts, capture_output=True, text=True, timeout=timeout, check=False)
    except Exception as exc:  # noqa: BLE001 - operator should report, not crash
        return {"ok": False, "command": parts, "returncode": -1, "stdout": "", "stderr": str(exc)}
    return {
        "ok": completed.returncode == 0,
        "command": parts,
        "returncode": completed.returncode,
        "stdout": (completed.stdout or "").strip(),
        "stderr": (completed.stderr or "").strip(),
    }


def systemctl(*args: str, timeout: int = 30) -> dict[str, Any]:
    return run_command(["systemctl", *args], timeout=timeout)


def unit_active(unit: str) -> bool:
    return systemctl("is-active", "--quiet", unit, timeout=8)["ok"]


def ensure_unit(unit: str) -> dict[str, Any]:
    before = unit_active(unit)
    action = "none"
    command: dict[str, Any] | None = None
    if not before:
        action = "start"
        command = systemctl("start", unit, timeout=90)
    after = unit_active(unit)
    return {"unit": unit, "active_before": before, "action": action, "active_after": after, "command": command}


def restart_unit(unit: str) -> dict[str, Any]:
    command = systemctl("restart", unit, timeout=90)
    return {"unit": unit, "command": command, "active_after": unit_active(unit)}


def check_url(url: str, timeout: int = 10, contains: str = "") -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "TurkiyeGundemiOperator/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(80_000).decode("utf-8", errors="replace")
            status = int(response.status)
    except Exception as exc:  # noqa: BLE001 - state should carry exact failure
        return {"ok": False, "url": url, "status": 0, "error": str(exc)}
    ok = 200 <= status < 400 and (not contains or contains in payload)
    return {"ok": ok, "url": url, "status": status, "bytes": len(payload), "contains": bool(contains and contains in payload)}


def wait_for_url(url: str, *, timeout: int = 10, contains: str = "", attempts: int = 6, delay_seconds: float = 1.0) -> dict[str, Any]:
    last: dict[str, Any] = {"ok": False, "url": url, "status": 0, "error": "not checked"}
    for attempt in range(1, max(1, attempts) + 1):
        last = check_url(url, timeout=timeout, contains=contains)
        last["attempt"] = attempt
        if last["ok"]:
            return last
        if attempt < attempts:
            time.sleep(delay_seconds)
    return last


def fix_permissions(service_user: str, service_group: str | None = None) -> dict[str, Any]:
    service_group = service_group or service_user
    result: dict[str, Any] = {"attempted": False, "ok": True, "commands": [], "warning": ""}
    if os.name != "posix":
        result["warning"] = "permission repair only runs on Linux/POSIX"
        return result
    if getattr(os, "geteuid", lambda: 1)() != 0:
        result["warning"] = "not running as root; ownership repair skipped"
        return result
    result["attempted"] = True
    for name in MANAGED_DIRS:
        path = project_path(name)
        path.mkdir(parents=True, exist_ok=True)
        command = run_command(["chown", "-R", f"{service_user}:{service_group}", str(path)], timeout=90)
        result["commands"].append(command)
        result["ok"] = bool(result["ok"] and command["ok"])
    return result


def load_news_state() -> dict[str, Any]:
    path = project_path(NEWS_STATE_RELATIVE_PATH)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def news_age_minutes() -> int | None:
    last_import = str(load_news_state().get("last_import_at", "")).strip()
    parsed = parse_iso(last_import)
    if parsed is None:
        return None
    return int((datetime.now(timezone.utc).astimezone() - parsed).total_seconds() // 60)


def site_signature(site_id: str) -> dict[str, Any]:
    site = get_site(site_id)
    public_dir = project_path(site["public_dir"])
    index = public_dir / "index.html"
    css = public_dir / "assets" / "styles.css"
    return {
        "public_dir": str(public_dir),
        "index_exists": index.exists(),
        "css_exists": css.exists(),
        "index_has_headline_stage": index.exists() and "headline-stage" in index.read_text(encoding="utf-8", errors="replace"),
    }


def generate_if_needed(site_id: str, force: bool = False) -> dict[str, Any]:
    before = site_signature(site_id)
    should_generate = force or not before["index_exists"] or not before["css_exists"] or not before["index_has_headline_stage"]
    generated_dir = ""
    error = ""
    if should_generate:
        try:
            generated_dir = str(generate_site(site_id))
        except Exception as exc:  # noqa: BLE001 - operator state should carry error
            error = str(exc)
    after = site_signature(site_id)
    return {"generated": should_generate and not error, "generated_dir": generated_dir, "error": error, "before": before, "after": after}


def article_counts(site_id: str) -> dict[str, int]:
    try:
        articles = load_articles(site_id)
    except Exception:
        return {"total": 0, "published": 0, "draft": 0}
    published = [article for article in articles if article.get("status", "published") == "published"]
    return {"total": len(articles), "published": len(published), "draft": len(articles) - len(published)}


def trigger_news_if_stale(max_news_age_minutes: int) -> dict[str, Any]:
    age = news_age_minutes()
    running = unit_active("growth-os-newsbot.service")
    result: dict[str, Any] = {"age_minutes": age, "running": running, "triggered": False, "command": None}
    if running:
        return result
    if age is None or age >= max_news_age_minutes:
        result["triggered"] = True
        result["command"] = systemctl("start", "growth-os-newsbot.service", timeout=180)
    return result


def save_state(payload: dict[str, Any]) -> None:
    path = project_path(STATE_RELATIVE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_operator(
    *,
    site_id: str = "turkiye-gundemi",
    service_user: str = "growthos",
    health_url: str = "http://127.0.0.1:8080/healthz",
    public_url: str = "http://127.0.0.1/",
    max_news_age_minutes: int = 12,
    force_generate: bool = False,
    trigger_news: bool = True,
) -> dict[str, Any]:
    started_at = now_iso()
    warnings: list[str] = []
    permissions = fix_permissions(service_user)
    if permissions.get("warning"):
        warnings.append(str(permissions["warning"]))

    related_images = apply_related_visuals(site_id, publish_site=False)
    site_generation = generate_if_needed(site_id, force=force_generate or bool(related_images.get("updated_count")))
    unit_results = [ensure_unit(unit) for unit in MANAGED_UNITS]

    health = wait_for_url(health_url, contains="ok", attempts=3, delay_seconds=1.0)
    restart: dict[str, Any] | None = None
    if not health["ok"]:
        restart = restart_unit("growth-os.service")
        health = wait_for_url(health_url, contains="ok", attempts=8, delay_seconds=1.0)

    news_trigger = trigger_news_if_stale(max_news_age_minutes) if trigger_news else {"triggered": False}
    homepage = wait_for_url(public_url, contains="headline-stage", attempts=4, delay_seconds=1.0)

    payload: dict[str, Any] = {
        "ok": bool(health["ok"] and homepage["ok"] and all(unit.get("active_after") for unit in unit_results)),
        "started_at": started_at,
        "finished_at": now_iso(),
        "site_id": site_id,
        "permissions": permissions,
        "site_generation": site_generation,
        "related_images": related_images,
        "units": unit_results,
        "health": health,
        "restart": restart,
        "news": news_trigger,
        "homepage": homepage,
        "article_counts": article_counts(site_id),
        "warnings": warnings,
    }
    save_state(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Growth OS Linux production operator.")
    parser.add_argument("--site", default="turkiye-gundemi")
    parser.add_argument("--service-user", default="growthos")
    parser.add_argument("--health-url", default="http://127.0.0.1:8080/healthz")
    parser.add_argument("--public-url", default="http://127.0.0.1/")
    parser.add_argument("--max-news-age-minutes", type=int, default=12)
    parser.add_argument("--force-generate", action="store_true")
    parser.add_argument("--no-trigger-news", action="store_true")
    args = parser.parse_args(argv)
    print(
        json.dumps(
            run_operator(
                site_id=args.site,
                service_user=args.service_user,
                health_url=args.health_url,
                public_url=args.public_url,
                max_news_age_minutes=max(5, args.max_news_age_minutes),
                force_generate=args.force_generate,
                trigger_news=not args.no_trigger_news,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
