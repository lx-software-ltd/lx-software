---
name: admin-record-table
description: Build an admin list as a toolbar, a table, and a row editor that follows the console contract.
---

# Admin record table

Use the primitives in `apps/admin_web/docs/UI_COMPONENTS.md`.

- One untitled card. Toolbar first (search, then import immediately left of create when the table imports), then the table.
- The create button matches the search field height and spells the noun (`New account`).
- The editor opens under the clicked row. There is no editor title and no Cancel.
- One primary button, labeled with the verb, and `Saving…` while the save is in flight.
- The open row id is that table's query parameter. `new` is the draft. An unknown id is removed. Drop every other table's row parameter.
- Dirty means any editor field differs from the saved record. Deletes and dirty-row switches use `ConfirmDialog`.
- Selecting text does not toggle the row. The summary row is keyboard-focusable.
- Every row action sits in the kebab menu, which closes when an action is chosen.

Verify with `npm run dev:mock` and, when the layout changes, `npm run test:e2e`.
