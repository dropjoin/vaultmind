# VaultMind — a policy copilot for an AI agent's vault, powered by Otari

> **Submission summary (item 1):** VaultMind · built by M Aziz Yahya
> (GitHub `dropjoin`) · Contact/sign-up email: the address registered
> for this hackathon on DoraHacks and Otari.ai ·
> **One line:** VaultMind is an AI copilot that reads a live on-chain
> policy vault (AgentVault), drafts and checks proposed agent payments
> against the vault's caps and allowlist, and explains every decision —
> with every model call routed through Otari under per-role virtual
> keys and budgets.

## The idea

AgentVault (the parent project) is a Solidity vault on Arbitrum that
separates *owning* money from *spending* it: a human owner sets hard
on-chain rules — a per-transaction cap, a daily cap, recipient and
token allowlists — and an AI agent's hot key can only spend inside
them. The contract enforces the policy at execution time.

But a contract can't *explain* itself, draft a justification, or smell
a manipulated payment request. That's the copilot's job — and the
copilot itself needs a policy. VaultMind gives the agent's **brain**
the same treatment AgentVault gives its **wallet**:

| AgentVault (on-chain, for money) | VaultMind via Otari (for model calls) |
|---|---|
| Per-transaction cap | Per-role budget, enforced before dispatch |
| Daily cap | Budget window per virtual key |
| Recipient allowlist | Model-scoped virtual keys (a role can only reach its models) |
| Owner freeze | Revocable keys; local budget block at 100% |
| `agentSpend` policy check | Checker role + deterministic policy mirror |

## How it works

```
        ┌──────────────── Arbitrum Sepolia ────────────────┐
        │  AgentVault 0x0344…C87d1C3                          │
        │  owner · agent · frozen · getPolicy · balanceOf · │
        │  allowedRecipient                                 │
        └───────────────▲───────────────────────────────────┘
                        │ eth_call (live state)
        ┌───────────────┴───────────────────────────────────┐
        │  VaultMind CLI (this repo)                        │
        │  1. proposer  — drafts the justification          │
        │  2. floor     — deterministic mirror of           │
        │     agentSpend's require() chain + injection      │
        │     guardrail scan of the untrusted memo          │
        │  3. checker   — judgment layer: PASS / REJECT     │
        │  4. reporter  — plain-language decision card      │
        └───────────────▲───────────────────────────────────┘
                        │ every model call, per-role key
        ┌───────────────┴───────────────────────────────────┐
        │  Otari gateway (hosted, api.otari.ai)             │
        │  virtual keys · budgets · thrifty routing (>=80%  │
        │  budget -> cheap model) · failover · usage        │
        └───────────────────────────────────────────────────┘
```

Governance rule: **a model may tighten a verdict, never loosen it.**
If the deterministic mirror rejects (over cap, not allowlisted,
frozen, …) or the guardrail finds a high-severity injection in the
memo, the final verdict is REJECT and no model is asked to reconsider.
When the floor passes, the checker model must also PASS.

## Live status (2026-11-04)

Exercised end-to-end against the hosted gateway and the live Sepolia
vault — raw outputs in `docs/evidence/`:

- Gateway auth and the model catalog check out with the real
  workspace key (159 models; the routing config now uses verified
  catalog IDs and the gateway's own prices — the blog/docs example
  models do not exist in the hosted catalog, see `NOTES.md`).
- Both demo proposes run the full pipeline against live vault state:
  0.005 ETH → PASS card, 0.5 ETH → REJECT card, every gateway attempt
  ledgered with failover.
- **Funded and fully model-backed (2026-11-04):** the $20 starter
  credit landed via the organizer's voucher (Marcus, DoraHacks
  message), and the full model-backed run completed against the
  funded workspace — smoke test OK, both demo proposes decided by
  the models through the gateway, usage ledgered per role. Raw
  outputs in `docs/evidence/` (the `*-funded.txt` files). Earlier
  the same day the workspace sat at $0.00 and the gateway refused
  every completion with 402 `insufficient_funds`; that block is
  resolved, not current.
- The per-role virtual keys are the one remaining manual step
  (dashboard only — the keys API needs a master key); exact steps in
  `docs/OTARI_FEATURES.md`.

