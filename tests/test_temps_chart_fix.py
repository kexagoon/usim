"""Heating charts must use bumpChart and run transient before spectrum sweeps."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"


def test_bump_chart_helper_and_none_updates():
    src = APP_JS.read_text(encoding="utf-8")
    assert "function bumpChart(ch)" in src
    assert 'ch.update("none")' in src
    assert "animation: false" in src or "animation: { duration: 0 }" in src


def test_analyze_bowl_transient_before_spectrum():
    src = APP_JS.read_text(encoding="utf-8")
    # Inside analyzeBowl, transient POST must appear before spectrum GET
    start = src.find("async function analyzeBowl()")
    end = src.find("function renderBowlTransient", start)
    assert start > 0 and end > start
    body = src[start:end]
    idx_tr = body.find('postJSON("/api/bowl/transient"')
    idx_spec = body.find('getJSON("/api/bowl/spectrum')
    assert 0 <= idx_tr < idx_spec, "transient must run before spectrum in analyzeBowl"


def test_render_bowl_transient_uses_slice_and_bump():
    src = APP_JS.read_text(encoding="utf-8")
    start = src.find("function renderBowlTransient")
    end = src.find("async function resetBowl", start)
    body = src[start:end]
    assert "(s.T_piezo_c || []).slice()" in body
    assert "bumpChart(bowlCharts.temps)" in body
    assert "clearChartYAutoscale" in body
    assert "bowlCharts.temps.resize" in body
