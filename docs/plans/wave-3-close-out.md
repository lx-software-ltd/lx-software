# Plan: Wave 3 close-out

**Status**: Draft
**Zone**: yellow

## Goal

Move `lx-software` onto the wave 1 actions commit and close the CI convergence rows that apply here. The last commit switches `workflow-conformance` from warn to enforce.

## Non-goals

Part B. No deploy, bootstrap, or key-management workflow is triggered. C28's Dependabot exclude for `lx-software-ltd/actions` is not set, because that option is not measured. C23, C24, and C25 stay for Stage 5.

## Files

`.github/workflows/`, `.github/dependabot.yml`, `.pre-commit-config.yaml`, `.cursor/hooks/stop_gate.py`, `.cursor/rules/00-repository-core.mdc`, `.cursor/skills/verify-change/SKILL.md`, `docs/architecture/zones.md`, and the deleted local hook scripts.

## Invariants this change preserves

- One `lx-software-ltd/actions` commit: `61b67ed4f686659433f6ca4cb10c80707e365cd0`.
- The pre-commit `rev` is that same commit.
- `lint` and `test` stay the required check names.
- The PII denylist file stays. The hook reads it. No plaintext was added.
- Deploy workflows are not triggered. Their account-id expressions are unchanged.
- Gate G2 covers the red hook path: `.pre-commit-config.yaml`, `.cursor/hooks/**`, and `scripts/pii-denylist.sha256`.

## Done when

- `workflow-conformance` in enforce mode reports no findings. Enforce is the last commit.
- Code scanning categories stay the strings the existing alerts use. CodeQL still analyzes `javascript-typescript` and uploads `/language:javascript`. Python stays `/language:python`. Semgrep uploads `.github/workflows/security.yml:semgrep`.
- Semgrep runs `mode: scan`, which reads the whole repository on a pull request. The previous `semgrep ci` command scanned only files changed since the base. The packs are `p/python`, `p/javascript`, `p/security-audit`, `p/secrets`, and `p/owasp-top-ten`. The two added packs are `p/python` and `p/owasp-top-ten`. The urllib rule is not excluded. Lines that already carry `noqa: S310` on a `urlopen` call also carry `nosemgrep` for `python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected`. `bank_sync.py` and `board_catalog_import.py` do not, so the rule checks them.
- Bandit on `backend/lambda` exits 0. Measured 22 Nov 2026: no high findings. The skip list is `B101` (assert) only. `B311` stays off that list. The seeded `Random` in `board_review_sample.py` is `# nosec B311` on the shuffle line. The four medium groups are marked on each line, not skipped: `B104` (four `0.0.0.0` fallback strings), `B108` (`TemporaryDirectory` under `/tmp` in a test), `B310` (sixteen `urlopen` calls), and `B608` (two Metrics Insights expressions; the pool id has single quotes removed). The same scan's low findings are marked the same way. They are empty strings, token URLs, secret names, test fixtures, two `except: continue` paths, and a fixed `openssl` argv. `B105` and `B106` are not a directory-wide skip. `scripts/` is not in the scan path. Re-run after the marks: 0 findings, exit 0.
- `npm audit --omit=dev --audit-level=high` reports no high advisory in `apps/public_www`, `apps/admin_web`, and `backend/infrastructure`. `backend/infrastructure` has a moderate `minimatch` advisory below that level. The level was not lowered.
- `pip-audit` could run locally after `python3.12-venv` was installed. Both `backend/lambda/admin/requirements.txt` and `backend/lambda/public_api_authorizer/requirements.txt` reported no known vulnerabilities. Before that package was installed, pip-audit could not create a virtualenv.
- Python requirement pins pass.
- The agent harness check passes after the core-rule sentence change. The denylist sentence keeps `[why: 5da3336 hashed PII denylist]`.
- `python3 -m unittest scripts/test_agent_hooks.py` passes. A machine without `pre-commit` on `PATH` gets a follow-up from the stop hook. The first `pre-commit` run needs network to clone `lx-software-ltd/actions`.
- Third-party pin comments name the tag whose object is that SHA: `actions/checkout` is v7.0.1, `actions/setup-node` is v7.1.0, `actions/upload-artifact` is v7.0.2, `aws-actions/configure-aws-credentials` is v6.3.0, `docker/setup-qemu-action` is v4.4.0, and `github/codeql-action/upload-sarif` is v4.39.3. No workflow calls `actions/setup-python` directly.

## Rollback

Revert the branch. The previous pin is `aab84b76383d5a44838f9617ac47b23cfff7fdaf`.

## Open questions

None. Lighthouse on this pull request still stops at the production environment rule. That check is not required.
