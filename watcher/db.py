import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from watcher.models import Base


def get_engine(database_url: str | None = None):
    url = database_url or os.environ.get("DATABASE_URL", "sqlite:///watcher.db")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return create_engine(url)


def get_session_factory(database_url: str | None = None) -> sessionmaker:
    engine = get_engine(database_url)
    return sessionmaker(bind=engine)


def init_db(database_url: str | None = None):
    engine = get_engine(database_url)
    Base.metadata.create_all(engine)
    return engine
