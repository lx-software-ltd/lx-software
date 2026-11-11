# Plan: LinkedIn draft slots in Hong Kong time

**Status**: Done
**Zone**: yellow

## Goal

The LinkedIn drafts table shows each saved slot in Asia/Hong_Kong, using the
same formatter as the Calendar slot. That covers the Slot column and the slot
line under the hook, which replaces the column while it is hidden.

## Non-goals

- Calendar, Posted, and Settings already use that formatter
- Slot values stay UTC ISO instants
- Executive Board content slots stay as they are

## Files

- `docs/plans/linkedin-draft-slot-hkt.md` (this plan)
- `apps/admin_web/src/components/linkedin/LinkedInDraftsSection.tsx`
- `apps/admin_web/src/components/linkedin/LinkedInDraftsSection.test.tsx`

## Invariants this change preserves

- An empty slot stays an em dash, with no extra line under the hook
- Approving, unapproving, and storing `slotAt` are unchanged
- `formatDateTimeHKT` stays the single Hong Kong datetime format

## Done when

- `npx vitest run src/components/linkedin/LinkedInDraftsSection.test.tsx` in `apps/admin_web` passes
- `npm run lint` in `apps/admin_web` passes
- In `npm run dev:mock`, an approved draft's Slot matches the Calendar slot for the same instant

## Rollback

Restore the UTC date slice in the drafts table.

## Open questions

None.
