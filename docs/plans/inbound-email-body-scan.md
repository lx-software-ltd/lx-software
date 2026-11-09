# Plan: Inbound statement mail without a PDF

**Status**: Ready
**Zone**: yellow

## Goal

A message to any statement inbox can be parsed when the bill is not a PDF.
`billing@inbound.lx-software.com`, `32-hillmarton@`, and `the-morrison@` all
use `InboundStatementMailFn`. A message with nothing to read is logged
and left in the raw bucket. A body that names an amount is parsed.

When the message has a PDF, including a `.pdf` file that is not labelled
`application/pdf`, those parts stay the only source. Otherwise the same
function, for every finance owner in `INBOUND_STATEMENT_MAILBOXES`, queues:

- an itemised text, CSV, or HTML attachment, or a receipt image that is
  not inline and not a decorative name such as `logo`
- otherwise the message body, only when the subject or body names an amount

An amount is a currency code or HK$/US$ figure, a currency symbol with
cents, or a total, amount, balance, or charged label beside a number. A
date, a version, a discount such as "$10 off", or a long note that merely
contains a digit is not parsed. Each body file is named from the subject
and a short digest of the text, so a later body is not the same filename.
Text and image parses set `data_collection: deny`. The prompt tells the
model to return itemised charges instead of also returning the total.
No inbox is special-cased.

## Non-goals

- No line-level dedupe inside one parsed file. An itemised attachment is
  parsed instead of the body, so the total in the body is not added beside
  the lines. A PDF still suppresses everything else.
- No change to the admin upload control, which still accepts PDF and images.
- Receipt-rule output text no longer says "PDF inbox". No receipt rule,
  bucket, or permission changes.
- Evolve Sprouts `InboundInvoiceEmailProcessor` is not in this repository.
- A message already skipped is left under `inbound-raw/` and is not
  replayed. Send it again after deploy. The raw object is deleted only
  once a parse job is queued, which is the existing PDF behaviour.

## Files

- `docs/plans/inbound-email-body-scan.md` (this plan)
- `backend/lambda/admin/inbound_statement_sources.py` — choose PDF, attachment, or body
- `backend/lambda/admin/inbound_email_handler.py` — queue that choice for every inbox
- `backend/lambda/admin/openrouter_statement_parser.py` — prompt covers email text
- `backend/lambda/admin/test_inbound_email_handler.py`
- `backend/lambda/admin/test_openrouter_statement_parser.py`
- `docs/deployment/admin-website.md`
- `backend/infrastructure/lib/admin-outputs.ts` — output description text
- `backend/infrastructure/lib/inbound-mail.ts` — comment only

## Invariants this change preserves

- A PDF attachment is copied as `application/pdf` and is the only source
  for that message. Filename sanitising for PDFs is unchanged.
- House mailboxes still parse every line type. `billing@` still passes
  `lineTypeOnly=expenditure` for the LX Software book.
- Unknown prefixes, oversize objects, and a message with nothing to read
  still skip the parse job and leave the raw object in place.
- The board mailbox (`siutindei-board@`) still goes to `board_mail` and is
  not parsed as a statement.

## Done when

- `python3 -m unittest test_inbound_email_handler test_openrouter_statement_parser -v`
  in `backend/lambda/admin` passes.
- `python3 -m ruff check backend/lambda/admin/inbound_statement_sources.py backend/lambda/admin/inbound_email_handler.py backend/lambda/admin/openrouter_statement_parser.py backend/lambda/admin/test_inbound_email_handler.py backend/lambda/admin/test_openrouter_statement_parser.py` passes.
- `python3 scripts/check_file_length.py` passes.

## Rollback

Revert this change. Messages without a PDF are skipped again. PDF imports
are unchanged.

## Open questions

None. A bare decimal and a currency symbol without cents are not amounts.
