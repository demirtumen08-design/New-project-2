#!/usr/bin/env bash
set -euo pipefail

ADMIN_USER="${ADMIN_USER:-deploy}"
SSH_PORT="${SSH_PORT:-22}"
ALLOW_SSH_FROM="${ALLOW_SSH_FROM:-}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo ADMIN_USER=deploy bash ops/bootstrap_ubuntu_public.sh"
  exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This bootstrap supports Ubuntu/Debian apt-based servers."
  exit 1
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ca-certificates curl git rsync ufw fail2ban python3 python3-venv python3-pip \
  nginx bind9 bind9utils dnsutils certbot python3-certbot-nginx

id -u "${ADMIN_USER}" >/dev/null 2>&1 || adduser --disabled-password --gecos "" "${ADMIN_USER}"
usermod -aG sudo "${ADMIN_USER}"

install -d -m 700 -o "${ADMIN_USER}" -g "${ADMIN_USER}" "/home/${ADMIN_USER}/.ssh"
if [[ -f /root/.ssh/authorized_keys ]]; then
  cp /root/.ssh/authorized_keys "/home/${ADMIN_USER}/.ssh/authorized_keys"
  chown "${ADMIN_USER}:${ADMIN_USER}" "/home/${ADMIN_USER}/.ssh/authorized_keys"
  chmod 600 "/home/${ADMIN_USER}/.ssh/authorized_keys"
fi

cat >/etc/ssh/sshd_config.d/90-growth-os-hardening.conf <<EOF
Port ${SSH_PORT}
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
X11Forwarding no
AllowUsers ${ADMIN_USER}
EOF

ufw --force reset
ufw default deny incoming
ufw default allow outgoing
if [[ -n "${ALLOW_SSH_FROM}" ]]; then
  ufw allow from "${ALLOW_SSH_FROM}" to any port "${SSH_PORT}" proto tcp
else
  ufw allow "${SSH_PORT}/tcp"
fi
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 53/tcp
ufw allow 53/udp
ufw --force enable

systemctl enable --now fail2ban
systemctl restart ssh || systemctl restart sshd

public_ip="$(curl -4fsS https://api.ipify.org || true)"

cat <<EOF
Bootstrap complete.

Public IPv4: ${public_ip}
Admin user: ${ADMIN_USER}
SSH port: ${SSH_PORT}

Next:
1. Reconnect as ${ADMIN_USER}: ssh -p ${SSH_PORT} ${ADMIN_USER}@${public_ip}
2. Copy project to the server.
3. Run: sudo DOMAIN=turkiyegundemi.com bash ops/install_model_b.sh
4. Run DNS setup if this is ns1: sudo PRIMARY_IP=${public_ip} SECONDARY_IP=<NS2_IP> bash ops/install_self_dns_bind9.sh
EOF
