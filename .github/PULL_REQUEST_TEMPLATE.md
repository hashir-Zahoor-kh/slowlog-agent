## Summary

<!-- What does this PR change, and why? -->

## Test plan

- [ ] `make lint` passes
- [ ] `make typecheck` passes
- [ ] `make test` passes (coverage gates: ≥90% on parser/digest/report/schemas, ≥80% overall)
- [ ] If `terraform/` changed: `terraform fmt -check` and `terraform validate` pass
- [ ] New behavior has test coverage; bug fixes include a regression test

## Checklist

- [ ] No AWS credentials, DSNs, or other secrets in the diff or in test fixtures
- [ ] Any new exception raised in `src/` carries a remediation message
- [ ] Docs (`README.md`, `CHANGELOG.md`) updated if user-facing behavior changed
