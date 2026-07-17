# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial release of `slowlog-agent`: on-demand MySQL slow query log
  analysis via CloudWatch Logs, a deterministic parse/fingerprint/digest
  pipeline, a headless-Claude analysis step with schema-validated output
  and one retry on validation failure, a CLI (`slowlog analyze`,
  `slowlog doctor`, `slowlog init`), Terraform for a scoped read-only IAM
  user, and GitHub Actions CI (lint, typecheck, coverage-gated tests,
  terraform fmt/validate).
- Pluggable agent backend (`agent_backend = "claude" | "copilot"`):
  `analyzer.py`'s prompt rendering, schema validation, and retry-once
  policy are now backend-agnostic, with `backends/claude.py` (native
  `--json-schema` enforcement) and `backends/copilot.py` (schema inlined
  in the prompt, defensive markdown-fence stripping) behind a shared
  `AgentBackend` protocol. `slowlog init` detects installed binaries and
  offers a choice when both are present; `slowlog doctor` validates
  whichever backend is configured.
