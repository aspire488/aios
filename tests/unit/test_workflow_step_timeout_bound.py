from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from aios.models.sessions import Err
from aios.workflows.step import _resolve_agent_call
from aios.workflows.wf_script_host import _agent_error_from


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
        (timedelta(seconds=301), 1_000_000, 1_000_000, "spend"),
        (timedelta(seconds=301), 1_000_000, None, "deadline"),
    ],
)
async def test_resolve_agent_call_timeout_identifies_triggered_bound(
    now_offset: timedelta,
    ceiling: int,
    spent: int | None,
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


@pytest.mark.parametrize(
    ("bound", "expected_message"),
    [
        ("deadline", "the agent did not respond within its wall-clock deadline"),
        ("spend", "the agent stopped after reaching its spend ceiling"),
    ],
)
def test_agent_error_from_timeout_exposes_bound_and_message(
    bound: str, expected_message: str
) -> None:
    error = _agent_error_from({"kind": "timeout", "bound": bound})

    assert error.kind == "timeout"
    assert error.bound == bound
    assert str(error) == expected_message


def test_agent_error_from_legacy_timeout_preserves_message_and_has_no_bound() -> None:
    error = _agent_error_from({"kind": "timeout"})

    assert error.kind == "timeout"
    assert error.bound is None
    assert str(error) == "the agent did not respond within its wall-clock deadline"
