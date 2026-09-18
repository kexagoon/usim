"""API: bowl params POST keeps custom ti_diameter_m."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_post_bowl_params_custom_ti_diameter():
    client = TestClient(app)
    r = client.post("/api/bowl/params", json={"ti_diameter_m": 0.016})
    assert r.status_code == 200
    body = r.json()
    params = body["params"]
    assert abs(params["ti_diameter_m"] - 0.016) < 1e-9
    assert abs(params["cup_outer_diameter_m"] - 0.016) < 1e-9
    # Round-trip GET
    g = client.get("/api/bowl/params")
    assert g.status_code == 200
    assert abs(g.json()["params"]["ti_diameter_m"] - 0.016) < 1e-9
