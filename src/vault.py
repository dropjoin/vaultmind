"""Live AgentVault state reader — Arbitrum Sepolia via raw JSON-RPC.

Reads the real deployed AgentVault (see VAULTMIND_VAULT_ADDRESS) with
eth_call. No web3 dependency: selectors are Keccak-256 of the function
signatures from src/AgentVault.sol, ABI kept in src/agentvault_abi.json
(extracted from the project's own Foundry artifact).

Public RPC notes (observed 2026-11-04): Arbitrum's official Sepolia
endpoint answers 403 to the default Python urllib User-Agent, so every
request carries an explicit UA; several endpoints are tried in order.
The transport is `requests`, not urllib: probing the three endpoints
with the same eth_call payload, urllib failed 15 of 75 calls (6x
http.client.IncompleteRead and 2x RemoteDisconnected on the first
endpoint alone), and IncompleteRead is not a URLError subclass, so it
escaped this reader's failover loop and crashed the CLI outright
("ERROR: IncompleteRead(103 bytes read)"). `requests` read the same
75 calls without a single failure and roughly 3x faster.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

import requests

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
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def is_valid_address(addr: object) -> bool:
    """True only for a well-formed 0x + 40 hex chars address."""
    return isinstance(addr, str) and ADDRESS_RE.match(addr) is not None


def validate_address(addr: str, what: str) -> str:
    """Return the address unchanged, or raise ValueError.

    Calldata is built by hand in this module, so a malformed address
    must fail loudly here instead of being silently padded into a
    different address (or the zero address) inside _enc_address.
    """
    if not is_valid_address(addr):
        raise ValueError(
            f"Invalid {what}: {addr!r} — expected 0x followed by "
            "40 hex characters.")
    return addr


def unit_label(token: str) -> str:
    """Display unit for amounts of a token: ETH for native, else base units."""
    return "ETH" if str(token).lower() == ZERO_ADDRESS else "base units"


def format_amount(amount: int, token: str) -> str:
    """Human-readable amount string for a token.

    Native ETH uses the exact 18-decimal rendering. Other tokens have
    unknown decimals (no decimals() read), so their amounts are shown
    as raw base units rather than a fake ETH decimal.
    """
    if str(token).lower() == ZERO_ADDRESS:
        return wei_to_eth_str(amount)
    return str(amount)
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
    return validate_address(addr, "address").lower()[2:].rjust(64, "0")


def _word_to_address(word: str) -> str:
    if not isinstance(word, str) or len(word) < 42 or not word.startswith("0x"):
        raise VaultReadError(
            f"Truncated eth_call result, expected a 32-byte word: {word!r}")
    return "0x" + word[-40:]


def _word_to_int(raw: str, what: str) -> int:
    """Parse one 32-byte eth_call word, failing as VaultReadError."""
    if not isinstance(raw, str) or len(raw) < 66 or not raw.startswith("0x"):
        raise VaultReadError(
            f"Truncated eth_call result for {what}, expected a 32-byte "
            f"word: {raw!r}")
    try:
        return int(raw, 16)
    except ValueError as exc:
        raise VaultReadError(
            f"Unparseable eth_call result for {what}: {raw!r}") from exc


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
        self.vault = validate_address(
            vault_address or os.environ.get(
                "VAULTMIND_VAULT_ADDRESS", DEFAULT_VAULT),
            "vault address")
        env_rpcs = os.environ.get("ARB_SEPOLIA_RPC", "")
        self.rpcs = rpcs or ([r.strip() for r in env_rpcs.split(",") if r.strip()]
                             or DEFAULT_RPCS)
        self.timeout = timeout

    # -- transport ------------------------------------------------------
    def _eth_call(self, data: str) -> str:
        payload = {
            "jsonrpc": "2.0", "id": 1, "method": "eth_call",
            "params": [{"to": self.vault, "data": "0x" + data}, "latest"],
        }
        last_err: Exception | None = None
        for rpc in self.rpcs:
            try:
                resp = requests.post(
                    rpc, json=payload, timeout=self.timeout,
                    headers={"Content-Type": "application/json",
                             "User-Agent": USER_AGENT})
                resp.raise_for_status()
                out = resp.json()
                if not isinstance(out, dict):
                    raise VaultReadError(
                        f"Malformed JSON-RPC response from {rpc}: "
                        f"{str(out)[:120]}")
                if "error" in out:
                    raise VaultReadError(f"RPC error from {rpc}: {out['error']}")
                result = out.get("result")
                if not isinstance(result, str) or not result.startswith("0x"):
                    raise VaultReadError(
                        f"Malformed JSON-RPC response from {rpc}: missing "
                        f"or non-hex 'result': {str(result)[:120]}")
                return result
            except (requests.RequestException, ValueError,
                    VaultReadError) as exc:
                # Any transport failure (a truncated body surfaces in
                # requests as ChunkedEncodingError) moves on to the
                # next endpoint instead of crashing the run.
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
        return _word_to_int(self._call("frozen()"), "frozen()") != 0

    def allowed_recipient(self, who: str) -> bool:
        return _word_to_int(self._call(
            "allowedRecipient(address)", _enc_address(who)),
            "allowedRecipient(address)") != 0

    def get_policy(self, token: str) -> Policy:
        raw = self._call("getPolicy(address)", _enc_address(token))
        if len(raw) < 2 + 4 * 64:
            raise VaultReadError(
                "Truncated eth_call result for getPolicy(address), "
                f"expected 4 words: {raw!r}")
        try:
            words = [int(raw[2 + i * 64: 2 + (i + 1) * 64], 16)
                     for i in range(4)]
        except ValueError as exc:
            raise VaultReadError(
                f"Unparseable eth_call result for getPolicy(address): "
                f"{raw!r}") from exc
        return Policy(per_tx_cap=words[0], daily_cap=words[1],
                      spent_today=words[2], configured=words[3] != 0)

    def balance_of(self, token: str) -> int:
        return _word_to_int(self._call("balanceOf(address)",
                                       _enc_address(token)),
                            "balanceOf(address)")

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
