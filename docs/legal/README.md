# Legal documents

## Canonical source

The public website is the single canonical host for LX Software legal
documents. Privacy Policy and Terms & Conditions live in
`apps/public_www/src/content/site.json` (`legal.privacy` and `legal.terms`)
and render at `/privacy` and `/terms`.

## Key facts encoded in the documents

- Legal entity: LX Software, a sole proprietorship registered in Hong Kong.
- Proprietor: the public website owner name in `site.owner`.
- Contact mailbox: `hello@lx-software.com`.
- Hosting and analytics: described on `/privacy` (server logs, Google
  Analytics 4 through Tag Manager, Global Privacy Control / Do Not Track).

The Organization JSON-LD `legalName` is the registered name `LX Software`.
The footer repeats the sole-proprietorship phrase from
`chrome.copyrightLegalForm`.

## Update procedure

1. Edit `legal.privacy` / `legal.terms` in `apps/public_www/src/content/site.json`.
2. Bump each document's `updated` date.
3. Deploy with the normal public-website flow.
