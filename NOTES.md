# NOTES — Otari docs friction log (for the hackathon feedback deliverable)

Only genuine, dated observations from actually building VaultMind.
Nothing here is invented; each entry says how it was hit. Entries marked
[pre-build research] were recorded during the 2026-11-04 research pass
(scoring plan) and are included because they shaped this build.

## 2026-11-04 — building VaultMind

1. **Base URL: blog says `/v1`, the live API says `/api/v1`.**
   Mozilla's official blog post ("Use the Otari Gateway with OpenCode")
   points clients at `https://api.otari.ai/v1`. Calling it returns
   HTTP 404 with a (helpful!) JSON correction: "Otari serves its API
   under /api/v1, not /v1." The current repo quickstart has it right
   (`https://api.otari.ai/api/v1`). The gateway's self-correcting error
   message saved real time — but anyone following the blog first still
   hits the wall. Verified by direct calls, 2026-11-04: `/api/v1/models`
   and `/api/v1/chat/completions` answer 401 (auth), `/v1/...` answers
   the 404 correction.

2. **Key prefix differs between sources: `tk_` vs `otk_`.**
   The blog-era material describes keys starting `tk_...`; the current
   quickstart says the key "starts with `otk_`". Minor, but a builder
   pattern-matching their key against the docs can doubt they copied
   the right secret. VaultMind's client accepts either (it just sends
   the Bearer token).

3. **Auth header flexibility is real and undocumented in the quickstart
   path I took.** The unauthenticated response says the gateway accepts
   `Otari-Key`, `Authorization`, or `x-api-key`. Nice — discovered from
   the error body, not from the docs page I started on.

4. **The hosted model catalog / provider spelling could not be
   confirmed from public docs.** The blog names `mzai:` as the managed
   provider with `mzai:moonshotai/Kimi-K2.6`; the string `mzai` does not
   appear anywhere in the current repo docs (`models.md`,
   `hosted-providers.md`), which instead teach catalog IDs
   (`vendor/model`) and `provider:model` pins with other providers.
   Which spellings the hosted deployment actually accepts is only
   answerable with a key in hand (the smoke test's model-list check is
   built for exactly this). Until then, model IDs in
   `config/otari-routing.yml` are best-effort from official examples.

5. **Routing policies are documented as config, and the hosted surface
   for them was not findable from the docs.** `routing.md` specifies
   policy YAML (`select`, `budget_used_pct`, `on_failure`) and a CLI
   (`otari routing explain ...`). Building for the hosted platform, I
   could not tell from public docs where a hosted user creates that
   policy (dashboard? per-workspace YAML? CLI against the hosted
   endpoint?). VaultMind therefore implements the same semantics
   client-side and ships the policy-shaped YAML in its config as the
   artifact to configure — if the hosted surface exists, this is the
   friction that hid it. [To re-check in the dashboard once the account
   exists.]

6. **Learned/smart routing is documented at length but self-described
   as not offered.** [pre-build research, from routing.md itself]
   The docs say the smart router "is not offered in the dashboard...
   has not been validated for general use". Documenting an unavailable
   feature in the main routing doc without a banner is a trap for
   builders planning around it.

7. **The hackathon onboarding/rubric doc is JS-rendered and was not
   fetchable as text** [pre-build research] — `otari.ai/devs-wilding`
   and the linked rubric could not be read outside a live browser, and
   no mirror exists. The 7 submission items were reconstructed from the
   DoraHacks page itself. A plain-text/markdown version of the rubric
   would remove a whole class of eligibility mistakes.

8. **Tool-call budget holds need a live test.** [pre-build research,
   still open] Docs say gateway-run tool calls are held against budget
   and refused with `budget_exceeded`; whether the hosted platform
   behaves exactly so (and how the refusal looks in the dashboard) is
   on the verify list for the next build step, when built-in tools
   enter the checker.

## Non-Otari friction hit during the same build (context, not feedback)

- Arbitrum's official Sepolia RPC answers 403 to Python urllib's
  default User-Agent; an explicit UA header fixes it. VaultMind's
  reader also fails over across three public endpoints.
- A dropped connection from the gateway's edge ("Remote end closed
  connection without response") escapes urllib as a raw
  `http.client.RemoteDisconnected`, not a `URLError`. The Otari client
  now normalises it into a gateway error so failover engages.
