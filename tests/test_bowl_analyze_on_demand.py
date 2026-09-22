"""Bowl analysis must run only on Analysieren — no auto API queue from UI hooks."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"


def test_app_js_analyze_bowl_only_from_button():
    src = APP_JS.read_text(encoding="utf-8")
    assert "bowlAnalyzeBusy" in src
    assert "btnBowlAnalyze" in src
    assert 'addEventListener("click", analyzeBowl)' in src or "addEventListener(\"click\", analyzeBowl)" in src

    # switchTab must not auto-analyze
    assert "if (name === \"bowl\") { ensureBowl(); }" in src or "if (name === 'bowl') { ensureBowl(); }" in src
    assert "ensureBowl(); analyzeBowl()" not in src

    # freq chips: set f0 + sync only
    assert "syncBowlFreqChips();" in src
    # no analyzeBowl() immediately after syncBowlFreqChips in chip handler
    idx = src.find('querySelectorAll("#bowlFreqChips')
    assert idx > 0
    chunk = src[idx : idx + 280]
    assert "analyzeBowl()" not in chunk

    # power presets: setBowlDriveLevel only
    idx = src.find('querySelectorAll("#bowlPowerPresets')
    assert idx > 0
    chunk = src[idx : idx + 220]
    assert "setBowlDriveLevel" in chunk
    assert "analyzeBowl()" not in chunk

    # loadBowlPreset / resetBowl must not await analyzeBowl
    assert "await analyzeBowl()" not in src

    # only one intentional call site besides definition/warn: the button listener
    # Count invoke patterns excluding definition and console.warn
    lines = [ln.strip() for ln in src.splitlines() if "analyzeBowl" in ln]
    invoke = [ln for ln in lines if "analyzeBowl()" in ln or "analyzeBowl);" in ln or 'analyzeBowl)' in ln]
    # Allowed: function analyzeBowl(), console.warn("analyzeBowl", ...), addEventListener(..., analyzeBowl)
    bad = [
        ln
        for ln in invoke
        if not ln.startswith("async function analyzeBowl")
        and "console.warn" not in ln
        and "addEventListener" not in ln
    ]
    assert bad == [], f"unexpected analyzeBowl triggers: {bad}"


def test_build_stamp_temps_chart_fix():
    client = TestClient(app)
    r = client.get("/api/build")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == "1.3.3-bond-wide"
    assert "bond-press-cure-wide" in body["usim_build"]
    note = body.get("note", "").lower()
    assert "fullscreen" in note or "chart" in note or "ti" in note
