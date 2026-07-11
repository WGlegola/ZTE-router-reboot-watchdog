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

# Run the venv/pip steps as the target user (not root under sudo) so the venv is
# owned by the same user the service runs as. No-op when not invoked via sudo.
as_user() { if [ "$(id -u)" -eq 0 ]; then sudo -u "$USER_NAME" "$@"; else "$@"; fi; }

echo "==> Installing python3-venv"
sudo apt-get update -qq
sudo apt-get install -y python3-venv

echo "==> Creating virtualenv at $VENV (owned by $USER_NAME)"
as_user python3 -m venv "$VENV"
as_user "$VENV/bin/pip" install --upgrade pip -q
as_user "$VENV/bin/pip" install -e "$REPO_DIR" -q   # editable: git pull + restart picks up changes

echo "==> Config directory /etc/zte-watchdog"
sudo mkdir -p /etc/zte-watchdog
sudo cp -n "$REPO_DIR/config.example.toml" /etc/zte-watchdog/config.toml

if [ ! -f /etc/zte-watchdog.env ]; then
  if [ ! -t 0 ]; then
    echo "!! /etc/zte-watchdog.env is missing and there's no terminal to read the password." >&2
    echo "!! Create it manually, e.g.:" >&2
    echo "!!   printf 'ZTE_IP=192.168.7.1\\nZTE_PASSWORD=YOURPASS\\n' | sudo install -m 600 /dev/stdin /etc/zte-watchdog.env" >&2
    exit 1
  fi
  echo "==> Creating /etc/zte-watchdog.env (enter admin password)"
  read -rsp "ZTE admin password: " PW; echo
  # Create the file 0600 *before* writing the secret (tee keeps an existing
  # file's mode), so there is no world-readable window.
  sudo install -m 600 /dev/null /etc/zte-watchdog.env
  printf 'ZTE_IP=192.168.7.1\nZTE_PASSWORD=%s\n' "$PW" | sudo tee /etc/zte-watchdog.env >/dev/null
fi

echo "==> Installing systemd unit (User=$USER_NAME, venv python)"
sed -e "s#^User=.*#User=$USER_NAME#" \
    -e "s#^ExecStart=.*#ExecStart=$VENV/bin/python -m zte_watchdog --config /etc/zte-watchdog/config.toml#" \
    "$REPO_DIR/deploy/zte-watchdog.service" \
  | sudo tee /etc/systemd/system/zte-watchdog.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now zte-watchdog

echo "==> Done. Follow logs with: journalctl -u zte-watchdog -f"
