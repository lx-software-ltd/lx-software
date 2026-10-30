# Plan: Resume tab

**Status**: Done
**Zone**: yellow, with red routes and the `LxSoftwareResumeEnabled` parameter

## Goal

Add a Resume tab on LX Software, after LinkedIn. Resumes stores Word, PDF, and Markdown files and picks one Word file as the template. New resume rewrites only the allowed paragraphs of that template for a job post and saves a new `.docx`. Job tracker records the resume, company, position, and recruiter. Settings holds the model and the generation limits. PDF download is rendered from the paragraph map.

## Non-goals

Pixel-identical PDF of the Word file, legacy `.doc`, URL fetching of job ads, reminders, and a new OpenRouter app entry.

## Files

- `apps/admin_web/src/components/resume/*`, `hooks/useResume.ts`, `lib/resumeModel.ts`, `lib/pollJob.ts`, `lib/downloadBase64.ts`, mock route, shell tab edits
- `backend/lambda/admin/resume.py`, `resume_store.py`, `resume_docx.py`, `resume_extract.py`, `resume_tailor.py`, `resume_guard.py`, `resume_pdf.py`, tests, `requirements.txt`, static fonts
- `backend/lambda/admin/dispatch.py` (route, workers, `/records` filter) without growing the allowlisted file
- Red: `backend/infrastructure/lib/admin-api-routes.ts`, `admin-parameters-product.ts`, `admin-api-env.ts`, `admin-api-function.ts`, `params/production.json`, `test/lxsoftware-stack.test.ts`

## Invariants this change preserves

No model call inside an HTTP request. `RESUME_ENABLED` defaults off and writes return 403. `RESUME#` rows stay out of `/records`. Locked paragraphs are merged from the template and are not model output. The template file is never modified. No real personal data in source, fixtures, or tests. Record-table, kebab, and `ConfirmDialog` conventions stay. Allowlisted files do not grow.

## Done when

`npm run lint`, `npm test`, and `npm run build` in `apps/admin_web`. `python3 -m ruff check backend/lambda scripts`. `python3 scripts/check_file_length.py`, `scripts/check-pii.sh`, and `scripts/check_test_focus.py`. `npm test` and `npm run build` in `backend/infrastructure`. `npm run dev:mock` exercises upload, tailor, tracker, settings, `.docx` download, and PDF view. `npm run test:e2e` covers the Resume tab.

## Rollback

Set `LxSoftwareResumeEnabled` to `false`. Writes return 403 and the tab shows the disabled notice. Data lives under `RESUME#` and the `resume/` object prefix.

## Open questions

None. The template is one `.docx` at a time. Tailored resumes are immutable. Bullet count stays the same unless Settings chooses flex. New skills are off unless Settings allows them, and then they are listed on the resume. PDF is a rendered copy. Spend cap defaults to 5 USD per month. Usage is booked as service `resume`.
