# Admin web UI components

This document defines **reusable patterns** for the LX Software admin SPA (`apps/admin_web`). Future features should follow these conventions so screens stay visually and behaviorally consistent.

## Layout rules

1. **Editors above tables** — Any form that creates or updates rows belongs in a dedicated block **above** the related table, never inline-only inside table rows (except icon actions).
2. **Save actions bottom-left** — Within each editor card, primary actions (`Save`, `Update`, etc.) sit in the footer, **left-aligned** (`justify-content-start`). Secondary actions (e.g. `Clear`) sit beside them to the right in the same footer row.
3. **Tables** — Use `AdminDataTable` for list views: one **search/filter** input at the top of the card, then a striped Bootstrap table. The **last column is always “operations”**: row actions only, no heading text (use a visually hidden label for screen readers). On phones, mark non-essential columns with `priority: "secondary"` (`md+`) or `"tertiary"` (`lg+`) and repeat the most useful hidden value under the identifying cell with `AdminDataTableCellMeta`. Body cells must use `AdminCell column="…"` so the header/cell priority classes stay aligned (do not call `adminColumnPriorityClass` by hand). Warnings (stale badges, consent expiry) and the table’s main metric must stay `primary` or appear in the meta line. A record table should stay readable at ~390px without sideways scrolling to reach the name and Operations.
4. **Operations use icons only** — Row actions use `TableIconButton` with Bootstrap Icons classes (`bi bi-pencil`, `bi bi-trash`, …). Every control **must** have a meaningful `aria-label` (and `title` mirrors it). No visible text on these buttons.

## Shared components (`src/components/ui/`)

| Component | Purpose |
|-----------|---------|
| `MoneyAmount` | Displays a numeric amount with ISO currency via `Intl.NumberFormat`. Props: `amount`, `currency`. |
| `CurrencySelect` | Bootstrap `form-select` for admin-supported currency codes only (`src/lib/currencies.ts`). Props: `id`, `value`, `onChange`, optional `className`, `disabled`, `ariaLabel`. |
| `DateTimeDisplay` | Formats an ISO instant for **Hong Kong** wall time, e.g. `May 26, 2026 at 10:12pm HKT`. Uses `formatDateTimeHKT` in `src/lib/formatDisplay.ts`. |
| `AdminEditorSection` | Card wrapper for editor blocks: optional title/description, body content, optional **footer** for Save/Update/Clear. |
| `AdminDataTable` | Card + single filter field + standard table (`table-sm`, `table-striped`). Pass columns and row `<tr>` children via `AdminCell`. Use `AdminDataTableEmptyRow` for empty/filter-empty states. Optional `priority` hides secondary/tertiary columns on small screens; pair with `AdminDataTableCellMeta`. Pass `sort` so phones get a select + direction toggle when sortable headers are hidden. |
| `AdminCell` | Body cell bound to a column key. Applies that column’s priority class so headers and cells hide together. |
| `AdminPageIntro` | Explanatory copy under a page title. Collapsed behind a disclosure on phones; inline from `md`. |
| `AdminTableTotalLabel` / `AdminTableTotalCurrency` | Render the FX note and display-currency picker **once** in a finance table footer (never a mobile duplicate). |
| `AdminTabList` | WAI-ARIA tablist (arrow / Home / End). On phones, up to six tabs fill a **two-column grid**; longer lists become a native `<select>`. From `md` they are a horizontally scrollable row of pills. Pass `disabled` when the backing query failed. |
| `TableIconButton` | Icon-only button for the operations column. |

Import from the barrel: `import { MoneyAmount, … } from "../components/ui"` (adjust path).

## Formatting helpers (`src/lib/formatDisplay.ts`)

- `formatMoneyAmount(amount, currency)` — string for non-React contexts.
- `formatDateTimeHKT(iso)` — string for HKT display.

## Executive Board components (`src/components/board/`)

The Siu Tin Dei **Executive Board** tab (`ExecutiveBoardTab`) is the reference for conversational / long-running features:

