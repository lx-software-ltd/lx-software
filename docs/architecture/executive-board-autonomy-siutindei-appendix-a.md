# Appendix A — siutindei repo (WP10 hand-off)

This file is for whoever owns **lx-software-ltd/siutindei**. The lx-software
admin stack dispatches these workflows; it cannot create them from this
repository.

Live copies live in that repo:
`.github/workflows/board-agent.yml`,
`board-merge-staging.yml`,
`board-promote.yml`, and
`scripts/ci/board_policy.py` (mirrors `board_code.py` path/size guards).

Set repo secret `BOARD_PR_TOKEN` (fine-grained PAT or GitHub App with
contents + pull-requests) so `board-agent` opens the draft PR as that
actor. PRs opened with `GITHUB_TOKEN` often never start lint/test and
sit in `action_required`. Org Actions must allow read/write
`GITHUB_TOKEN` and “create and approve pull requests”.

Lockfile diffs (`package-lock.json`, `pubspec.lock`, `yarn.lock`, …)
are excluded from the 400-line runner cap so Dependabot bumps can land.

This admin repo cannot push to `lx-software-ltd/siutindei`. Apply the
lockfile + `BOARD_PR_TOKEN` change set, then the revision-mode patch
(a real unified diff against current `staging` `board-agent.yml`):

```
git -C /path/to/siutindei apply /path/to/lx-software/docs/architecture/siutindei-board-runner.patch
git -C /path/to/siutindei apply /path/to/lx-software/docs/architecture/siutindei-board-runner-revision.patch
```

If the second apply fails against a drifted workflow, merge the revision
inputs, `gh pr checkout`, Postgres Test Python, and no-force-push hunks
by hand. Do not replace the live workflow with the simplified block
below. Then set the `BOARD_PR_TOKEN` repo secret.

The admin stack refuses `code_run_task` revisions until staging
`board-agent.yml` declares `pr_number:` and `ci_failure:` inputs. Without
that, a CI-red `board/*` PR cannot be patched in place — the runner always
branches from `staging` and force-pushes. Owner-reopened revision tasks
use the same path: they stay `CodeRefused` until the patch is on staging.
An owner reopen clears the 1h runner-capability cache so a just-applied
YAML change is seen on the next dispatch.

## Branch protection

1. Create `staging` from `main`. Protect it: no force push; allow merges by
   the Actions bot; require status checks.
2. Protect `main`: PRs only, owner approval. The board never merges to `main`.

## `.github/workflows/board-agent.yml`

```yaml
name: board-agent
run-name: board-agent ${{ inputs.task_id }}
on:
  workflow_dispatch:
    inputs:
      task_id:
        required: true
        type: string
      issue:
        required: true
        type: string
      brief:
        required: true
        type: string
      kind:
        required: true
        type: string
      pr_number:
        required: false
        type: string
        description: Existing board/* PR to revise (do not start from staging)
      ci_failure:
        required: false
        type: string
        description: CI failure excerpt to fix
      revision_round:
        required: false
        type: string
permissions:
  contents: write
  pull-requests: write
  actions: write
jobs:
  run:
    timeout-minutes: 30
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: backend_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U postgres -d backend_test"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 10
    env:
      DATABASE_URL: postgresql+psycopg://postgres:postgres@localhost:5432/backend_test
      TEST_DATABASE_URL: postgresql+psycopg://postgres:postgres@localhost:5432/backend_test
    steps:
      - uses: actions/checkout@v4
        with:
          ref: staging
          fetch-depth: 0
          token: ${{ secrets.BOARD_PR_TOKEN || secrets.GITHUB_TOKEN }}
      - name: Branch
        env:
          GH_TOKEN: ${{ secrets.BOARD_PR_TOKEN || secrets.GITHUB_TOKEN }}
          PR_NUMBER: ${{ inputs.pr_number }}
          TASK_ID: ${{ inputs.task_id }}
        run: |
          if [ -n "$PR_NUMBER" ]; then
            gh pr checkout "$PR_NUMBER"
          else
            git checkout -B "board/${TASK_ID}"
          fi
      - name: Write brief
        env:
          CI_FAILURE: ${{ inputs.ci_failure }}
        run: |
          printf '%s\n' "${{ inputs.brief }}" > brief.txt
          if [ -n "$CI_FAILURE" ]; then
            printf '\n\nCI failure:\n%s\n' "$CI_FAILURE" >> brief.txt
          fi
      - name: Cursor agent
        env:
          CURSOR_API_KEY: ${{ secrets.CURSOR_API_KEY }}
        run: |
          # Install the Cursor CLI at the version the owner pins.
          # If the CLI supports a token/turn budget flag at install time, set it.
          cursor-agent -p "$(cat brief.txt)" --model composer-2.5 --yolo
      - name: Test
        run: |
          set -euo pipefail
          # Same suite as test.yml Test Python (Postgres + alembic). A red
          # suite must fail this step so the runner does not push.
          if git diff --quiet origin/staging -- \
            && [ -z "$(git ls-files --others --exclude-standard)" ]; then
            echo "No changes from staging; skip repo tests"
            exit 0
          fi
          if git diff --name-only origin/staging -- backend tests | grep -q .; then
            python -m pip install --upgrade pip
            python -m pip install -r backend/dev-requirements.txt
            python -m alembic -c backend/db/alembic.ini upgrade head
            python -m pytest tests backend --tb=short -q
          else
            echo "No backend/tests changes; Flutter and Node stay on PR CI."
          fi
      - name: Commit and draft PR
        env:
          GH_TOKEN: ${{ secrets.BOARD_PR_TOKEN || secrets.GITHUB_TOKEN }}
          PR_NUMBER: ${{ inputs.pr_number }}
          TASK_ID: ${{ inputs.task_id }}
          ISSUE: ${{ inputs.issue }}
        run: |
          git add -A
          git commit -m "board: #${ISSUE} $(head -n 1 brief.txt)" || true
          git push -u origin HEAD
          if [ -z "$PR_NUMBER" ]; then
            gh pr create --draft --base staging \
              --title "board: #${ISSUE} $(head -n 1 brief.txt)" \
              --body "$(cat brief.txt)

Task: ${TASK_ID}"
          fi
```

Secrets on the runner: `CURSOR_API_KEY` plus `BOARD_PR_TOKEN` (falls back
to `GITHUB_TOKEN`). No AWS credentials.

Repo-level `AGENTS.md` must require acceptance-criteria discipline and forbid
touching `**/auth/**`, `**/payments/**`, `**/migrations/**`, `infra/**`,
`.github/**`.

## `.github/workflows/board-merge-staging.yml`

`workflow_dispatch` input `pr_number`. Re-check CI green, base `staging`,
branch prefix `board/`, no protected paths (old and new file names), size
(400 lines, or 2000 for `content/**` only). Then `gh pr merge --squash`.

## `.github/workflows/board-promote.yml`

`workflow_dispatch`. If `staging` is behind `main`, exit non-zero (the admin
Lambda also refuses and opens a `needs_owner` rebase task). Otherwise open or
update a PR `staging → main` titled `Promote staging YYYY-MM-DD`. **The owner
merges that PR in GitHub.**

## Deploy

On push to `staging`, deploy a staging stack/URL and run a smoke test. On
push to `main`, deploy production (existing).
