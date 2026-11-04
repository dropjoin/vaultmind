#!/usr/bin/env python3
"""Live launcher — runs the VaultMind CLI with the workspace Otari key
WITHOUT the key ever touching disk, a file, or the terminal.

The real Otari key lives in the registered `custom.otari` connection.
This launcher asks the local credential service (authd) for an
`hsurr:` surrogate in-process, puts it in the CHILD process environment
as OTARI_API_KEY (child env only — never printed, never written), and
execs the requested VaultMind command. The egress layer swaps the
surrogate for the real key on the way to api.otari.ai.

Usage:
  python3 scripts/run_live.py state
  python3 scripts/run_live.py propose --to 0x... --amount 0.005 --memo "..."
  python3 scripts/run_live.py usage
  python3 scripts/run_live.py smoke        # scripts/smoke_test.py, live

Any VaultMind/smoke exit code is passed through unchanged.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import (  # noqa: E402
    DynamicCredentialError, dynamic_credential_entry)

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "https://api.otari.ai/api/v1"


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2

    try:
        entry = dynamic_credential_entry("custom.otari")
    except DynamicCredentialError as exc:
        print(f"LIVE LAUNCH FAILED: could not obtain the stored Otari "
              f"credential surrogate: {exc}")
        return 1
    surrogate = str(entry["surrogate"]).strip()
    if not surrogate.startswith("hsurr:"):
        print("LIVE LAUNCH FAILED: credential service returned a "
              "non-surrogate value; refusing to continue.")
        return 1

    env = dict(os.environ)
    env["OTARI_API_KEY"] = surrogate
    env["OTARI_BASE_URL"] = BASE_URL
    # Per-role dashboard keys are a separate, still-manual step (see
    # docs/OTARI_FEATURES.md); make sure a stray local value cannot
    # shadow the stored workspace key during live runs.
    for var in ("OTARI_KEY_PROPOSER", "OTARI_KEY_CHECKER",
                "OTARI_KEY_REPORTER"):
        env.pop(var, None)

    if args[0] == "smoke":
        cmd = [sys.executable, str(REPO_ROOT / "scripts" / "smoke_test.py")]
        args = args[1:]
    else:
        cmd = [sys.executable, str(REPO_ROOT / "vaultmind.py")]
    return subprocess.call(cmd + args, env=env, cwd=REPO_ROOT)


if __name__ == "__main__":
    sys.exit(main())
