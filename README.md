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
sudo ./deploy/install.sh          # creates a .venv, installs the service, prompts for password
journalctl -u zte-watchdog -f     # watch it
```

The admin password is read from `ZTE_PASSWORD` in `/etc/zte-watchdog.env`
(mode 600) — it is never stored in the repo or logs.

## Supervised mode (testing / debugging): `--heartbeat`

```bash
ZTE_PASSWORD='...' python3 -m zte_watchdog --heartbeat
```

Runs the **same continuous monitoring as the daemon**, but prints a live
heartbeat each cycle (reachability, gateway `ppp`/`modem` state, and signal
metrics) and **pauses to ask `reboot? [y/N]` only when a drop is actually
detected** — never while things are healthy. Decline and it keeps watching,
re-asking after the cooldown. Add `--once` to run a single cycle and exit.

Use this to watch the connection and, the first time a real drop happens,
confirm the reboot works before trusting the autonomous daemon (the
`REBOOT_DEVICE` token is inferred from retail firmware; the daemon also warns
if a reboot is sent but nothing recovers).

## Usage

```bash
python3 -m zte_watchdog                 # autonomous daemon (default)
python3 -m zte_watchdog --once          # single evaluation, then exit
python3 -m zte_watchdog --log-signal    # daemon + log signal metrics each cycle
python3 -m zte_watchdog --heartbeat     # supervised: live readout, ask before reboot on drop
```

Tune with `--interval` (calm cadence while healthy), `--fail-interval` (faster
cadence once a failure is detected, so an outage escalates to the reboot
threshold quickly without polling hard while up), `--fails`, `--cooldown`,
`--max-reboots-per-hour`, or `config.toml` (see `config.example.toml`).

## Logging

The daemon logs one line per **state change** to stderr (captured by journald),
and is otherwise silent while healthy — it does **not** print a line per check
(that's `--heartbeat` only). You'll see:

- `INFO no internet (fails=1/3, …)` as an outage ramps (one line per new strike),
- `WARNING sustained hung session — rebooting gateway` + `reboot sent (response=…)`
  on **every reboot it performs**,
- `INFO reboot confirmed: gateway recovered` (or a `WARNING` that the reboot did
  nothing) after the cooldown, and `INFO internet recovered` when it comes back,
- `ERROR reboot cap reached (…/hr) — backing off` once, during a real outage.

```bash
journalctl -u zte-watchdog -f                    # live
journalctl -u zte-watchdog | grep -iE 'reboot|outage'   # just restarts + outages
```

Set `log_level = "WARNING"` to hide the INFO chatter and keep only reboots and
problems. Retention is journald's (systemd) — the app writes no log files of its
own. Signal metrics are off unless you pass `--log-signal`.

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
