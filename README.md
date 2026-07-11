# ZTE MC801A Reboot Watchdog

Always-on watchdog (for a Raspberry Pi on the same LAN) that detects the ZTE
MC801A "session up but dead" hang and **automatically reboots the gateway**,
with guards against false positives and reboot storms.

Verified against firmware `BD_TMOPLMC801AV1.0.0B07` (T-Mobile PL) at
`http://192.168.7.1`.

## How it works

Every `interval` seconds it checks external reachability (raw-IP TCP to
Cloudflare/Google/Quad9) and the gateway's own `ppp_status`. It reboots only
when the internet is dead **and** the gateway is reachable **and** it reports
`ppp_connected` — the hung-session signature — after `fails` consecutive
checks. A cooldown and a max-reboots-per-hour cap prevent reboot storms during
real tower outages. Weak signal never triggers a reboot (it can't fix RF).

## Install (Raspberry Pi OS Bookworm)

```bash
git clone <this repo> && cd ZTE-router-reboot-watchdog
sudo ./deploy/install.sh          # installs deps, service, prompts for password
journalctl -u zte-watchdog -f     # watch it
```

The admin password is read from `ZTE_PASSWORD` in `/etc/zte-watchdog.env`
(mode 600) — it is never stored in the repo or logs.

## Test everything first: `--heartbeat`

```bash
ZTE_PASSWORD='...' python3 -m zte_watchdog --heartbeat
```

Prints reachability, gateway `ppp`/`modem` state, and parsed signal metrics,
then asks `Reboot gateway now? [y/N]`. This exercises every layer — including
the reboot path — under your eye. **Run it once to confirm the reboot actually
works before trusting the daemon** (the `REBOOT_DEVICE` token is inferred from
retail firmware; if it doesn't reboot, open an issue with the web-UI JS).

## Usage

```bash
python3 -m zte_watchdog                 # autonomous daemon (default)
python3 -m zte_watchdog --once          # single evaluation, then exit
python3 -m zte_watchdog --log-signal    # daemon + log signal metrics each cycle
python3 -m zte_watchdog --heartbeat     # interactive readout + manual reboot
```

Tune with `--interval`, `--fails`, `--cooldown`, `--max-reboots-per-hour`, or
`config.toml` (see `config.example.toml`).

## Remote access (CGNAT note)

The gateway's WAN is CGNAT (`10.x`), so there is no inbound path from the
internet. To reach the Pi remotely, install a mesh VPN on it
(`curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up`) and
connect to that. Wire the Pi to the gateway over **Ethernet** so the watchdog
isn't subject to Wi-Fi issues.

## Development

```bash
python3 -m pytest -v      # unit tests: no network, no sleeps
```

Signal/reboot live paths are exercised manually via `--heartbeat`, not in CI.
