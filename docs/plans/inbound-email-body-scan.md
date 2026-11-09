# Plan: Inbound statement mail without a PDF

**Status**: Ready
**Zone**: yellow

## Goal

A message to any statement inbox can be parsed when the bill is not a PDF.
`billing@inbound.lx-software.com`, `32-hillmarton@`, and `the-morrison@` all
use `InboundStatementMailFn`. Today that function logs `inbound_mail_no_pdf`
and skips the message, so amounts written in the body are never read.

When the message has a PDF, those PDF parts stay the only source. Otherwise
the same function, for every finance owner in `INBOUND_STATEMENT_MAILBOXES`,
queues one of:

- a receipt image, or a text, CSV, or HTML attachment, when the body does
  not itself name an amount
- the message body (plain text, or HTML reduced to text) when the subject
  or body names an amount, or is long enough to be a prose bill

The stored object uses the content type the statement parser already
accepts (`application/pdf`, `image/*`, or `text/plain`). The parser prompt
names an email body as a document it should read. No inbox is special-cased.

## Non-goals

- No line-level dedupe when a body and a file repeat the same charge. A PDF
  still suppresses the body. A body that names an amount suppresses other
  attachments so a signature image is not parsed instead of the bill.
- No change to the admin upload control, which still accepts PDF and images.
- No CDK edit. Infrastructure is red. The receipt-rule outputs still say
  "PDF inbox"; the deployment doc is the operator description.
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

None. Amount detection is a currency code or symbol next to a number, a
decimal amount, or a total, amount, balance, or charged label next to a
number. A date header alone does not count.
