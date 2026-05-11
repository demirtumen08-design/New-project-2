import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

from .config import get_site, project_path
from .content_store import load_articles, now_iso


COOKIE_NAME = "tg_dosya_access"


def default_payment_settings() -> dict[str, Any]:
    return {
        "enabled": False,
        "provider": "payment_link",
        "provider_label": "Ödeme linki",
        "currency": "TRY",
        "plans": [
            {"id": "aylik", "name": "Aylık", "price_label": "99 TL", "days": 30, "payment_url": ""},
            {"id": "uc-aylik", "name": "3 Aylık", "price_label": "249 TL", "days": 90, "payment_url": ""},
            {"id": "yillik", "name": "Yıllık", "price_label": "899 TL", "days": 365, "payment_url": ""},
        ],
    }


def default_settings() -> dict[str, Any]:
    return {
        "enabled": True,
        "tier": "dosya",
        "price_label": "Aylık 99 TL",
        "cookie_days": 30,
        "payment": default_payment_settings(),
    }
DEFAULT_SETTINGS = default_settings()
_LEGACY_DEFAULT_SETTINGS = {
    "enabled": True,
    "tier": "dosya",
    "price_label": "Aylık 99 TL",
    "cookie_days": 30,
}


def subscription_store_path(site_id: str) -> Path:
    site = get_site(site_id)
    return project_path(site["content_file"]).parent / "subscriptions.json"


