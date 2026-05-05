#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/growth-os}"
SERVICE_USER="${SERVICE_USER:-growthos}"
DOMAIN="${DOMAIN:-turkiyegundemi.com}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash ops/install_model_b.sh"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required."
  exit 1
fi

id -u "${SERVICE_USER}" >/dev/null 2>&1 || useradd --system --home "${APP_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"

mkdir -p "${APP_DIR}" /etc/growth-os
rsync -a --delete \
  --exclude ".git" \
  --exclude "build" \
  --exclude "dist" \
  ./ "${APP_DIR}/"

python3 -m venv "${APP_DIR}/venv"
"${APP_DIR}/venv/bin/python" -m pip install --upgrade pip

if [[ ! -f /etc/growth-os/growth-os.env ]]; then
  cp "${APP_DIR}/ops/systemd/growth-os.env.example" /etc/growth-os/growth-os.env
  password="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
  sed -i "s/change-this-long-password/${password}/" /etc/growth-os/growth-os.env
  echo "Generated admin password in /etc/growth-os/growth-os.env"
fi

chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}"
chmod 600 /etc/growth-os/growth-os.env

(cd "${APP_DIR}" && "${APP_DIR}/venv/bin/python" -m src.growth_os.sitegen --site turkiye-gundemi)
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}"

cp "${APP_DIR}/ops/systemd/growth-os.service" /etc/systemd/system/growth-os.service
systemctl daemon-reload
systemctl enable --now growth-os

if command -v nginx >/dev/null 2>&1; then
  cp "${APP_DIR}/ops/nginx/model-b-turkiyegundemi.conf" /etc/nginx/sites-available/turkiyegundemi.conf
  sed -i "s/turkiyegundemi.com/${DOMAIN}/g" /etc/nginx/sites-available/turkiyegundemi.conf
  rm -f /etc/nginx/sites-enabled/default
  ln -sf /etc/nginx/sites-available/turkiyegundemi.conf /etc/nginx/sites-enabled/turkiyegundemi.conf
  nginx -t
  systemctl reload nginx
fi

echo "Model B installed."
echo "Service: systemctl status growth-os"
echo "Admin user: $(grep '^GROWTH_OS_ADMIN_USER=' /etc/growth-os/growth-os.env | cut -d= -f2-)"
echo "Admin password: sudo grep '^GROWTH_OS_ADMIN_PASSWORD=' /etc/growth-os/growth-os.env"
