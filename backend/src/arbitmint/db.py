from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str | None = None):
    url = database_url or os.getenv("DATABASE_URL", "sqlite:///./arbitmint.db")
    options: dict[str, object] = {"pool_pre_ping": True}
    if url.startswith("sqlite:"):
        options["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **options)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def initialize_database() -> None:
    from arbitmint import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
