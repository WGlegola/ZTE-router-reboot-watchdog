#!/usr/bin/env bash
# Install the ZTE watchdog as a systemd service on Raspberry Pi OS.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="${SUDO_USER:-$(whoami)}"

echo "==> Installing python3-requests"
sudo apt-get update -qq
sudo apt-get install -y python3-requests

echo "==> Installing package for $USER_NAME"
sudo python3 -m pip install --break-system-packages "$REPO_DIR" \
  || sudo pip3 install "$REPO_DIR"

echo "==> Config directory /etc/zte-watchdog"
sudo mkdir -p /etc/zte-watchdog
sudo cp -n "$REPO_DIR/config.example.toml" /etc/zte-watchdog/config.toml

if [ ! -f /etc/zte-watchdog.env ]; then
  echo "==> Creating /etc/zte-watchdog.env (enter admin password)"
  read -rsp "ZTE admin password: " PW; echo
  printf 'ZTE_IP=192.168.7.1\nZTE_PASSWORD=%s\n' "$PW" | sudo tee /etc/zte-watchdog.env >/dev/null
  sudo chmod 600 /etc/zte-watchdog.env
fi

echo "==> Installing systemd unit (User=$USER_NAME)"
sed "s/^User=.*/User=$USER_NAME/" "$REPO_DIR/deploy/zte-watchdog.service" \
  | sudo tee /etc/systemd/system/zte-watchdog.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now zte-watchdog

echo "==> Done. Follow logs with: journalctl -u zte-watchdog -f"
