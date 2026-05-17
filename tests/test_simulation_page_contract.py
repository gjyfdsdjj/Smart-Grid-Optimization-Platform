from __future__ import annotations

import inspect
from pathlib import Path

from src.ui.map_overlay_renderer import render_map_overlay


_SIMULATION_PAGE = Path(__file__).resolve().parents[1] / "pages" / "02_simulation.py"


def test_simulation_page_uses_common_map_overlay_renderer():
    source = _SIMULATION_PAGE.read_text(encoding="utf-8")

    assert "from src.ui.map_overlay_renderer import render_map_overlay" in source
    assert "render_map_overlay(" in source
    assert "show_point_table=True" in source


def test_simulation_page_does_not_keep_local_folium_renderer_helpers():
    source = _SIMULATION_PAGE.read_text(encoding="utf-8")
    forbidden_fragments = [
        "def _render_overlay_map",
        "def _add_overlay_line",
        "def _add_overlay_route",
        "def _add_overlay_point",
        "def _load_map_libraries",
        "streamlit_folium",
        "folium.",
    ]

    assert all(fragment not in source for fragment in forbidden_fragments)


def test_common_renderer_supports_candidate_point_fallback_tables():
    signature = inspect.signature(render_map_overlay)

    assert "show_point_table" in signature.parameters
    assert signature.parameters["show_point_table"].default is False