| Component | Purpose |
|-----------|---------|
| `BoardOffcanvas` | Right-hand slide-over (React state + CSS, no Bootstrap JS). Use for chat threads and per-item editors that should not navigate away from the list. |
| `BoardMarkdown` | Renders LLM output with `react-markdown` + `remark-gfm` inside `.board-markdown`. Never `dangerouslySetInnerHTML`. |
| `BoardMemberEditor`, `BoardCharterEditor`, `BoardBriefEditor` | Editors keyed on the record they edit (`key={…}`) so local state re-initialises on data change instead of syncing props in effects. Show character counters against the contract limits and a **Use default** link for overridable fields. |
| `BoardChatOffcanvas` | Optimistic user bubble + "thinking…" placeholder while the async job runs; polling lives in `useBoardChat`, which also copies the job's in-flight `toolCalls` onto the pending bubble so lookups show live. |
| `BoardMeetingPanel`, `BoardTranscript`, `BoardMinutesView` | Progress bar driven by `meetingPhaseProgress`, minutes/transcript toggle, refetch-while-running in `useBoardMeeting`. `BoardTranscript` renders `kind: "tool"` turns as a collapsed `<details>` ("Ada looked at 2 things") wrapping a `BoardToolCallList`, not markdown. |
| `BoardToolCallList` | One compact row per tool call (status icon with `role="img"` + `aria-label`, tool badge, summary, optional error, **review** link for `pending_approval`). Reused by chat bubbles, transcript tool turns and the audit log. |
| `BoardToolsCard` | Tools & permissions: kill switch, global mode, the tool × member level matrix (cells show `→ effective` when the global mode caps them), per-tool operation list, the **Recipient allow-list** textarea (one address, `@domain`, or E.164 phone per line), **Meta ads spend caps** (daily / monthly) with spend-versus-cap copy from `adsSpend`, configured hints on research / finance / product / meta / stores / web rows, and the collapsible call log. Keyed on the saved config like the other editors. |
| `BoardApprovalsList` | Pending / decided queue. Arguments render as a key/value table unless the approval carries a mail `preview` (`MailPreviewCard`) or phishing `preview`. **Edit…** opens labeled fields for body / message / subject (and other text args); **Edit raw JSON** remains for everything else. Approve sends the merged `arguments`. A `focusApprovalId` (from a review link) scrolls to the row and forces the decided list open. |
| `BoardMailView` | Company mail: mailbox chips with unread badges, search + unread toggle, thread list, and a detail pane. Opening an unread thread marks it read. **Board's view** swaps in the masked (`contact#N` / `phone#N`) bodies a persona sees. |
| `BoardReceivablesView` | Aging buckets (current / D+7 / D+21 / D+35) plus listing subscriptions. Empty until `SiutindeiClusterArn` and `SiutindeiDbSecretArn` are set. Overdue count is a badge on the Receivables tab. |
| `BoardStaffSection` | Executive Board staff roster grouped by manager (active toggle, tier select, brief editor via `AdminEditorSection`) and a five-column task board (`Queued / Running / Review / Needs owner / Delivered`). **New task** assigns work to a persona or active seat. The Staff tab badge is `needs_owner`. |
| `BoardTaskDrawer` | `BoardOffcanvas` for one task: brief, step log (`<details>` + `BoardToolCallList`), deliverable (`BoardMarkdown` or CSV table), last review, Accept / Return / Cancel. |

Async work (chat replies, meetings) always goes through a job row + polling hook, never a long HTTP request; keep poll deadlines aligned with `contracts/board-timeouts.json`. Containers that show polling progress (the pending chat bubble, the transcript's "phase…" line) carry `aria-live="polite"` so screen readers hear tool-progress lines as they arrive. Icon-only `<i class="bi …">` elements that convey status get `role="img"` + `aria-label`; decorative icons beside text stay `aria-hidden="true"`. Mutations live in `src/hooks/useBoard*.ts`; keep request/invalidation logic in exported `*MutationOptions(qc)` factories (see `approvalDecisionMutationOptions`, `toolsSaveMutationOptions`) so they are unit-testable in the node Vitest environment without rendering React. Tool ids, levels and defaults come from `contracts/board-tools.json`; `effectiveToolLevel()` in `boardModel.ts` mirrors the Lambda's capping rule so the matrix can preview the effect of the global mode before saving.

## Dependencies

- **Bootstrap Icons** — Imported globally in `src/main.tsx` (`bootstrap-icons/font/bootstrap-icons.css`). Use `bi` classes only for table/icon buttons per above.
- **react-markdown / remark-gfm** — Only via `BoardMarkdown`.

## Reference implementation

`HouseStatementPanel` (`src/components/HouseStatementPanel.tsx`) applies these patterns: float editor + line editor (`AdminEditorSection`), then `AdminDataTable` with filter and icon operations.
