"""Live AgentVault state reader — Arbitrum Sepolia via raw JSON-RPC.

Reads the real deployed AgentVault (see VAULTMIND_VAULT_ADDRESS) with
eth_call. No web3 dependency: selectors are Keccak-256 of the function
signatures from src/AgentVault.sol, ABI kept in src/agentvault_abi.json
(extracted from the project's own Foundry artifact).

Public RPC notes (observed 2026-11-04): Arbitrum's official Sepolia
endpoint answers 403 to the default Python urllib User-Agent, so every
request carries an explicit UA; several endpoints are tried in order.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

try:
    from Crypto.Hash import keccak as _keccak

    def _selector(signature: str) -> str:
        k = _keccak.new(digest_bits=256)
        k.update(signature.encode())
        return k.hexdigest()[:8]
except ImportError:  # pragma: no cover — pycryptodome is present in our env
    _FALLBACK = {  # verified against `cast sig` 2026-11-04
        "owner()": "8da5cb5b",
        "agent()": "f5ff5c76",
        "frozen()": "054f7d9c",
        "allowedRecipient(address)": "db846026",
        "getPolicy(address)": "3791dc6a",
        "balanceOf(address)": "70a08231",
    }

    def _selector(signature: str) -> str:
        return _FALLBACK[signature]


ZERO_ADDRESS = "0x" + "0" * 40
USER_AGENT = "vaultmind/0.1 (otari-hackathon devs-wilding)"
DEFAULT_VAULT = "0x0344c57616d0ff50608D85B1852C5e3E3C87d1C3"
DEFAULT_RPCS = [
    "https://sepolia-rollup.arbitrum.io/rpc",
    "https://arbitrum-sepolia-rpc.publicnode.com",
    "https://arbitrum-sepolia.gateway.tenderly.co",
]


class VaultReadError(Exception):
    pass


@dataclass
class Policy:
    per_tx_cap: int
    daily_cap: int
    spent_today: int
    configured: bool


@dataclass
class VaultState:
    address: str
    owner: str
    agent: str
    frozen: bool
    token: str
    policy: Policy
    balance: int  # wei (native) or token base units

    def recipient_allowed(self, reader: "VaultReader", who: str) -> bool:
        return reader.allowed_recipient(who)


def _enc_address(addr: str) -> str:
    return addr.lower().replace("0x", "").rjust(64, "0")


def _word_to_address(word: str) -> str:
    return "0x" + word[-40:]


def wei_to_eth_str(wei: int) -> str:
    """Exact decimal ETH string for a wei amount (no float rounding)."""
    sign = "-" if wei < 0 else ""
    wei = abs(wei)
    whole, frac = divmod(wei, 10**18)
    if frac == 0:
        return f"{sign}{whole}"
    return f"{sign}{whole}.{str(frac).rjust(18, '0').rstrip('0')}"


class VaultReader:
    def __init__(self, vault_address: str | None = None,
                 rpcs: list[str] | None = None, timeout: float = 20.0):
        self.vault = vault_address or os.environ.get(
            "VAULTMIND_VAULT_ADDRESS", DEFAULT_VAULT)
        env_rpcs = os.environ.get("ARB_SEPOLIA_RPC", "")
        self.rpcs = rpcs or ([r.strip() for r in env_rpcs.split(",") if r.strip()]
                             or DEFAULT_RPCS)
        self.timeout = timeout

    # -- transport ------------------------------------------------------
    def _eth_call(self, data: str) -> str:
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "eth_call",
            "params": [{"to": self.vault, "data": "0x" + data}, "latest"],
        }).encode()
        last_err: Exception | None = None
        for rpc in self.rpcs:
            req = urllib.request.Request(
                rpc, data=payload,
                headers={"Content-Type": "application/json",
                         "User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    out = json.loads(resp.read().decode())
                if "error" in out:
                    raise VaultReadError(f"RPC error from {rpc}: {out['error']}")
                return out["result"]
            except (urllib.error.URLError, TimeoutError, ValueError,
                    VaultReadError) as exc:
                last_err = exc
        raise VaultReadError(
            f"All Arbitrum Sepolia RPC endpoints failed: {last_err}")

    def _call(self, signature: str, args: str = "") -> str:
        return self._eth_call(_selector(signature) + args)

    # -- views ----------------------------------------------------------
    def owner(self) -> str:
        return _word_to_address(self._call("owner()"))

    def agent(self) -> str:
        return _word_to_address(self._call("agent()"))

    def frozen(self) -> bool:
        return int(self._call("frozen()"), 16) != 0

    def allowed_recipient(self, who: str) -> bool:
        return int(self._call("allowedRecipient(address)",
                              _enc_address(who)), 16) != 0

    def get_policy(self, token: str) -> Policy:
        raw = self._call("getPolicy(address)", _enc_address(token))
        words = [int(raw[2 + i * 64: 2 + (i + 1) * 64], 16) for i in range(4)]
        return Policy(per_tx_cap=words[0], daily_cap=words[1],
                      spent_today=words[2], configured=words[3] != 0)

    def balance_of(self, token: str) -> int:
        return int(self._call("balanceOf(address)", _enc_address(token)), 16)

    def read_state(self, token: str = ZERO_ADDRESS) -> VaultState:
        return VaultState(
            address=self.vault,
            owner=self.owner(),
            agent=self.agent(),
            frozen=self.frozen(),
            token=token,
            policy=self.get_policy(token),
            balance=self.balance_of(token),
        )
