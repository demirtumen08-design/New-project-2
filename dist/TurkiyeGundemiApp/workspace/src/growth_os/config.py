from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def resolve_root() -> Path:
    env_root = os.environ.get("GROWTH_OS_ROOT")
    if env_root:
        return Path(env_root).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "workspace"
    return Path(__file__).resolve().parents[2]


ROOT = resolve_root()
CONFIG_PATH = ROOT / "config" / "sites.json"


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def get_site(site_id: str) -> dict[str, Any]:
    config = load_config()
    try:
        site = config["sites"][site_id]
    except KeyError as exc:
        known = ", ".join(sorted(config.get("sites", {}).keys()))
        raise SystemExit(f"Unknown site '{site_id}'. Known sites: {known}") from exc
    site = dict(site)
    site["id"] = site_id
    return site


def project_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return ROOT / path
