"""FastAPI application entrypoint.

Run with::

    uvicorn api.main:app --reload --port 8000

The store is created in the lifespan handler rather than at import time so tests
can point ``AXIOM_DB`` at a tmp file, or construct the app directly and swap
``app.state.store`` for an in-memory instance.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from axiom.store import Store

from .routes import router, set_llm_client

__all__ = ["app", "create_app", "get_store"]

_DB_PATH = os.environ.get("AXIOM_DB", "axiom.db")


def get_store(path: Optional[str] = None) -> Store:
    return Store(path or _DB_PATH)


def _make_lifespan(db_path: Optional[str]):
    """Build a lifespan that binds the store for BOTH the factory path and the
    module-level `app`.

    This used to be attached only when `db_path` was passed. Every test called
    `create_app(tmp_path)` and therefore got a store, while `uvicorn
    api.main:app` — which is `create_app()` with no path — got no lifespan at
    all, so `app.state.store` never existed and every store-backed route
    returned a 500. The test suite could not see it because it never exercised
    the production entrypoint.
    """

    @asynccontextmanager
    async def _lifespan(application: FastAPI):
        application.state.store = get_store(db_path)
        try:
            from axiom.llm import LLMClient  # type: ignore

            set_llm_client(LLMClient())
        except Exception:
            # No key, no module, no client — AXIOM still answers and still
            # refuses correctly. The LLM is an assist over the planner, never a
            # dependency of correctness.
            set_llm_client(None)
        yield
        store: Optional[Store] = getattr(application.state, "store", None)
        if store is not None:
            store.close()

    return _lifespan


def create_app(db_path: Optional[str] = None) -> FastAPI:
    """Application factory — ``db_path`` is what the tests inject a tmp file into."""
    application = FastAPI(
        title="AXIOM",
        version="1.0.0",
        description="Calibrated clinical reasoning that refuses when the record "
                    "cannot support an answer.",
        lifespan=_make_lifespan(db_path),
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(router)

    @application.get("/")
    def root() -> dict:
        return {"service": "AXIOM", "docs": "/docs", "health": "/api/health"}

    return application


app = create_app()