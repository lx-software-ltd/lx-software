# Plan: Admin wait bao

**Status**: Ready
**Zone**: yellow

## Goal

Replace the white informational rows between sign-in and a filled dashboard with a quiet row on the page background, marked by a spinning char siu bao. Use the same bao, smaller and without the float, wherever the console currently shows a Bootstrap spinning wheel.

## Non-goals

- No gear icon. Settings keeps `bi-gear`.
- No tram, ferry, or other floating marks.
- No change to loaded dashboard cards, error alerts, or the "Load more" labels.
- No contracts, CDK, or deploy changes.

## Files

- `docs/plans/admin-wait-bao.md` (this plan)
- `apps/admin_web/src/components/ui/AdminWait.tsx` — `AdminBao`, `AdminWaitRow`
- `apps/admin_web/src/components/ui/AdminWait.test.tsx`
- `apps/admin_web/src/components/ui/index.ts`
- `apps/admin_web/src/styles/shell.css` — row, spin, float, reduced motion
- `apps/admin_web/src/components/FinanceDataStatus.tsx` — loading row
- `apps/admin_web/src/components/FinanceDataStatus.test.tsx`
- `apps/admin_web/src/components/LazyPage.tsx`
- `apps/admin_web/src/components/LazyPage.test.tsx`
- `apps/admin_web/src/pages/AuthCallbackPage.tsx`
- `apps/admin_web/src/pages/AuthCallbackPage.test.tsx`
- `apps/admin_web/src/components/dashboard/DashboardApiHealthCard.tsx`
- `apps/admin_web/src/components/dashboard/DashboardSessionCard.tsx`
- `apps/admin_web/src/components/dashboard/DashboardLoadingCards.test.tsx`
- `apps/admin_web/src/components/ui/AdminEditorPanel.tsx`
- `apps/admin_web/src/components/board/BoardPipelineSection.tsx`
- `apps/admin_web/src/components/board/BoardToolCallList.tsx`
- `apps/admin_web/src/components/board/BoardTranscript.tsx`
- `apps/admin_web/src/components/board/BoardChatOffcanvas.tsx`
- `apps/admin_web/src/components/HouseStatementPanel.tsx`
- `apps/admin_web/docs/UI_COMPONENTS.md`

## Invariants this change preserves

- Loading and saving copy stays the same sentences.
- API health and Session stay white cards once data or an error is known.
- A primary save button still shows `Saving…` or `Uploading…` and `aria-busy`.
- `prefers-reduced-motion: reduce` leaves the bao still. The sentence is the status.

## Done when

- `npm run test:unit` and `npm run lint` in `apps/admin_web`.
- `npm run dev:mock`, then the dashboard still renders its cards, and a delayed load shows the bao row on the canvas.

## Rollback

Revert this change. Wait copy returns to muted paragraphs and Bootstrap `spinner-border`.

## Open questions

None.
