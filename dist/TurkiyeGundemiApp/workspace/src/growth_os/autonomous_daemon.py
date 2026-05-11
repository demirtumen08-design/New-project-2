from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import project_path
from .news_automation import import_news, load_runtime_defaults
from .runtime_network import heal_network_runtime, load_network_defaults


STATE_RELATIVE_PATH = "content/turkiye-gundemi/autonomous_daemon_state.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def save_state(state: dict[str, Any]) -> None:
    path = project_path(STATE_RELATIVE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state() -> dict[str, Any]:
    path = project_path(STATE_RELATIVE_PATH)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def run_cycle(
    *,
    site_id: str = "turkiye-gundemi",
    limit: int | None = None,
    max_items: int | None = None,
    status: str | None = None,
    publish_site: bool | None = None,
    enrich_images: bool | None = None,
    heal_network: bool = True,
    prefer_public_ip: bool | None = None,
) -> dict[str, Any]:
    defaults = load_runtime_defaults()
    resolved_publish_site = defaults["publish_site_after_import"] if publish_site is None else bool(publish_site)

    started_at = now_iso()
    network_result: dict[str, Any] | None = None
    import_result: dict[str, Any] | None = None
    error = ""

    try:
        if heal_network:
            network_result = heal_network_runtime(
                site_id,
                apply_config=True,
                publish_site=False,
                generate_dns_files=True,
                prefer_public_ip=prefer_public_ip,
            )
        import_result = import_news(
            site_id=site_id,
            limit=limit,
            max_items=max_items,
            status=status,
            publish_site=resolved_publish_site,
            enrich_images=enrich_images,
        )
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001 - daemon must stay alive
        error = str(exc)

    payload: dict[str, Any] = {
        "ok": not bool(error),
        "started_at": started_at,
        "finished_at": now_iso(),
        "site_id": site_id,
        "network": network_result,
        "news": import_result,
        "error": error,
    }

    state = load_state()
    history = state.get("history", [])
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "finished_at": payload["finished_at"],
            "ok": payload["ok"],
            "ip_changed": bool((network_result or {}).get("ip_changed")),
            "imported_count": int((import_result or {}).get("imported_count", 0) or 0),
            "error": error,
        }
    )
    state.update({"last_cycle": payload, "history": history[-200:]})
    save_state(state)
    return payload


def run_loop(
    *,
    site_id: str = "turkiye-gundemi",
    limit: int | None = None,
    max_items: int | None = None,
    status: str | None = None,
    publish_site: bool | None = None,
    enrich_images: bool | None = None,
    heal_network: bool = True,
    prefer_public_ip: bool | None = None,
    interval_seconds: int | None = None,
) -> int:
    runtime_defaults = load_runtime_defaults()
    network_defaults = load_network_defaults()
    sleep_seconds = int(interval_seconds or runtime_defaults.get("scan_interval_seconds") or 900)
    sleep_seconds = max(60, min(sleep_seconds, 86_400))

    while True:
        result = run_cycle(
            site_id=site_id,
            limit=limit,
            max_items=max_items,
            status=status,
            publish_site=publish_site,
            enrich_images=enrich_images,
            heal_network=heal_network,
            prefer_public_ip=prefer_public_ip,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        time.sleep(sleep_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Growth OS 7/24 autonomous production daemon.")
    parser.add_argument("--site", default="turkiye-gundemi")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-items", type=int)
    parser.add_argument("--status", choices=["draft", "published"])
    parser.add_argument("--publish-site", dest="publish_site", action="store_true")
    parser.add_argument("--no-publish-site", dest="publish_site", action="store_false")
    parser.add_argument("--enrich-images", dest="enrich_images", action="store_true")
    parser.add_argument("--no-enrich-images", dest="enrich_images", action="store_false")
    parser.add_argument("--no-network-heal", action="store_true")
    parser.add_argument("--prefer-local-ip", action="store_true")
    parser.add_argument("--prefer-public-ip", action="store_true")
    parser.add_argument("--interval-seconds", type=int)
    parser.add_argument("--once", action="store_true")
    parser.set_defaults(publish_site=None, enrich_images=None)
    args = parser.parse_args(argv)

    prefer_public_ip = None
    if args.prefer_local_ip:
        prefer_public_ip = False
    elif args.prefer_public_ip:
        prefer_public_ip = True

    if args.once:
        print(
            json.dumps(
                run_cycle(
                    site_id=args.site,
                    limit=args.limit,
                    max_items=args.max_items,
                    status=args.status,
                    publish_site=args.publish_site,
                    enrich_images=args.enrich_images,
                    heal_network=not args.no_network_heal,
                    prefer_public_ip=prefer_public_ip,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    return run_loop(
        site_id=args.site,
        limit=args.limit,
        max_items=args.max_items,
        status=args.status,
        publish_site=args.publish_site,
        enrich_images=args.enrich_images,
        heal_network=not args.no_network_heal,
        prefer_public_ip=prefer_public_ip,
        interval_seconds=args.interval_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
