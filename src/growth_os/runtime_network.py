from __future__ import annotations

import json
import os
import socket
import subprocess
import urllib.request
from datetime import datetime, timezone
from ipaddress import ip_address
from pathlib import Path
from typing import Any

from .config import load_config, project_path, save_config
from .dnsgen import generate as generate_dns
from .sitegen import generate as generate_site


STATE_RELATIVE_PATH = "content/turkiye-gundemi/runtime_network_state.json"
PUBLIC_IP_ENDPOINTS = (
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://checkip.amazonaws.com",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def is_valid_ipv4(value: str) -> bool:
    try:
        parsed = ip_address(str(value).strip())
    except ValueError:
        return False
    return parsed.version == 4 and not parsed.is_loopback and not parsed.is_unspecified


def run_command(parts: list[str], timeout: int = 4) -> str:
    try:
        completed = subprocess.run(parts, capture_output=True, text=True, timeout=timeout, check=False)
    except Exception:
        return ""
    return (completed.stdout or "").strip()


def detect_default_lan_ip() -> str:
    for target in (("8.8.8.8", 80), ("1.1.1.1", 80), ("9.9.9.9", 80)):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            try:
                sock.settimeout(3)
                sock.connect(target)
                candidate = str(sock.getsockname()[0])
            except OSError:
                candidate = ""
        if is_valid_ipv4(candidate):
            return candidate

    route = run_command(["ip", "route", "get", "1.1.1.1"])
    if route:
        parts = route.split()
        if "src" in parts:
            candidate = parts[parts.index("src") + 1]
            if is_valid_ipv4(candidate):
                return candidate

    hostname_ips = run_command(["hostname", "-I"])
    for candidate in hostname_ips.split():
        if is_valid_ipv4(candidate):
            return candidate

    try:
        candidate = socket.gethostbyname(socket.gethostname())
    except OSError:
        candidate = ""
    return candidate if is_valid_ipv4(candidate) else ""


def detect_public_ip(timeout: int = 6) -> str:
    for endpoint in PUBLIC_IP_ENDPOINTS:
        request = urllib.request.Request(endpoint, headers={"User-Agent": "TurkiyeGundemiNetWatch/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read(128).decode("utf-8", errors="replace").strip()
        except Exception:
            continue
        candidate = payload.strip().split()[0].strip()
        if is_valid_ipv4(candidate):
            return candidate
    return ""


def load_state() -> dict[str, Any]:
    path = project_path(STATE_RELATIVE_PATH)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict[str, Any]) -> None:
    path = project_path(STATE_RELATIVE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_network_defaults() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "enabled": True,
        "prefer_public_ip": True,
        "update_dns_records": True,
        "regenerate_dns_on_ip_change": True,
        "regenerate_site_on_ip_change": True,
        "network_check_interval_seconds": 300,
        "secondary_ip": "",
    }
    path = project_path("config/news_sources.json")
    try:
        raw = json.loads(path.read_text(encoding="utf-8")).get("defaults", {}).get("network_auto_repair", {})
    except Exception:
        raw = {}
    if isinstance(raw, dict):
        defaults.update(raw)
    return defaults


def detect_network_snapshot(prefer_public_ip: bool | None = None) -> dict[str, Any]:
    defaults = load_network_defaults()
    if prefer_public_ip is None:
        prefer_public_ip = bool(defaults.get("prefer_public_ip", True))
    local_ipv4 = detect_default_lan_ip()
    public_ipv4 = detect_public_ip()
    if prefer_public_ip and public_ipv4:
        publish_ipv4 = public_ipv4
        publish_source = "public"
    elif local_ipv4:
        publish_ipv4 = local_ipv4
        publish_source = "local"
    else:
        publish_ipv4 = public_ipv4
        publish_source = "public" if public_ipv4 else "none"
    return {
        "detected_at": now_iso(),
        "local_ipv4": local_ipv4,
        "public_ipv4": public_ipv4,
        "publish_ipv4": publish_ipv4,
        "publish_source": publish_source,
        "prefer_public_ip": bool(prefer_public_ip),
    }


def current_config_primary_ip(config: dict[str, Any], site_id: str) -> str:
    try:
        return str(config["sites"][site_id].get("dns", {}).get("primary_ipv4", "")).strip()
    except Exception:
        return ""


def apply_ip_to_site_config(site_id: str, primary_ip: str) -> dict[str, Any]:
    config = load_config()
    site = config.setdefault("sites", {}).setdefault(site_id, {})
    dns = site.setdefault("dns", {})
    before = str(dns.get("primary_ipv4", "")).strip()
    changed = before != primary_ip
    dns["primary_ipv4"] = primary_ip

    for record in dns.get("records", []):
        if not isinstance(record, dict):
            continue
        if str(record.get("type", "")).upper() != "A":
            continue
        name = str(record.get("name", "")).strip()
        if name in {"@", "www", "ns1"}:
            if str(record.get("value", "")).strip() != primary_ip:
                record["value"] = primary_ip
                changed = True

    if changed:
        save_config(config)
    return {"changed": changed, "before": before, "after": primary_ip}


def runtime_status() -> dict[str, Any]:
    state = load_state()
    snapshot = detect_network_snapshot()
    config = load_config()
    return {
        "ok": True,
        "generated_at": now_iso(),
        "snapshot": snapshot,
        "config_primary_ipv4": current_config_primary_ip(config, "turkiye-gundemi"),
        "state": state,
    }


def write_public_synthesis(site_id: str, payload: dict[str, Any]) -> str:
    config = load_config()
    site = config["sites"][site_id]
    public_dir = project_path(site["public_dir"])
    public_dir.mkdir(parents=True, exist_ok=True)
    target = public_dir / "runtime-synthesis.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


def heal_network_runtime(
    site_id: str = "turkiye-gundemi",
    *,
    apply_config: bool = True,
    publish_site: bool = False,
    generate_dns_files: bool = True,
    prefer_public_ip: bool | None = None,
) -> dict[str, Any]:
    defaults = load_network_defaults()
    snapshot = detect_network_snapshot(prefer_public_ip=prefer_public_ip)
    state = load_state()
    previous_ip = str(state.get("last_publish_ipv4", "")).strip()
    detected_ip = str(snapshot.get("publish_ipv4", "")).strip()

    result: dict[str, Any] = {
        "ok": True,
        "generated_at": now_iso(),
        "site_id": site_id,
        "enabled": bool(defaults.get("enabled", True)),
        "snapshot": snapshot,
        "previous_publish_ipv4": previous_ip,
        "ip_changed": bool(detected_ip and detected_ip != previous_ip),
        "config_update": {"changed": False},
        "dns_dir": None,
        "public_dir": None,
        "warnings": [],
    }

    if not defaults.get("enabled", True):
        result["warnings"].append("network_auto_repair disabled")
        save_state({**state, "last_check": result})
        return result

    if not detected_ip:
        result["ok"] = False
        result["warnings"].append("publish_ipv4 detected edilemedi")
        save_state({**state, "last_check": result})
        return result

    if apply_config and defaults.get("update_dns_records", True):
        result["config_update"] = apply_ip_to_site_config(site_id, detected_ip)

    secondary_ip = str(defaults.get("secondary_ip") or detected_ip).strip()
    if generate_dns_files and defaults.get("regenerate_dns_on_ip_change", True) and (result["ip_changed"] or result["config_update"].get("changed")):
        try:
            result["dns_dir"] = str(generate_dns(site_id, detected_ip, secondary_ip))
        except Exception as exc:
            result["ok"] = False
            result["warnings"].append(f"DNS uretim hatasi: {exc}")

    if publish_site and defaults.get("regenerate_site_on_ip_change", True) and (result["ip_changed"] or result["config_update"].get("changed")):
        try:
            result["public_dir"] = str(generate_site(site_id))
        except Exception as exc:
            result["ok"] = False
            result["warnings"].append(f"Site uretim hatasi: {exc}")

    synthesis = {
        "type": "runtime-network-synthesis",
        "generated_at": now_iso(),
        "site_id": site_id,
        "detected": snapshot,
        "previous_publish_ipv4": previous_ip,
        "ip_changed": result["ip_changed"],
        "config_update": result["config_update"],
        "dns_dir": result["dns_dir"],
        "public_dir": result["public_dir"],
        "warnings": result["warnings"],
    }
    try:
        result["synthesis_path"] = write_public_synthesis(site_id, synthesis)
    except Exception as exc:
        result["warnings"].append(f"runtime synthesis yazilamadi: {exc}")

    state.update(
        {
            "last_checked_at": now_iso(),
            "last_publish_ipv4": detected_ip,
            "last_snapshot": snapshot,
            "last_result": result,
        }
    )
    save_state(state)
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Detect and repair Growth OS runtime IP/DNS state.")
    parser.add_argument("--site", default="turkiye-gundemi")
    parser.add_argument("--status-only", action="store_true")
    parser.add_argument("--no-apply", action="store_true")
    parser.add_argument("--publish-site", action="store_true")
    parser.add_argument("--no-dns", action="store_true")
    parser.add_argument("--prefer-local-ip", action="store_true")
    parser.add_argument("--prefer-public-ip", action="store_true")
    args = parser.parse_args(argv)

    prefer_public_ip = None
    if args.prefer_local_ip:
        prefer_public_ip = False
    elif args.prefer_public_ip:
        prefer_public_ip = True

    if args.status_only:
        print(json.dumps(runtime_status(), ensure_ascii=False, indent=2))
        return 0

    print(
        json.dumps(
            heal_network_runtime(
                args.site,
                apply_config=not args.no_apply,
                publish_site=args.publish_site,
                generate_dns_files=not args.no_dns,
                prefer_public_ip=prefer_public_ip,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