## Quickstart

```bash
cp .env.example .env        # add your OTARI_API_KEY (otk_...)
python3 scripts/smoke_test.py          # prove the Otari integration
# In this workspace the key lives in a credential store instead of
# .env; scripts/run_live.py fetches a runtime surrogate and runs any
# command above with it, e.g.:  python3 scripts/run_live.py propose ...
python3 vaultmind.py state             # live AgentVault readout
python3 vaultmind.py propose --to 0xF04D8eA360eF3097E632a67F4b9a9B11523b3Dc1 \
    --amount 0.005 --memo "API usage for November"
python3 vaultmind.py propose --to 0xF04D8eA360eF3097E632a67F4b9a9B11523b3Dc1 \
    --amount 0.5                 # -> REJECT: per-tx cap is 0.01 ETH
python3 vaultmind.py usage             # per-role Otari spend vs budget
python3 -m unittest discover -s tests  # 27 tests, no key needed
```

Without an `OTARI_API_KEY` the chain reads and the policy mirror still
run; the model roles report SKIPPED — nothing is faked. Exit codes:
`0` PASS/ok, `3` REJECT, `1` runtime error, `2` smoke test not
configured.

## Repo map

- `src/otari_client.py` — the Otari gateway client (the integration
  that landed in this branch's first commit).
- `config/otari-routing.yml` — per-role virtual keys, budgets, models;
  thrifty threshold; the same routing intent in the Otari docs'
  policy YAML shape.
- `src/vault.py` + `src/agentvault_abi.json` — live AgentVault reader
  (raw JSON-RPC, ABI from the project's own Foundry artifact).
- `src/policy.py` — deterministic mirror of the contract's checks.
- `src/guardrail.py` — prompt-injection tripwire for untrusted memos.
- `src/router.py` — budget-conditional model selection + failover.
- `src/ledger.py` — JSONL usage ledger (role, model, tokens, est. cost).
- `src/roles.py` — proposer / checker / reporter prompts and verdict logic.
- `vaultmind.py` — the CLI.
- `scripts/run_live.py` — runs the CLI/smoke test with the workspace
  key obtained as a runtime surrogate from the credential store; the
  key never touches disk.
- `docs/evidence/` — raw outputs of the 2026-11-04 live run.
- `docs/OTARI_FEATURES.md` — the Otari features table for the submission.
- `NOTES.md` — genuine Otari docs friction found while building (the
  raw material for the feedback deliverable).
- `tests/` — policy fixtures (over-cap → REJECT, non-allowlisted →
  REJECT, valid → PASS, boundary cases), routing/failover, guardrail.

## Hackathon submission map (Devs Wilding Online, 7 items)

1. **Name / email / one-liner** — see the summary block at the top.
2. **Public repo + branch** — this repository, branch
   `devs-wilding-otari`.
3. **First commit where Otari came in** — the branch's root commit,
   `feat(otari): integrate the Otari gateway — client wrapper,
   per-role routing config, smoke test` (client + routing config +
   smoke test, nothing else).
4. **Otari features used** — `docs/OTARI_FEATURES.md` (implemented vs
   workspace-configuration status stated per feature).
5. **PRs / issues on mozilla-ai/otari** — FILED 2026-11-05 from the
   real friction in `NOTES.md`:
   https://github.com/mozilla-ai/otari/issues/2898 (the base-URL and
   key-prefix doc mismatches).
6. **Demo video (3–5 min)** — outline in the scoring plan: live vault
   state → in-policy PASS → over-cap REJECT → poisoned memo blocked →
   budget downgrade + failover → per-role usage costs. *(Link added
   when recorded; per the builder's rule, the user uploads videos
   himself.)*
7. **Feedback** — written answers drafted from `NOTES.md`; screen
   recording to follow the same material. Only friction actually hit
   while building is claimed.

## Deadline discipline

Submission deadline is **11 Nov 2026, 22:59 UTC** (the DoraHacks event
window). A later date shown in one dashboard field (3 Dec) is treated
as a platform artifact, not an extension — see the scoring plan's
deadline analysis in the build notes.

## License

MIT.
