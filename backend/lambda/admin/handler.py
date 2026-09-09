"""Admin HTTP API — Lambda entrypoint and backward-compatible re-exports."""

from __future__ import annotations

from contract_constants import (
    DEFAULT_EXPENSE_INCOME_ALLOCATION_PERCENTAGES,
    EXPENSE_RECORD_CATEGORIES,
    FINANCE_HOUSE_KEYS,
    INCOME_RECORD_CATEGORIES,
    MAX_SOURCE_ASSET_KEYS_PER_LINE,
)
from dispatch import lambda_handler

from assets import (  # noqa: F401
    _asset_delete_response,
    _asset_download_presigned_response,
    _assets_list_response,
    _is_allowed_upload_content_type,
    _normalize_public_asset_key,
)
from finance_store import (  # noqa: F401
    _build_allocation_records_for_response,
    _derived_expense_rows_from_tagged_income,
    _load_investment_records,
    _merge_accounts_last_updated,
    _merge_allocation_stored_last_updated,
    _merge_investment_last_updated,
    _merge_pension_last_updated,
    _normalize_accounts_sheet_payload,
    _normalize_allocations_sheet_payload,
    _normalize_finance_payload,
    _merge_liabilities_last_updated,
    _normalize_investment_sheet_payload,
    _normalize_ledger_sheet_payload,
    _normalize_liabilities_sheet_payload,
    _normalize_pension_sheet_payload,
    _normalize_savings_sheet_payload,
    _sanitize_accounts_records_list,
    _sanitize_liabilities_records_list,
    _sanitize_expense_income_allocation_percentages,
    _sanitize_investment_records_list,
    _sanitize_ledger_records_list,
    _sanitize_pension_records_list,
    _sanitize_savings_records_list,
)
from bank_sync import (  # noqa: F401
    _build_eb_jwt,
    _consent_valid_until,
    _load_bank_sync_state,
    _pick_balance,
    _summarize_session_accounts,
    bank_sync_enabled,
    run_bank_sync,
)
from http_common import _groups_include_admin, _utc_iso_z  # noqa: F401
from parse_jobs import (  # noqa: F401
    _finalize_stuck_processing_job,
    _handle_parse_statement_async_worker,
    _parse_job_public_doc,
    _path_finance_parse_job,
    _path_siu_tin_dei_parse_job,
    enqueue_parse_statement_async_job,
)
from parse_statement import (  # noqa: F401
    _path_finance_house_for_parse,
    _resolve_parse_line_type_filter,
    _statement_basename_already_imported,
    execute_parse_statement,
)
from proxies import (  # noqa: F401
    _normalize_finance_quote_symbol,
    _normalize_yahoo_price_currency,
    _parse_finance_quotes_query,
    _parse_fx_v2_rates_query,
)

__all__ = [
    "DEFAULT_EXPENSE_INCOME_ALLOCATION_PERCENTAGES",
    "EXPENSE_RECORD_CATEGORIES",
    "FINANCE_HOUSE_KEYS",
    "INCOME_RECORD_CATEGORIES",
    "MAX_SOURCE_ASSET_KEYS_PER_LINE",
    "lambda_handler",
    "execute_parse_statement",
    "enqueue_parse_statement_async_job",
]
