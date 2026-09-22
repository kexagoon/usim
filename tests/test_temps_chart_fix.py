"""Heating charts: bumpChart, transient-first, destroy/recreate temps, dedicated refresh."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"
INDEX = ROOT / "app" / "templates" / "index.html"


def test_bump_chart_helper_and_none_updates():
    src = APP_JS.read_text(encoding="utf-8")
    assert "function bumpChart(ch)" in src
    assert 'ch.update("none")' in src
    assert "animation: false" in src or "animation: { duration: 0 }" in src


def test_analyze_bowl_transient_before_spectrum():
    src = APP_JS.read_text(encoding="utf-8")
    start = src.find("async function analyzeBowl()")
    end = src.find("function renderBowlTransient", start)
    assert start > 0 and end > start
    body = src[start:end]
    idx_tr = body.find('postJSON("/api/bowl/transient"')
    idx_spec = body.find('getJSON("/api/bowl/spectrum')
    assert 0 <= idx_tr < idx_spec, "transient must run before spectrum in analyzeBowl"


def test_render_bowl_transient_recreates_temps_chart():
    src = APP_JS.read_text(encoding="utf-8")
    start = src.find("function renderBowlTransient")
    end = src.find("async function refreshBowlTempsOnly", start)
    if end < 0:
        end = src.find("async function resetBowl", start)
    body = src[start:end]
    assert "ensureTempsChartFresh" in body
    assert "freshArray(s.T_piezo_c)" in body
    assert "recreateLineChart" in src
    assert "function buildTempsChart" in src
    assert "function refreshBowlTempsOnly" in src
    assert 'postJSON("/api/bowl/transient"' in src[src.find("async function refreshBowlTempsOnly") :]


def test_temps_refresh_button_in_html():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="btnBowlTempsRefresh"' in html
    assert "bowl.btn_temps_refresh" in html
    assert 'data-chart-expand="chartBowlTemps"' in html
