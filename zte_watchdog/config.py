"""Config loading with precedence: CLI > env > TOML file > defaults."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields

from .connectivity import parse_target


@dataclass
class Config:
    ip: str = "192.168.7.1"
    password: str | None = None
    targets: list[str] = field(
        default_factory=lambda: ["1.1.1.1:443", "8.8.8.8:53", "9.9.9.9:443"]
    )
    interval: int = 30
    fail_interval: int = 5      # faster cadence once a failure is being counted
    fails: int = 3
    cooldown: int = 300
    max_reboots_per_hour: int = 3
    log_signal: bool = False
    metrics_interval: int = 30
    health_host: str = "127.0.0.1"   # bind for the HTTP health endpoint
    health_port: int = 0             # 0 disables the health endpoint
    log_level: str = "INFO"

    @property
    def base_url(self) -> str:
        return f"http://{self.ip}"

    @property
    def parsed_targets(self) -> list[tuple[str, int]]:
        return [parse_target(t) for t in self.targets]


def load_config(path: str | None = None, env: dict | None = None,
                cli: dict | None = None) -> Config:
    env = os.environ if env is None else env
    cli = cli or {}
    # password comes only from ZTE_PASSWORD — never from a config file or CLI.
    loadable = {f.name for f in fields(Config) if f.name != "password"}

    data: dict = {}
    if path:
        with open(path, "rb") as fh:
            data.update({k: v for k, v in tomllib.load(fh).items() if k in loadable})

    if env.get("ZTE_IP"):
        data["ip"] = env["ZTE_IP"]
    if env.get("ZTE_PASSWORD"):
        data["password"] = env["ZTE_PASSWORD"]

    for k, v in cli.items():
        if k in loadable and v is not None:
            data[k] = v

    return Config(**data)
