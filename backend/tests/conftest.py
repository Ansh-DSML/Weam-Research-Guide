import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app import graph_pipeline, models  # noqa: F401  (models registers Company on Base.metadata)
from app.db import Base, get_session
from app.extraction.fake_extractor import FakeExtractor
from app.main import app

TEST_DB_NAME = "weam_research_test"
ADMIN_URL = "postgresql://weam:weam_dev_local_only@localhost:5433/postgres"
TEST_DB_URL = f"postgresql+psycopg://weam:weam_dev_local_only@localhost:5433/{TEST_DB_NAME}"


@pytest.fixture(scope="session")
def test_engine():
    admin_conn = psycopg.connect(ADMIN_URL, autocommit=True)
    with admin_conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)")
        cur.execute(f"CREATE DATABASE {TEST_DB_NAME}")
    admin_conn.close()

    engine = create_engine(TEST_DB_URL)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()

    admin_conn = psycopg.connect(ADMIN_URL, autocommit=True)
    with admin_conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)")
    admin_conn.close()


@pytest.fixture()
def db_session(test_engine):
    session_local = sessionmaker(bind=test_engine)
    session = session_local()
    yield session
    session.close()
    with test_engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE companies RESTART IDENTITY CASCADE"))


@pytest.fixture()
def api_client(test_engine):
    session_local = sessionmaker(bind=test_engine)

    def override_get_session():
        session = session_local()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    # background graph extraction must never touch the real dev DB or the real Groq API
    # during tests — point it at the disposable test schema and a deterministic fake extractor.
    app.dependency_overrides[graph_pipeline.get_default_session_factory] = lambda: session_local
    app.dependency_overrides[graph_pipeline.get_default_extractor] = lambda: FakeExtractor()
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
    with test_engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE companies RESTART IDENTITY CASCADE"))
