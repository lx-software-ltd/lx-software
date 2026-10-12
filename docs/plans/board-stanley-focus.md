# Plan: Neighbourhood-first catalog go-live (Stanley focus)

**Status**: Implemented
**Zone**: yellow

## Goal

The owner goes live one neighbourhood at a time: Stanley, then the rest of
Southern, then Hong Kong Island, then everywhere. The catalog pipeline
(micro-batch sheets, Places discovery, candidate approval, bulk import,
Progress) must work the current neighbourhood first instead of rotating
through all 18 districts, and the owner or the board API key must be able to
queue hand-sourced Stanley organisations (web research, competitor
listings) without a sheet.

## Non-goals

- Changing `contracts/board-staff.json` (red zone). The area list, the
  default focus, the go-live district order, the focus Places queries, the
  `manual` source and the `places_class` / `places_sport` categories are
  Python constants in `board_catalog_focus.py` until the owner approves a
  contract change.
- Any LLM call in the new paths. Area placement is text / alias / circle
  matching only.
- Writing the product database. Import still goes through the siutindei
  importer and the existing `catalog_import` hold.

## Files

- `backend/lambda/admin/board_catalog_focus.py` (new): `AREAS`,
  `FOCUS_AREAS_DEFAULT`, `DEFAULT_FOCUS_DISTRICTS`, `FOCUS_QUERIES`,
  `FOCUS_KIND_CATEGORY`, `MANUAL_SOURCE`; `focus_area_ids`,
  `focus_district_names` (membership), `priority_district_names` /
  `order_districts` (rotation order), `area_for`, `is_focus_row`,
  `normalize_focus_settings`, `brief_paragraph`.
- `board_store.normalize_catalog_config` copies `focusAreas` /
  `focusDistricts` (strict on owner PUT).
- `board_catalog.py`: `next_district` issues one neighbourhood sheet per
  focus area first (`eventRef.areaId`, claim `catalog:southern:stanley`),
  then districts in go-live order; `compose_brief` adds the `FOCUS —`
  paragraph.
- `board_places.py`: `location` in the field mask (lat / lng on every
  place), `discover_area` (text query + `locationBias` circle, cached).
- `board_catalog_discovery.py`: `discover_focus_areas` before the
  3-district rotation; results outside the area are dropped.
- `board_catalog_candidates.py`: `area` stamp, `focus_auto_approvable`,
  `add_manual`, `area=` filter, focus kinds in `category_for`.
- `board_catalog_bulk.py`: `BULK_SOURCES` (contract + `manual`),
  focus-first ordering in `_approved_for_source`, `focus_counts`,
  launch-target bypass for focus rows in `maybe_queue_auto_imports`.
- `board_routes.py`: `POST /catalog/candidates` (key-allowed with
  `allowWrite`), `GET /catalog/candidates?area=`.
- `board_catalog_import.catalog_coverage` and `board_review` report the
  focus label.
- `apps/admin_web`: `focus` block on Progress, `manual` in the source
  filter, mock route.
- Docs: `docs/architecture/executive-board.md` §6.4.1,
  `docs/deployment/admin-website.md`.

## Invariants this change preserves

- Kill switches fail closed; catalog import still needs
  `SiutindeiBoardCatalogImportEnabled` and the `catalog_import` hold.
- Owner-only routes stay owner-only (`write_blocked` unchanged). The new
  `POST /catalog/candidates` is a queue write like `PUT /actions/{id}`.
- No model call in an HTTP request; no `print()`.
- `focusAreas: []` restores the previous behaviour everywhere; the default
  district order changes rotation order only, not membership.
- Tests use fictional organisations and `example.com`.

## Done when

- `python3 -m ruff check backend/lambda scripts`
- `cd backend/lambda/admin && env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY python3 -m unittest discover -p "test_*.py"`
  (new `test_board_catalog_focus.py`; `test_board_catalog.py` and
  `test_board_review.py` updated)
- `bash scripts/check-pii.sh`, `python3 scripts/check-contracts.py`
- `cd apps/admin_web && npx vitest run && npm run lint && npm run build`
- After deploy: `GET …/catalog/sources` returns `focus.label ==
  "Stanley (Southern)"`; the next micro-batch sheet is
  `catalog:southern:stanley`; `POST …/catalog/candidates` with a Stanley
  address returns 201 with `area: "stanley"`.

## Rollback

Revert the PR. Candidate rows keep an extra `area` attribute, which the
previous code ignores. `settings.catalog.focusAreas` / `focusDistricts`
are dropped by the previous `normalize_catalog_config`.

## Open questions

- Red zone: move `AREAS`, the default focus, the district order,
  `focusQueries`, `bulkSources + manual` and the two `sourceCategory`
  entries into `contracts/board-staff.json` so the SPA Settings page can
  list the areas. Needs explicit owner approval before any contract write.
