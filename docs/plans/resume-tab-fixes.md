# Plan: Resume tab review fixes

**Status**: Done
**Zone**: yellow

## Goal

Close the gaps found in the Resume tab review. Writes stay blocked while `RESUME_ENABLED` is off, including a pasted job post. Model cost from extract, job-post analysis, and a length retry counts toward the monthly cap, and a failed run keeps the cost already incurred. A tailor or extract job finishes or fails inside the existing Lambda limit, and a poll marks a stuck job failed and settles its reservation. Forms start empty, the tracker can pick a job post, dates are real dates, and downloads and unsaved-edit prompts match the screen the user is leaving.

## Non-goals

Changing the Admin API Lambda timeout, memory, or CDK parameters. Pixel-identical PDF. Fetching job ads from a URL.

## Files

- `backend/lambda/admin/resume.py`, `resume_spend.py`, `resume_tailor.py`, `resume_extract.py`, `resume_store.py`, `resume_tracker.py`, `test_resume.py`
- `apps/admin_web/src/components/resume/*`, `components/ui/AdminEditorPanel.tsx`, `lib/downloadBase64.ts`, `lib/mock/routes/resume.ts`, tests

## Invariants this change preserves

No model call inside an HTTP request. `RESUME_ENABLED` off means no write, including a posting created while queueing a tailor run. Locked paragraphs still come from the template. The template file is never modified. Spend is booked as service `resume`. The worker stays inside the existing 300 second Lambda: the job budget is 220 seconds and a poll finalizes a job still running after 280 seconds. Allowlisted files do not grow.

## Done when

`python3 -m unittest discover -s backend/lambda/admin -p 'test_resume.py' -v`. `npm run test:unit` and `npm run lint` in `apps/admin_web`. `npm run dev:mock` covers an empty New resume form, a job-post field on the tracker, original-file download, and the unsaved-edit prompt when leaving a section.

## Rollback

Revert this change. `LxSoftwareResumeEnabled` stays false until someone turns it on.

## Open questions

None. A killed worker cannot know tokens that were never recorded, so a stale job settles whatever cost was saved on the job and releases the rest of the reservation.
