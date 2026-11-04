# Live evidence — 2026-11-04

First end-to-end run of VaultMind against the **live** Otari gateway
(real workspace key, fetched at runtime by `scripts/run_live.py` — the
key itself is never on disk) and the **live** AgentVault on Arbitrum
Sepolia. Raw outputs, unedited:

| File | What it shows |
|---|---|
| `smoke-test.txt` | Gateway auth OK, 159 models visible, configured primary reachable — then the chat call is refused (see "The funding wall") |
| `vault-state.txt` | Live vault read: caps 0.01 / 0.025 ETH, spent today 0.01 ETH, balance 0.04 ETH, demo recipient allowlisted |
| `propose-pass.txt` | 0.005 ETH to the allowlisted service → **PASS** card, exit 0 |
| `propose-reject.txt` | 0.5 ETH → **REJECT** card, exit 3, three independent policy reasons |
| `usage-ledger-live.jsonl` | Every gateway attempt of both proposes: per role, primary then fallback (failover engaged), each refused pre-dispatch |

## The funding wall (why the model text is missing, honestly)

The workspace balance is **$0.00**: the announced $20 starter credit
for the first 200 Otari sign-ups never appeared (the dashboard showed
$0.00, and the gateway itself says so). Every chat completion —
including models priced at $0.00 in the catalog — is refused before
dispatch:

```
HTTP 402 · {"detail": "Insufficient funds ($0.00) to serve this request.",
            "code": "insufficient_funds"}
```

So in this run the three roles were *attempted* live (primary +
fallback each, all ledgered), the gateway refused them all, and
VaultMind degraded exactly as designed: the deterministic policy
mirror decided both verdicts and the reporter fell back to the
template card. No model output is faked anywhere in this repo; the
moment the workspace carries a balance, the same commands produce
the full proposer → checker → reporter flow with real token counts
in the ledger. (One cosmetic note: the PASS card in
`propose-pass.txt` carries the older fallback wording "no working
Otari key"; the string was clarified in the next commit — the key
works, the balance is empty.)

## What this run proves

- The stored workspace key authenticates against the hosted gateway
  (`GET /models` → 200, 159 models; wrong-key control earlier → 401).
- The routing config's models are real catalog IDs (the blog-era
  `mzai:` spelling and the docs' `gpt-5-nano` / `claude-haiku-4-5`
  examples do not exist in the hosted catalog — see NOTES.md).
- Failover engages on gateway refusals, per role, and every attempt
  is written to the usage ledger with its error.
- The on-chain half is fully live: verdicts are computed from the
  vault's actual caps, spend and allowlist, read at run time.
