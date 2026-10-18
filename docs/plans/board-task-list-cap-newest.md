# Plan: capped task reads keep the newest rows

**Status**: Done
**Zone**: yellow

## Goal

`board_store.list_tasks` walks the `tasks#<status>` index oldest first and
stops at `limit`. `delivered` passed 200 rows on 2026-09-30, so every capped
read of that status returns the September rows and never a task created
after that date. `board_code._find_task` (dedupe of `code-implement` tasks),
`list_tasks_for_api` (the Done list), and every other `limit=200` dedupe over
`delivered` are blind to recent work. On 2026-10-18 that re-created an
engineer task for siutindei issue #714 on every five-minute staff tick, and
each one dispatched a `board-agent` workflow run (20 runs in two hours). The
same loop ran for issue #639 on 2026-10-12.

Make a capped read return the most recent `limit` rows of each status, in the
order the caller asked for. `newest_first` keeps controlling output order.

## Non-goals

Changing `board_code.py` (red). A per-issue failed-run cap on
`maybe_assign_ready_issues` is proposed separately in chat. Changing the
siutindei `board-agent` workflow (patch supplied under `docs/architecture/`).

## Files

- `backend/lambda/admin/board_store.py`
- `backend/lambda/admin/test_board_staff.py`
- `docs/architecture/executive-board.md`

## Invariants this change preserves

A status with fewer rows than `limit` returns the same rows in the same order
as before. Oldest-first output stays the default. `newest_first=True` still
returns newest first. `_find_task` and other dedupes see the latest 200 rows
of a status instead of the oldest 200.

## Done when

`python3 -m unittest test_board_staff -k Cap` passes with a status holding
more rows than `limit`: the newest rows come back, oldest first by default and
newest first with `newest_first=True`. `python3 -m ruff check backend/lambda
scripts` is clean. The full admin suite passes.

## Rollback

Revert the commit. Capped reads return the oldest rows again.

## Open questions

None.
