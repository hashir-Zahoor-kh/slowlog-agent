# Contributing to slowlog-agent

Thanks for considering a contribution. This project keeps a deliberately
small non-goal list (no scheduler, no web UI, no auto-applying DDL, no write
access anywhere) — please check an idea against those before opening a PR.

## Setup

```bash
git clone https://github.com/hashir-Zahoor-kh/slowlog-agent.git
cd slowlog-agent
uv sync --extra dev
pre-commit install
```

## Workflow

1. Create a branch off `main`.
2. Make your change. New behavior needs tests; bug fixes need a regression
   test that fails before the fix and passes after.
3. Run the full local gate before opening a PR:
   ```bash
   make lint
   make typecheck
   make test
   ```
   `make test` enforces the same coverage gates as CI: ≥90% on
   `parser.py`, `digest.py`, `report.py`, `schemas.py`, ≥80% overall.
4. If you touched `terraform/`, run `terraform fmt -check` and
   `terraform validate` (or let CI catch it — the terraform job doesn't
   need any AWS credentials).
5. Open a PR using the template. Describe what changed and why, and how you
   tested it.

## Code style

- Formatting and linting are enforced by `ruff` (`make lint`); typing by
  `mypy --strict` (`make typecheck`). Both run in CI and in `pre-commit`.
- Deterministic logic (parsing, fingerprinting, digesting, schema
  validation, report rendering) belongs in tested Python, not in the
  prompt. Keep the LLM's job narrow: interpret the digest, run `EXPLAIN`,
  rank findings. If you find yourself asking the agent to do something a
  regex or a pydantic model could do reliably, do that instead.
- Every exception raised in `src/` should carry a `remediation` string (see
  `errors.py`'s `SlowlogError` base class) — a user hitting it should never
  see a bare traceback without being told what to do next.

## Commit messages

Conventional-commit-style prefixes (`feat:`, `fix:`, `chore:`, `ci:`,
`docs:`, `refactor:`, `test:`) are used throughout this repo's history —
please keep using them.

## Reporting bugs / requesting features

Use the issue templates. For security vulnerabilities, see
[SECURITY.md](SECURITY.md) instead of opening a public issue.
