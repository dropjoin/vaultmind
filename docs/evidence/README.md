# Live evidence — 2026-11-04

Two end-to-end runs of VaultMind against the **live** Otari gateway
(real workspace key, fetched at runtime by `scripts/run_live.py` — the
key itself is never on disk) and the **live** AgentVault on Arbitrum
Sepolia. Raw outputs, unedited.

**Run 1 — the funding wall.** The workspace balance was $0.00, so the
gateway refused every chat completion and VaultMind degraded to its
deterministic mirror, exactly as designed.

**Run 2 — the funded run.** The $20 starter credit landed (voucher
redeemed on the org billing page), and the same commands produced the
full proposer → checker → reporter flow with real model text and real
token counts. Run 2 is the current evidence; run 1 is kept because the
degradation path is part of the design.

## Run 1 files (balance $0.00)

| File | What it shows |
|---|---|
| `smoke-test.txt` | Gateway auth OK, 159 models visible, configured primary reachable — then the chat call is refused (see "The funding wall") |
| `vault-state.txt` | Live vault read: caps 0.01 / 0.025 ETH, spent today 0.01 ETH, balance 0.04 ETH, demo recipient allowlisted |
| `propose-pass.txt` | 0.005 ETH to the allowlisted service → **PASS** card, exit 0 |
| `propose-reject.txt` | 0.5 ETH → **REJECT** card, exit 3, three independent policy reasons |
| `usage-ledger-live.jsonl` | Every gateway attempt of both proposes: per role, primary then fallback (failover engaged), each refused pre-dispatch |

## The funding wall (why run 1 has no model text, honestly)

The workspace balance was **$0.00**: the announced $20 starter credit
for the first 200 Otari sign-ups had not appeared (the dashboard showed
$0.00, and the gateway itself said so). Every chat completion —
including models priced at $0.00 in the catalog — was refused before
dispatch:

```
HTTP 402 · {"detail": "Insufficient funds ($0.00) to serve this request.",
            "code": "insufficient_funds"}
```

So in run 1 the three roles were *attempted* live (primary +
fallback each, all ledgered), the gateway refused them all, and
VaultMind degraded exactly as designed: the deterministic policy
mirror decided both verdicts and the reporter fell back to the
template card. No model output is faked anywhere in this repo.
(One cosmetic note: the PASS card in `propose-pass.txt` carries the
older fallback wording "no working Otari key"; the string was
clarified in the next commit — the key worked, the balance was empty.)

## The IncompleteRead crash (found and fixed between the runs)

With the balance in place, `propose` twice died before any model call:

```
ERROR: IncompleteRead(103 bytes read)   ·   exit 1
```

Root cause: the vault reader (`src/vault.py`) fetched JSON-RPC over
**urllib**, and its failover loop only caught `URLError`/`TimeoutError`.
Public RPC endpoints intermittently truncate response bodies, and
`http.client.IncompleteRead` is not a `URLError` subclass — so it
escaped the loop entirely: no failover, hard crash. A controlled probe
(same eth_call payload, 25 calls per endpoint × 3 endpoints) failed
**15 of 75** urllib calls (6× IncompleteRead on the first endpoint)
and **0 of 75** with `requests`. The reader's transport now uses
`requests`; any transport failure moves on to the next endpoint.
(The Otari client already normalised `http.client` errors, which is
why gateway-side drops degraded into failover instead of crashing —
see the funded ledger.)

## Run 2 files (balance $20.00, after the fix)

| File | What it shows |
|---|---|
| `smoke-funded.txt` | Full pass: 162 models visible, primary `moonshotai/kimi-k2.6` answers for real (76 tokens), exit 0 |
| `vault-state-funded.txt` | Live vault read via the fixed transport: caps 0.01 / 0.025 ETH, balance 0.04 ETH, demo recipient allowlisted, exit 0 |
| `propose-pass-funded.txt` | 0.005 ETH to the allowlisted service → **PASS**, exit 0 — proposer, checker and reporter all model-backed; the card is the reporter's own prose, not the template |
| `propose-reject-funded.txt` | 0.5 ETH → **REJECT**, exit 3 — the deterministic floor is decisive (per-tx cap, daily cap, balance), so by design no checker LLM call is made; the reporter model still writes the card |
| `usage-ledger-funded.jsonl` | Every gateway attempt since funding landed (see below) |
| `usage-funded.txt` | The `usage` command's cumulative summary over the whole local ledger (both runs; the per-run split is the jsonl extracts) |

`usage-ledger-funded.jsonl` holds 12 entries covering three proposes:
a diagnostic PASS run made while pinning down the IncompleteRead bug
(pre-fix; it completed, slowly, on failover), then the two evidence
proposes above. Totals across the 12 entries: **5,661 tokens,
≈ $0.0063 estimated cost, 8 successful model calls, 4 transport
errors — all four on the `moonshotai/kimi-k2.6` primary, all four
recovered by failover** (proposer → `deepseek/deepseek-v3.2`,
checker → `z-ai/glm-4.7`). Nothing degraded silently: every error is
in the ledger with its note, and no verdict in run 2 came from the
deterministic mirror alone — the PASS was confirmed by the checker
model, the REJECT rests on the deterministic floor by design.

## What these runs prove

- The stored workspace key authenticates against the hosted gateway
  (`GET /models` → 200; wrong-key control earlier → 401), and with a
  balance the gateway serves real completions on the configured
  catalog models.
- The routing config's models are real catalog IDs (the blog-era
  `mzai:` spelling and the docs' `gpt-5-nano` / `claude-haiku-4-5`
  examples do not exist in the hosted catalog — see NOTES.md).
- Failover engages on gateway refusals *and* on transport drops, per
  role, and every attempt is written to the usage ledger with its
  error.
- The on-chain half is fully live: verdicts are computed from the
  vault's actual caps, spend and allowlist, read at run time.
- A $0 workspace degrades VaultMind to an honest deterministic
  copilot instead of breaking it — and a truncated RPC response no
  longer crashes it either.
