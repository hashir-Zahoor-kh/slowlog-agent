# Security Policy

## Reporting a vulnerability

If you find a security vulnerability in slowlog-agent, please **do not**
open a public GitHub issue. Instead, use GitHub's private vulnerability
reporting for this repository:
<https://github.com/hashir-Zahoor-kh/slowlog-agent/security/advisories/new>

Please include:

- A description of the vulnerability and its potential impact
- Steps to reproduce (a minimal repro is very helpful)
- Any relevant logs or output (redact log group names, credentials, DSNs)

We'll acknowledge reports as soon as possible and aim to keep you updated as
we investigate and fix the issue.

## Scope

slowlog-agent touches AWS credentials and database connection strings by
design. Particularly relevant reports:

- A way for the tool to gain write access to AWS or the configured database
  beyond what's documented in the [security model](README.md#security-model)
- A prompt-injection or tool-permission bypass that lets the analysis agent
  run something other than `SELECT`/`EXPLAIN`
- Credential or DSN leakage (into logs, reports, error messages, or the
  Claude API request beyond the intended digest/EXPLAIN payload)

## Out of scope

- Vulnerabilities requiring an attacker to already have write access to your
  AWS account or database
- Issues in third-party dependencies — please report those upstream (and
  feel free to also flag them here if slowlog-agent's usage makes them
  exploitable)
