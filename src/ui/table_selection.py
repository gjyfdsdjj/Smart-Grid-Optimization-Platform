# Streamlit dataframe selection events를 페이지 로직에서 쓰기 쉽게 변환한다.
from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def selected_value_from_dataframe_event(
    event: Any,
    rows: Sequence[dict[str, Any]],
    column: str,
) -> Any | None:
    """Return ``column`` from the first selected dataframe row.

    Streamlit returns a dataframe state object in app runtime, while tests and
    older compatibility paths often use a plain mapping. This helper keeps page
    code independent from that object shape.
    """

    selected_rows = _selected_row_indices(event)
    if not selected_rows:
        return None

    try:
        row_index = int(selected_rows[0])
    except (TypeError, ValueError):
        return None

    if row_index < 0 or row_index >= len(rows):
        return None

    return rows[row_index].get(column)


def _selected_row_indices(event: Any) -> list[Any]:
    if event is None:
        return []

    selection = _get_field(event, "selection")
    if selection is None:
        return []

    rows = _get_field(selection, "rows")
    if rows is None:
        return []

    if isinstance(rows, list):
        return rows
    if isinstance(rows, tuple):
        return list(rows)
    return []


def _get_field(value: Any, field_name: str) -> Any:
    if isinstance(value, dict):
        return value.get(field_name)
    return getattr(value, field_name, None)