def _secret() -> bytes:
    raw = (
        os.environ.get("GROWTH_OS_SUBSCRIPTION_SECRET")
        or os.environ.get("GROWTH_OS_ADMIN_PASSWORD")
        or "growth-os-local-subscription-secret"
    )
    return raw.encode("utf-8")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _b64_json(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64_json(value: str) -> dict[str, Any]:
    padded = value + ("=" * (-len(value) % 4))
    raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    return json.loads(raw.decode("utf-8"))


def _sign(value: str) -> str:
    return hmac.new(_secret(), value.encode("utf-8"), hashlib.sha256).hexdigest()


def hash_code(code: str) -> str:
    normalized = str(code or "").strip().upper()
    return hmac.new(_secret(), normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def normalize_payment_settings(value: Any) -> dict[str, Any]:
    current = default_payment_settings()
    if isinstance(value, dict):
        for key in ("enabled", "provider", "provider_label", "currency"):
            if key in value:
                current[key] = value[key]
        incoming_plans = value.get("plans")
        if isinstance(incoming_plans, list):
            defaults_by_id = {str(plan.get("id") or ""): dict(plan) for plan in current["plans"]}
            normalized_order: list[dict[str, Any]] = []
            for item in incoming_plans:
                if not isinstance(item, dict):
                    continue
                plan_id = str(item.get("id") or "").strip() or f"plan-{len(normalized_order) + 1}"
                base = defaults_by_id.get(
                    plan_id,
                    {"id": plan_id, "name": plan_id, "price_label": "", "days": 30, "payment_url": ""},
                )
                base.update(item)
                normalized_order.append(base)
            if normalized_order:
                current["plans"] = normalized_order
    current["enabled"] = bool(current.get("enabled", False))
    current["provider"] = str(current.get("provider") or "payment_link").strip()
    current["provider_label"] = str(current.get("provider_label") or "Ödeme linki").strip()
    current["currency"] = str(current.get("currency") or "TRY").strip().upper()
    normalized_plans = []
    for item in current.get("plans") or []:
        if not isinstance(item, dict):
            continue
        payment_url = str(item.get("payment_url") or "").strip()
        if payment_url and not payment_url.startswith(("https://", "http://", "/")):
            payment_url = ""
        normalized_plans.append(
            {
                "id": str(item.get("id") or "").strip(),
                "name": str(item.get("name") or "").strip(),
                "price_label": str(item.get("price_label") or "").strip(),
                "days": max(1, min(int(item.get("days") or 30), 3650)),
                "payment_url": payment_url,
            }
        )
    current["plans"] = normalized_plans or default_payment_settings()["plans"]
    return current


def load_subscription_store(site_id: str) -> dict[str, Any]:
    path = subscription_store_path(site_id)
    if not path.exists():
        return {"settings": default_settings(), "subscribers": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("settings", {})
    merged_settings = default_settings()
    merged_settings.update(data.get("settings") or {})
    merged_settings["payment"] = normalize_payment_settings(merged_settings.get("payment"))
    data["settings"] = merged_settings
    data.setdefault("subscribers", [])
    return data


def save_subscription_store(site_id: str, data: dict[str, Any]) -> None:
    path = subscription_store_path(site_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def public_subscription_settings(site_id: str) -> dict[str, Any]:
    data = load_subscription_store(site_id)
    settings = data.get("settings") or {}
    return {
        "enabled": bool(settings.get("enabled", True)),
        "tier": str(settings.get("tier") or "dosya"),
        "price_label": str(settings.get("price_label") or DEFAULT_SETTINGS["price_label"]),
        "cookie_days": int(settings.get("cookie_days") or DEFAULT_SETTINGS["cookie_days"]),
        "payment": normalize_payment_settings(settings.get("payment")),
    }


def list_subscriptions(site_id: str) -> dict[str, Any]:
    data = load_subscription_store(site_id)
    subscribers = []
    for item in data.get("subscribers", []):
        subscribers.append(
            {
                "label": item.get("label", ""),
                "tier": item.get("tier", "dosya"),
                "status": item.get("status", "active"),
                "created_at": item.get("created_at", ""),
                "expires_at": item.get("expires_at", ""),
                "last_used_at": item.get("last_used_at", ""),
            }
        )
    return {"settings": public_subscription_settings(site_id), "subscribers": subscribers}


def create_subscription_code(
    site_id: str,
    *,
    label: str = "",
    days: int = 30,
    tier: str = "dosya",
    code: str | None = None,
) -> dict[str, Any]:
    data = load_subscription_store(site_id)
    days = max(1, min(int(days or 30), 3650))
    code_value = (code or f"TG-{secrets.token_urlsafe(9).upper().replace('_', '').replace('-', '')[:12]}").strip().upper()
    code_hash = hash_code(code_value)
    expires_at = (_utc_now() + timedelta(days=days)).isoformat(timespec="seconds")
    data.setdefault("subscribers", []).append(
        {
            "code_hash": code_hash,
            "label": str(label or "Dosya aboneliği").strip(),
            "tier": str(tier or "dosya").strip(),
            "status": "active",
            "created_at": now_iso(),
            "expires_at": expires_at,
            "last_used_at": "",
        }
    )
    save_subscription_store(site_id, data)
    return {"code": code_value, "expires_at": expires_at, "tier": tier, "label": label}


def update_subscription_settings(site_id: str, settings: dict[str, Any]) -> dict[str, Any]:
    data = load_subscription_store(site_id)
    current = default_settings()
    current.update(data.get("settings") or {})
    for key in ("enabled", "tier", "price_label", "cookie_days"):
        if key in settings:
            current[key] = settings[key]
    if "payment" in settings:
        current["payment"] = normalize_payment_settings(settings.get("payment"))
    current["enabled"] = bool(current.get("enabled", True))
    current["tier"] = str(current.get("tier") or "dosya").strip()
    current["price_label"] = str(current.get("price_label") or DEFAULT_SETTINGS["price_label"]).strip()
    current["cookie_days"] = max(1, min(int(current.get("cookie_days") or 30), 3650))
    current["payment"] = normalize_payment_settings(current.get("payment"))
    data["settings"] = current
    save_subscription_store(site_id, data)
    return public_subscription_settings(site_id)


def verify_code(site_id: str, code: str, tier: str = "dosya") -> dict[str, Any]:
    code_hash = hash_code(code)
    data = load_subscription_store(site_id)
    now = _utc_now()
    for item in data.get("subscribers", []):
        if not hmac.compare_digest(str(item.get("code_hash") or ""), code_hash):
            continue
        if str(item.get("tier") or "dosya") != str(tier or "dosya"):
            return {"ok": False, "error": "Bu kod bu abonelik türü için geçerli değil."}
        if str(item.get("status") or "active") != "active":
            return {"ok": False, "error": "Bu abonelik kodu pasif durumda."}
        expires_at = _parse_datetime(item.get("expires_at"))
        if expires_at and expires_at <= now:
            return {"ok": False, "error": "Bu abonelik kodunun süresi dolmuş."}
        item["last_used_at"] = now_iso()
        save_subscription_store(site_id, data)
        return {"ok": True, "code_hash": code_hash, "expires_at": item.get("expires_at"), "tier": tier}
    return {"ok": False, "error": "Abonelik kodu bulunamadı."}


def sign_subscription_session(site_id: str, code_hash: str, expires_at: str | None, tier: str = "dosya") -> str:
    settings = public_subscription_settings(site_id)
    code_exp = _parse_datetime(expires_at)
    session_exp = _utc_now() + timedelta(days=int(settings.get("cookie_days") or 30))
    if code_exp and code_exp < session_exp:
        session_exp = code_exp
    payload = {
        "site": site_id,
        "tier": tier,
        "code_hash": code_hash,
        "exp": int(session_exp.timestamp()),
    }
    body = _b64_json(payload)
    return f"{body}.{_sign(body)}"


def verify_subscription_cookie(site_id: str, cookie_header: str | None, tier: str = "dosya") -> bool:
    if not cookie_header:
        return False
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
    except Exception:
        return False
    morsel = cookie.get(COOKIE_NAME)
    if not morsel:
        return False
    token = morsel.value
    if "." not in token:
        return False
    body, signature = token.rsplit(".", 1)
    if not hmac.compare_digest(_sign(body), signature):
        return False
    try:
        payload = _unb64_json(body)
    except Exception:
        return False
    if payload.get("site") != site_id or payload.get("tier") != tier:
        return False
    if int(payload.get("exp") or 0) <= int(_utc_now().timestamp()):
        return False
    code_hash = str(payload.get("code_hash") or "")
    data = load_subscription_store(site_id)
    for item in data.get("subscribers", []):
        if hmac.compare_digest(str(item.get("code_hash") or ""), code_hash):
            expires_at = _parse_datetime(item.get("expires_at"))
            return str(item.get("status") or "active") == "active" and (not expires_at or expires_at > _utc_now())
    return False


def dossier_article(site_id: str, slug: str) -> dict[str, Any] | None:
    for article in load_articles(site_id):
        if article.get("slug") == slug and article.get("category") == "dosya":
            return article
    return None


def resolve_attachment_path(site_id: str, attachment_url: str) -> Path | None:
    value = str(attachment_url or "").strip()
    if not value or value.startswith(("http://", "https://")):
        return None
    site = get_site(site_id)
    public_dir = project_path(site["public_dir"]).resolve()
    content_dir = project_path(site["content_file"]).parent.resolve()
    if value.startswith("/private/dosya/"):
        candidate = (content_dir / "dosya-files" / value.removeprefix("/private/dosya/")).resolve()
        return candidate if content_dir in candidate.parents else None
    if value.startswith("/"):
        candidate = (public_dir / value.lstrip("/")).resolve()
        return candidate if public_dir == candidate or public_dir in candidate.parents else None
    candidate = (content_dir / "dosya-files" / value).resolve()
    return candidate if content_dir in candidate.parents else None
