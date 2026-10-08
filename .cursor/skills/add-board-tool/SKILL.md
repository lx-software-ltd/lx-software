---
name: add-board-tool
description: Register an Executive Board tool so the contract, the runtime, and the tests stay aligned.
---

# Add a board tool

1. Register `ToolOp`s in `backend/lambda/admin/board_tools.py`.
2. Add the tool to `contracts/board-tools.json`.
3. Run `python3 scripts/sync-contracts.py` and `python3 scripts/check-contracts.py`.
4. Cover the op in the `test_board_t*.py` file that owns that host (mail is `test_board_mail.py`). Put the fake behind `HostRouter` or `board_data_api.set_executor_for_tests`.
5. Say in the pull request whether the new op is `off`, `read`, `propose`, or `act`, and which action class it uses.

`propose` writes land in Approvals. `act` writes with a non-zero hold class are scheduled. `ToolOp.validate` must reject a call that cannot succeed before a hold is created.

Do not put a model call on the HTTP path. Long work goes through `board_async`.
