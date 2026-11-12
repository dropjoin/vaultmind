"""VaultMind configuration loading.

Reads `.env` (repo root) into the environment without overriding variables
that are already set, and loads the Otari routing config YAML.
No third-party dotenv dependency on purpose.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTING_CONFIG_PATH = REPO_ROOT / "config" / "otari-routing.yml"
LEDGER_PATH = REPO_ROOT / "data" / "usage-ledger.jsonl"

DEFAULT_BASE_URL = "https://api.otari.ai/api/v1"


def _unquote(value: str) -> str:
    """Strip one pair of matching surrounding quotes, nothing else.

    The old strip('"').strip("'") ate unmatched trailing quotes, so a
    value ending in a quote character silently lost it.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def load_env(env_path: Path | None = None) -> None:
    """Minimal .env loader: KEY=VALUE lines, existing env wins."""
    path = env_path or (REPO_ROOT / ".env")
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = _unquote(value.strip())
        if key and key not in os.environ:
            os.environ[key] = value


def load_routing_config(path: Path | None = None) -> dict:
    with open(path or ROUTING_CONFIG_PATH, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or not isinstance(data.get("roles"), dict):
        raise ValueError(
            f"Routing config {path or ROUTING_CONFIG_PATH} is empty or "
            "has no 'roles' mapping — expected config/otari-routing.yml.")
    return data


def otari_base_url() -> str:
    """Gateway base URL; an empty/blank value falls back to the default.

    OTARI_BASE_URL="" used to produce an empty base URL, and the client
    then failed with an opaque 'unknown url type' instead of talking
    to the hosted gateway.
    """
    configured = os.environ.get("OTARI_BASE_URL", "").strip()
    return (configured or DEFAULT_BASE_URL).rstrip("/")


def role_api_key(role_cfg: dict) -> str | None:
    """Per-role virtual key if configured, else the shared OTARI_API_KEY."""
    key_env = role_cfg.get("key_env")
    if key_env and os.environ.get(key_env):
        return os.environ[key_env]
    return os.environ.get("OTARI_API_KEY") or None
