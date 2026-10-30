# Plan: Resume upload fixes

**Status**: Done
**Zone**: yellow

## Goal

A Word file without tracked changes uploads. The tracked-changes check matched `<w:insideH>` and `<w:insideV>` table borders as `<w:ins>`. A Word file that is rejected returns 400 and writes no row. The upload form shows the real reason when a later step fails. The Resumes and Job tracker tables line up like the other admin tables, and the upload row opens at the top as "Upload a resume" instead of a second "New resume".

## Non-goals

Retrying an existing failed row, and changing PDF or Markdown extraction.

## Files

- `backend/lambda/admin/resume_docx.py`, `resume.py`, `test_resume_docx.py`, `test_resume.py`
- `apps/admin_web/src/components/resume/ResumeListSection.tsx`, `ResumeTrackerSection.tsx`, and their tests

## Invariants this change preserves

No model call inside an HTTP request. Real insertions, deletions, and moves are still rejected. Writes still return 403 while `RESUME_ENABLED` is off. Record-table and draft-row conventions match LinkedIn and Finance.

## Done when

`python3 -m unittest` for `test_resume_docx.py` and `test_resume.py`. `npm run lint` and the resume Vitest files in `apps/admin_web`. `npm run dev:mock` shows the Resumes and Job tracker cells under their headers with the same padding as LinkedIn drafts, and the upload row at the top.

## Rollback

Revert this change. Stored rows are unchanged.

## Open questions

None. A row that already failed with the false positive can be deleted and uploaded again.
