from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError

from app import anomalies, database, funnel, health, heatmap, ingestion, metrics
from app.database import configure_database, init_db
from app.errors import (
    database_exception_handler,
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.pos import load_pos_csv
from app.request_logging import RequestLoggingMiddleware
from app.store_config import load_layout


def create_app(
    database_url: str | None = None,
    pos_path: str | None = None,
    layout_path: str | None = None,
) -> FastAPI:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    configure_database(database_url)

    @asynccontextmanager
    async def lifespan(api: FastAPI):
        init_db()
        if database.SessionLocal is not None:
            with database.SessionLocal() as db:
                load_pos_csv(db, api.state.pos_path)
        yield

    api = FastAPI(
        title="Store Intelligence API",
        version="1.0.0",
        description="Offline retail analytics API for CCTV-derived behavioural events.",
        lifespan=lifespan,
    )
    api.state.pos_path = pos_path if pos_path is not None else os.getenv("POS_PATH", "data/raw/pos_transactions.csv")
    api.state.layout_path = (
        layout_path if layout_path is not None else os.getenv("STORE_LAYOUT_PATH", "data/raw/store_layout.json")
    )
    api.state.layout = load_layout(api.state.layout_path)

    api.add_middleware(RequestLoggingMiddleware)
    api.add_exception_handler(HTTPException, http_exception_handler)
    api.add_exception_handler(RequestValidationError, validation_exception_handler)
    api.add_exception_handler(SQLAlchemyError, database_exception_handler)
    api.add_exception_handler(Exception, unhandled_exception_handler)

    api.include_router(ingestion.router)
    api.include_router(metrics.router)
    api.include_router(funnel.router)
    api.include_router(heatmap.router)
    api.include_router(anomalies.router)
    api.include_router(health.router)

    return api


app = create_app()
