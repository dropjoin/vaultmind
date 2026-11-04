#!/usr/bin/env python3
"""Otari smoke test — proves the gateway integration end to end.

What it does:
  1. Loads .env + config/otari-routing.yml.
  2. Lists the models the configured key can reach (auth check).
  3. Sends one tiny chat completion as the `proposer` role on its primary
     model and prints the reply plus the usage block (tokens).

Without an API key it prints a clear NOT CONFIGURED message and exits 2 —
no traceback. Run:  python3 scripts/smoke_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config as cfg  # noqa: E402
from src.otari_client import OtariClient, OtariError, OtariNotConfigured  # noqa: E402


def main() -> int:
    cfg.load_env()
    routing = cfg.load_routing_config()
    role = "proposer"
    role_cfg = routing["roles"][role]
    model = role_cfg["models"]["primary"]

    try:
        client = OtariClient(role, role_cfg)
    except OtariNotConfigured as exc:
        print(f"NOT CONFIGURED: {exc}")
        return 2

    print(f"Otari base URL : {client.base_url}")
    print(f"Role           : {role} (virtual key '{role_cfg['virtual_key']}')")
    print(f"Primary model  : {model}")

    try:
        models = client.list_models()
        print(f"Models visible : {len(models)}")
        if model in models:
            print(f"               : primary model '{model}' is reachable")
        elif models:
            print(f"               : NOTE primary model not in the visible list "
                  f"(first entries: {models[:5]})")

        result = client.chat(model, [
            {"role": "user",
             "content": "Reply with exactly: VAULTMIND-OTARI-OK"},
        ])
    except OtariError as exc:
        print(f"GATEWAY ERROR: {exc}")
        return 1

    print(f"Reply          : {result['content'].strip()[:120]}")
    print(f"Served by      : {result['model']}")
    print(f"Usage          : {result['usage']}")
    print("SMOKE TEST OK — the Otari integration works.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
