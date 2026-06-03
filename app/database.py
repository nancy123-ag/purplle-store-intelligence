from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class EventRecord(Base):
    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    store_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    camera_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    visitor_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    zone_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    dwell_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    event_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class PosTransaction(Base):
    __tablename__ = "pos_transactions"

    transaction_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    store_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    basket_value_inr: Mapped[float] = mapped_column(Float, nullable=False)


engine = None
SessionLocal: sessionmaker[Session] | None = None


def default_database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite:///./data/store_intelligence.db")


def configure_database(database_url: str | None = None) -> tuple[object, sessionmaker[Session]]:
    global engine, SessionLocal

    url = database_url or default_database_url()
    if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
        db_path = url.replace("sqlite:///", "", 1)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args, future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return engine, SessionLocal


def init_db() -> None:
    global engine
    if engine is None:
        configure_database()
    Base.metadata.create_all(bind=engine)


def get_session() -> Generator[Session, None, None]:
    if SessionLocal is None:
        configure_database()
        init_db()
    assert SessionLocal is not None
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

