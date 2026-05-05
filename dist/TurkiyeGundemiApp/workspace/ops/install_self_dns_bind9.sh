#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/growth-os}"
SITE="${SITE:-turkiye-gundemi}"
DOMAIN="${DOMAIN:-turkiyegundemi.com}"
PRIMARY_IP="${PRIMARY_IP:-}"
SECONDARY_IP="${SECONDARY_IP:-}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo PRIMARY_IP=1.2.3.4 SECONDARY_IP=5.6.7.8 bash ops/install_self_dns_bind9.sh"
  exit 1
fi

if [[ -z "${PRIMARY_IP}" ]]; then
  echo "PRIMARY_IP is required."
  exit 1
fi

if [[ -z "${SECONDARY_IP}" ]]; then
  echo "WARNING: SECONDARY_IP is empty; ns2 will point to PRIMARY_IP. Use a real second DNS server before production."
  SECONDARY_IP="${PRIMARY_IP}"
fi

if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y bind9 bind9utils dnsutils
else
  echo "This installer currently supports apt-based Linux distributions."
  exit 1
fi

mkdir -p /etc/bind/zones
cd "${APP_DIR}"
"${APP_DIR}/venv/bin/python" -m src.growth_os.dnsgen --site "${SITE}" --primary-ip "${PRIMARY_IP}" --secondary-ip "${SECONDARY_IP}" --out-dir /tmp/growth-os-dns

cp /tmp/growth-os-dns/db."${DOMAIN}" /etc/bind/zones/db."${DOMAIN}"
cp /tmp/growth-os-dns/named.conf.options.authoritative /etc/bind/named.conf.options

if ! grep -q "db.${DOMAIN}" /etc/bind/named.conf.local; then
  cat /tmp/growth-os-dns/named.conf.local >> /etc/bind/named.conf.local
fi

named-checkconf
named-checkzone "${DOMAIN}" /etc/bind/zones/db."${DOMAIN}"
systemctl enable --now bind9
systemctl restart bind9

echo "Authoritative DNS installed for ${DOMAIN}."
echo "Open firewall UDP/TCP 53 if needed."
echo "Registrar glue records:"
echo "  ns1.${DOMAIN} -> ${PRIMARY_IP}"
echo "  ns2.${DOMAIN} -> ${SECONDARY_IP}"
echo "Registrar nameservers:"
echo "  ns1.${DOMAIN}"
echo "  ns2.${DOMAIN}"
