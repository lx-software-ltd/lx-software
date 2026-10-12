# Plan: Show the candidate kebab on Progress

**Status**: Implemented
**Zone**: yellow

## Goal

The Progress candidate table uses `AdminRowActions` (the ⋯ menu) for Approve /
Reject. On a desktop pointer that menu is `opacity: 0` unless the row is an
`.admin-expand-summary`. Catalog rows are plain `<tr>`s, so the owner cannot
see or click Reject.

## Non-goals

- Changing the kebab convention (actions stay in the menu, not standalone buttons).
- Owner-only API changes.

## Files

- `apps/admin_web/src/styles/tables.css`
- `apps/admin_web/src/components/board/BoardCatalogSourcesSection.test.tsx`

## Invariants this change preserves

- Every row action stays in the kebab.
- Expandable finance / record rows still fade the kebab until hover.

## Done when

- Desktop Progress candidate rows show the ⋯ without hovering an expandable summary.
- `cd apps/admin_web && npx vitest run src/components/board/BoardCatalogSourcesSection.test.tsx`

## Rollback

Revert the CSS rule.

## Open questions

None.
