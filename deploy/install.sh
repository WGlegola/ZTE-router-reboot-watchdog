#!/usr/bin/env bash
# Install the ZTE watchdog as a systemd service on Raspberry Pi OS.
#
# Uses a self-contained virtualenv by default (no --break-system-packages),
# which is the supported way to install Python apps on Bookworm. The venv lives
# at <repo>/.venv; the systemd unit is rewritten to run that venv's python.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="${SUDO_USER:-$(whoami)}"
VENV="$REPO_DIR/.venv"

echo "==> Installing python3-venv"
sudo apt-get update -qq
sudo apt-get install -y python3-venv

echo "==> Creating virtualenv at $VENV"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -e "$REPO_DIR" -q   # editable: git pull + restart picks up changes

echo "==> Config directory /etc/zte-watchdog"
sudo mkdir -p /etc/zte-watchdog
sudo cp -n "$REPO_DIR/config.example.toml" /etc/zte-watchdog/config.toml

if [ ! -f /etc/zte-watchdog.env ]; then
  echo "==> Creating /etc/zte-watchdog.env (enter admin password)"
  read -rsp "ZTE admin password: " PW; echo
  printf 'ZTE_IP=192.168.7.1\nZTE_PASSWORD=%s\n' "$PW" | sudo tee /etc/zte-watchdog.env >/dev/null
  sudo chmod 600 /etc/zte-watchdog.env
fi

echo "==> Installing systemd unit (User=$USER_NAME, venv python)"
sed -e "s#^User=.*#User=$USER_NAME#" \
    -e "s#^ExecStart=.*#ExecStart=$VENV/bin/python -m zte_watchdog --config /etc/zte-watchdog/config.toml#" \
    "$REPO_DIR/deploy/zte-watchdog.service" \
  | sudo tee /etc/systemd/system/zte-watchdog.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now zte-watchdog

echo "==> Done. Follow logs with: journalctl -u zte-watchdog -f"
