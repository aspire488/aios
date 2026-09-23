from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from aios.models.sessions import Err
from aios.workflows.step import _resolve_agent_call


class _Transaction:
    async def __aenter__(self) -> _Transaction:
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("now_offset", "ceiling", "spent", "expected_bound"),
    [
        (timedelta(seconds=301), 0, 0, "deadline"),
        (timedelta(seconds=10), 1_000_000, 1_000_000, "spend"),
    ],
)
async def test_resolve_agent_call_timeout_identifies_triggered_bound(
    now_offset: timedelta,
    ceiling: int,
    spent: int,
    expected_bound: str,
) -> None:
    conn = AsyncMock()
    conn.fetchval.return_value = spent
    conn.transaction = MagicMock(return_value=_Transaction())
    written = Err(error={"kind": "timeout", "bound": expected_bound})
    write = AsyncMock(return_value=True)
    with (
        patch("aios.workflows.step.get_settings", return_value=Mock(cancel_cascade_enabled=False)),
        patch(
            "aios.workflows.step.db_queries.derive_response",
            side_effect=[None, written],
        ),
        patch("aios.workflows.step.db_queries.write_response_if_absent", new=write),
    ):
        result = await _resolve_agent_call(
            conn,
            account_id="account",
            child_id="child",
            request_id="request",
            started_at=datetime(2026, 9, 23, tzinfo=UTC),
            now=datetime(2026, 9, 23, tzinfo=UTC) + now_offset,
            deadline=timedelta(seconds=300),
            cost_ceiling_microusd=ceiling,
        )

    # The re-derive is mocked, so the product contract lives in what gets WRITTEN.
    write.assert_awaited_once_with(
        conn,
        "child",
        account_id="account",
        request_id="request",
        outcome=written,
    )
    assert result is written
