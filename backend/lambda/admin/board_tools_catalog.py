"""Tool operations for the catalog family."""

from __future__ import annotations

from typing import Any

import board_catalog_import
from board_tools_core import (
    REASON_PARAM,
    ToolContext,
    ToolOp,
    _int_param,
    _obj,
    _str_param,
    _summ,
)
from contract_constants import (
    BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
)


def _run_catalog_bulk_import(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    import board_catalog_bulk

    return board_catalog_bulk.op_import_source(ctx, args)

def ops() -> list[ToolOp]:
    return [
        ToolOp(
            name="catalog_preview",
            tool_id="catalog",
            kind="read",
            description=(
                "Transform an accepted catalog micro-batch sheet into siutindei importer JSON. "
                "Copies verified_fields only. Does not call the importer."
            ),
            parameters=_obj(
                {
                    "taskId": _str_param("Staff task id of the catalog sheet.", max_len=40),
                    "sheet": _str_param("Optional sheet JSON; defaults to the task deliverable.", max_len=12000),
                },
                ["taskId"],
            ),
            run=board_catalog_import.op_preview,
            summarize=_summ("Previewed catalog import for {taskId}"),
        ),
        ToolOp(
            name="catalog_dry_run",
            tool_id="catalog",
            kind="read",
            description=(
                "Local verified-fields dry-run of a catalog sheet, plus a remote dry_run when "
                "the siutindei admin API is configured. Never writes the catalog."
            ),
            parameters=_obj(
                {
                    "taskId": _str_param("Staff task id of the catalog sheet.", max_len=40),
                    "sheet": _str_param("Optional sheet JSON; defaults to the task deliverable.", max_len=12000),
                },
                ["taskId"],
            ),
            run=board_catalog_import.op_dry_run,
            summarize=_summ("Dry-ran catalog import for {taskId}"),
            timeout_seconds=BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
        ),
        ToolOp(
            name="catalog_import",
            tool_id="catalog",
            kind="write",
            always_propose=True,
            action_class="catalog_import",
            description=(
                "Propose importing the accepted catalog-micro-batch deliverable through the "
                "siutindei admin importer. Uses the stored sheet only (no sheet override). "
                "Always an Approval. Refused while SiutindeiBoardCatalogImportEnabled is false "
                "or the task is not waiting to import. Does not write Aurora from this stack."
            ),
            parameters=_obj(
                {
                    "taskId": _str_param("Staff task id of the catalog sheet waiting to import.", max_len=40),
                    "reason": REASON_PARAM,
                },
                ["taskId", "reason"],
            ),
            run=board_catalog_import.op_import,
            summarize=_summ("Import catalog sheet {taskId}"),
            timeout_seconds=BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
        ),
        ToolOp(
            name="catalog_bulk_import",
            tool_id="catalog",
            kind="write",
            always_propose=True,
            action_class="catalog_import",
            description=(
                "Import approved catalog candidates from one bulk source (lcsd, edb, swd, "
                "places, competitor). Auto-import schedules this as an internal hold."
            ),
            parameters=_obj(
                {
                    "source": _str_param("Bulk source id.", enum=["lcsd", "edb", "swd", "places", "competitor"]),
                    "reason": REASON_PARAM,
                    "limit": _int_param(
                        "Max approved rows to import. Auto-import sets the room left under the launch target.",
                        minimum=1,
                        maximum=5000,
                    ),
                },
                ["source", "reason"],
            ),
            run=_run_catalog_bulk_import,
            summarize=_summ("Import catalog source {source}"),
            timeout_seconds=BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
        ),
    ]
