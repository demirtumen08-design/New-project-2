from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import get_site, project_path


def ensure_fqdn(value: str) -> str:
    return value.rstrip(".") + "."


def soa_mailbox(value: str) -> str:
    # DNS SOA mailbox syntax uses a dot instead of @.
    local, _, domain = value.partition("@")
    if not domain:
        return ensure_fqdn(value)
    return ensure_fqdn(f"{local}.{domain}")


def serial() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H")


def valid_ipv4(value: str) -> bool:
    match = re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", value)
    if not match:
        return False
    return all(0 <= int(part) <= 255 for part in value.split("."))


def render_record(record: dict[str, Any], primary_ip: str, secondary_ip: str) -> str:
    name = record["name"]
    record_type = record["type"].upper()
    value = str(record.get("value", "")).replace("PRIMARY_IPV4", primary_ip).replace("SECONDARY_IPV4", secondary_ip)
    if record_type in {"A", "AAAA"}:
        return f"{name:<16} IN {record_type:<5} {value}"
    if record_type == "TXT":
        escaped = value.replace('"', r"\"")
        return f'{name:<16} IN TXT   "{escaped}"'
    if record_type == "CAA":
        flag = int(record.get("flag", 0))
        tag = record.get("tag", "issue")
        escaped = value.replace('"', r"\"")
        return f'{name:<16} IN CAA   {flag} {tag} "{escaped}"'
    if record_type in {"CNAME", "MX"}:
        return f"{name:<16} IN {record_type:<5} {value}"
    raise ValueError(f"Unsupported DNS record type: {record_type}")


def render_zone(site: dict[str, Any], primary_ip: str, secondary_ip: str) -> str:
    dns = site["dns"]
    zone = dns["zone"]
    ttl = int(dns.get("ttl", 300))
    primary_ns = ensure_fqdn(dns["primary_ns"])
    secondary_ns = ensure_fqdn(dns["secondary_ns"])
    soa_email = soa_mailbox(dns.get("soa_email", f"dns@{zone}"))
    lines = [
        f"$ORIGIN {ensure_fqdn(zone)}",
        f"$TTL {ttl}",
        f"@                IN SOA   {primary_ns} {soa_email} (",
        f"                              {serial()} ; serial",
        "                              900        ; refresh",
        "                              300        ; retry",
        "                              1209600    ; expire",
        "                              300        ; minimum",
        "                         )",
        f"@                IN NS    {primary_ns}",
        f"@                IN NS    {secondary_ns}",
    ]
    lines.extend(render_record(record, primary_ip, secondary_ip) for record in dns.get("records", []))
    return "\n".join(lines) + "\n"


def render_named_conf(zone: str, zone_path: str) -> str:
    return f'''zone "{zone}" {{
    type master;
    file "{zone_path}";
    allow-transfer {{ none; }};
}};
'''


def render_options() -> str:
    return """options {
    directory "/var/cache/bind";
    recursion no;
    allow-query { any; };
    listen-on { any; };
    listen-on-v6 { none; };
    dnssec-validation auto;
};
"""


def generate(site_id: str, primary_ip: str, secondary_ip: str | None = None, out_dir: str | None = None) -> Path:
    if not valid_ipv4(primary_ip):
        raise SystemExit(f"Invalid primary IPv4: {primary_ip}")
    secondary_ip = secondary_ip or primary_ip
    if not valid_ipv4(secondary_ip):
        raise SystemExit(f"Invalid secondary IPv4: {secondary_ip}")
    site = get_site(site_id)
    dns = site.get("dns") or {}
    if dns.get("mode") != "self_hosted_bind9":
        raise SystemExit(f"{site_id} does not define self_hosted_bind9 DNS.")
    output = project_path(out_dir or "ops/dns/generated")
    output.mkdir(parents=True, exist_ok=True)
    zone_name = dns["zone"]
    zone_file = output / f"db.{zone_name}"
    zone_file.write_text(render_zone(site, primary_ip, secondary_ip), encoding="utf-8")
    (output / "named.conf.local").write_text(render_named_conf(zone_name, f"/etc/bind/zones/db.{zone_name}"), encoding="utf-8")
    (output / "named.conf.options.authoritative").write_text(render_options(), encoding="utf-8")
    (output / "README.md").write_text(
        f"""# Generated DNS files

Zone: `{zone_name}`

Primary IPv4: `{primary_ip}`
Secondary IPv4: `{secondary_ip}`

Copy `db.{zone_name}` to `/etc/bind/zones/db.{zone_name}` and include `named.conf.local` from BIND.

Registrar side needs glue/host records:

- `{dns["primary_ns"]}` -> `{primary_ip}`
- `{dns["secondary_ns"]}` -> `{secondary_ip}`

Then set domain nameservers to:

- `{dns["primary_ns"]}`
- `{dns["secondary_ns"]}`
""",
        encoding="utf-8",
    )
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate authoritative BIND DNS zone files.")
    parser.add_argument("--site", default="turkiye-gundemi")
    parser.add_argument("--primary-ip", required=True)
    parser.add_argument("--secondary-ip")
    parser.add_argument("--out-dir")
    args = parser.parse_args(argv)
    out = generate(args.site, args.primary_ip, args.secondary_ip, args.out_dir)
    print(f"DNS files generated: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
