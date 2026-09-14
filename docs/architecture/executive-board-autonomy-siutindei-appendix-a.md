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
lockfile + `BOARD_PR_TOKEN` change set from
[`siutindei-board-runner.patch`](siutindei-board-runner.patch):

```
git -C /path/to/siutindei apply /path/to/lx-software/docs/architecture/siutindei-board-runner.patch
```

Then set the `BOARD_PR_TOKEN` repo secret.

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
permissions:
  contents: write
  pull-requests: write
  actions: write
jobs:
  run:
    timeout-minutes: 30
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: staging
          token: ${{ secrets.BOARD_PR_TOKEN || secrets.GITHUB_TOKEN }}
      - name: Branch
        run: git checkout -B "board/${{ inputs.task_id }}"
      - name: Write brief
        run: printf '%s\n' "${{ inputs.brief }}" > brief.txt
      - name: Cursor agent
        env:
          CURSOR_API_KEY: ${{ secrets.CURSOR_API_KEY }}
        run: |
          # Install the Cursor CLI at the version the owner pins.
          # If the CLI supports a token/turn budget flag at install time, set it.
          cursor-agent -p "$(cat brief.txt)" --model composer-2.5 --yolo
      - name: Test
        run: # repo test command
      - name: Commit and draft PR
        env:
          GH_TOKEN: ${{ secrets.BOARD_PR_TOKEN || secrets.GITHUB_TOKEN }}
        run: |
          git add -A
          git commit -m "board: #${{ inputs.issue }} $(head -n 1 brief.txt)" || true
          git push -u origin "HEAD:board/${{ inputs.task_id }}"
          gh pr create --draft --base staging \
            --title "board: #${{ inputs.issue }} $(head -n 1 brief.txt)" \
            --body "$(cat brief.txt)

Task: ${{ inputs.task_id }}"
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
