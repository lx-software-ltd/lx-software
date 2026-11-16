# Plan: A delegate key for three board chores, and an Instagram read

**Status**: Done
**Zone**: red for the scope contract, the generated authorizer scope list, `write_blocked` and `scripts/manage-public-api-keys.py` (and the workflow that runs it). Approved in chat on 16 Nov 2026: "build apis so that you can do 4 5 and 6 as planned." Yellow for the handlers and the Instagram read.

## Goal

A key that already has board access and `allowWrite` can, with one extra scope `siutindei-board-delegate`:

- reject an approval, with a note
- dismiss a task, with a note
- change five focus settings, and nothing else: outreach districts, outreach prospect types, the weekly qualified target, catalog micro-batch on or off, and catalog auto-import off

The same key cannot approve anything. Approving is what sends the email or spends the money.

The board can also read the connected Instagram account: recent posts and current stories, as a tool and as `GET /siu-tin-dei/board/meta/instagram`.

## Non-goals

No approve for a key. No change to tool permissions, hold lengths, spend caps, budgets, the daily outreach cap, personal-address outreach, catalog import, or code promote. No WhatsApp sending. No retry of the stuck Instagram rows. The scope is not added to any live key by this change.

## Files

- `contracts/public-api-scopes.json` and the two generated copies (`contract_constants.py`, `public_api_scopes_generated.py`).
- `backend/lambda/admin/board_public_api.py`: `settings/focus` is owner-only, and `delegate_path` names the three writes the scope unlocks.
- `backend/lambda/admin/board_delegate.py`: the note rule, the focus apply, the audit line.
- `backend/lambda/admin/board_routes.py`: wire the three handlers and the Instagram GET. The file stays at its line allowance.
- `backend/lambda/admin/board_meta_media.py` and `board_tools_meta.py`: `meta_list_ig_media`.
- `scripts/manage-public-api-keys.py` and `.github/workflows/manage-api-keys.yml`: `set-scopes`, which replaces the scope list.
- Tests, `docs/deployment/admin-website.md`, `docs/architecture/executive-board.md`.

## Invariants this change preserves

`write_blocked` still returns true for approve, for `PUT settings`, `PUT boundaries` and `PUT tools`, and for every other owner-only path. The delegate scope does nothing without `allowWrite`, the writes kill switch, and the path's existing scope (board-ops for tasks, board-full for approvals and settings). A key actor who calls approve gets 403 from the handler as well as the gate. An owner rejecting or dismissing without a note still works. Focus either applies every field in the body or none. Instagram reads use the existing Page token and return id, time, type, permalink and caption.

## Done when

`python3 scripts/check-contracts.py`, `python3 -m unittest discover -p 'test_*.py'` in `backend/lambda/admin` and in `backend/lambda/public_api_authorizer`, `python3 -m ruff check backend/lambda scripts`, `python3 scripts/check_file_length.py`, `bash scripts/check-pii.sh`, `python3 scripts/validate_agent_rules.py`.

## Rollback

Revert the commits. A key that was given the scope keeps it and the deployed code ignores it, because the authorizer drops a scope it does not know.

## Open questions

None. Approving stays with the owner, as agreed.
