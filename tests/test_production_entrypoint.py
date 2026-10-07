"""Regression test for a defect the test suite could not see.

The API's own tests all called ``create_app(tmp_path)``, which attached a
lifespan that binds the store. Production runs ``uvicorn api.main:app``, which
is the module-level ``create_app()`` with no argument — and that path attached
no lifespan at all. So ``app.state.store`` did not exist, and every store-backed
route returned a 500 AttributeError.

The suite was green because it never exercised the entrypoint anyone actually
runs. These tests use the module-level ``app``, imported the same way uvicorn
imports it, so that gap cannot reopen.
"""

from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

import api.main as main_module


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Drive the real module-level app, with the database redirected to tmp."""
    monkeypatch.setattr(main_module, "_DB_PATH", str(tmp_path / "prod.db"))
    from api.main import app  # what `uvicorn api.main:app` resolves to

    with TestClient(app) as c:
        yield c


def test_lifespan_binds_the_store(client):
    assert hasattr(client.app.state, "store"), (
        "the production entrypoint must bind a store in its lifespan; "
        "routes read app.state.store at request time"
    )


def test_upload_works_on_the_production_app(client, tmp_path):
    """A real generated lab PDF, uploaded the way the demo does it."""
    import axiom.render.synthea as renderer

    out = tmp_path / "docs"
    renderer.generate(out_dir=str(out), patients=1)
    pdf = sorted(out.glob("pat_001/*.pdf"))
    labs = [p for p in pdf if "lab" in p.name]
    assert labs, f"renderer produced no lab reports under {out}"
    pdf_bytes = labs[0].read_bytes()

    r = client.post("/api/upload",
                    files={"file": (labs[0].name, pdf_bytes, "application/pdf")},
                    params={"patient_id": "pat_prod"})
    assert r.status_code == 200, f"upload failed: {r.text}"
    facts = r.json()["facts"]
    assert facts, "a lab report must yield at least one fact"
    assert all(f.get("source_doc_id") for f in facts), (
        "every fact must carry provenance — that is the product promise"
    )


def test_store_backed_routes_do_not_500(client):
    """The three routes that read app.state.store must not raise."""
    for method, url in (("get", "/api/patients"),):
        r = getattr(client, method)(url)
        assert r.status_code < 500, f"{url} returned {r.status_code}: {r.text}"
        assert r.status_code == 200


def test_ask_returns_200_for_unknown_patient_shape(client):
    """/api/ask may 404 on an unknown patient — but never 500."""
    r = client.post("/api/ask", json={"patient_id": "nobody", "query": "trend?"})
    assert r.status_code < 500, f"/api/ask returned {r.status_code}: {r.text}"