from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    # Without this, a dead/unreachable DB can hang a connection attempt on the OS-level TCP
    # timeout (tens of seconds, worse yet through Docker Desktop's WSL2 port-forward) instead of
    # failing fast — which would make /api/health useless as a "is the DB actually down" signal.
    connect_args={"connect_timeout": 2},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
