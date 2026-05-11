#!/usr/bin/env bash
set -euo pipefail

VPS_HOST="${VPS_HOST:-}"
VPS_USER="${VPS_USER:-root}"
SSH_PORT="${SSH_PORT:-22}"
DOMAIN="${DOMAIN:-turkiyegundemi.com}"
REMOTE_DIR="${REMOTE_DIR:-/tmp/growth-os-deploy}"
RUN_BOOTSTRAP="${RUN_BOOTSTRAP:-0}"
ADMIN_USER="${ADMIN_USER:-deploy}"
ALLOW_SSH_FROM="${ALLOW_SSH_FROM:-}"

if [[ -z "${VPS_HOST}" ]]; then
  echo "Set VPS_HOST first, for example:"
  echo "  VPS_HOST=203.0.113.10 VPS_USER=root bash ops/deploy_to_vps.sh"
  exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync is required on this machine. On Ubuntu/WSL: sudo apt-get install -y rsync"
  exit 1
fi

if ! command -v ssh >/dev/null 2>&1; then
  echo "ssh is required on this machine."
  exit 1
fi

SSH_TARGET="${VPS_USER}@${VPS_HOST}"
SUDO=""
if [[ "${VPS_USER}" != "root" ]]; then
  SUDO="sudo "
fi

ssh -p "${SSH_PORT}" "${SSH_TARGET}" "mkdir -p '${REMOTE_DIR}'"

rsync -az --delete \
  --exclude ".git" \
  --exclude ".venv" \
  --exclude "__pycache__" \
  --exclude "*.pyc" \
  --exclude "build" \
  --exclude "dist" \
  --exclude "release" \
  --exclude "logs" \
  -e "ssh -p ${SSH_PORT}" \
  ./ "${SSH_TARGET}:${REMOTE_DIR}/"

if [[ "${RUN_BOOTSTRAP}" == "1" ]]; then
  if [[ "${VPS_USER}" != "root" ]]; then
    echo "RUN_BOOTSTRAP=1 requires VPS_USER=root because SSH hardening edits system files."
    exit 1
  fi
  ssh -p "${SSH_PORT}" "${SSH_TARGET}" \
    "cd '${REMOTE_DIR}' && ADMIN_USER='${ADMIN_USER}' SSH_PORT='${SSH_PORT}' ALLOW_SSH_FROM='${ALLOW_SSH_FROM}' bash ops/bootstrap_ubuntu_public.sh"
  echo "Bootstrap finished. Reconnect with the hardened user, then rerun deploy if root login was disabled."
  exit 0
fi

ssh -p "${SSH_PORT}" "${SSH_TARGET}" \
  "cd '${REMOTE_DIR}' && ${SUDO}DOMAIN='${DOMAIN}' bash ops/install_model_b.sh && ${SUDO}systemctl status growth-os --no-pager -l | sed -n '1,25p' && ${SUDO}systemctl list-timers 'growth-os-*' --no-pager"

echo "Deployment finished for ${DOMAIN} on ${VPS_HOST}."
