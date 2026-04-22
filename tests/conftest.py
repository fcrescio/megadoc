import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///./test.db"
os.environ["STORAGE_BACKEND"] = "filesystem"
os.environ["LOCAL_STORAGE_PATH"] = "/tmp/megadoc-test-storage"
os.environ["OCR_BACKEND"] = "fake"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "false"

import api.main as api_main  # noqa: E402
from api.main import app, db_session_dep  # noqa: E402
from common.db.base import Base  # noqa: E402


@pytest.fixture()
def db_session(tmp_path: Path):
    db_path = tmp_path / "test.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session):
    def override_db():
        yield db_session

    app.dependency_overrides[db_session_dep] = override_db
    original_dispatch = api_main.dispatch_ingestion_job
    api_main.dispatch_ingestion_job = lambda job_id: None
    with TestClient(app) as test_client:
        yield test_client
    api_main.dispatch_ingestion_job = original_dispatch
    app.dependency_overrides.clear()
