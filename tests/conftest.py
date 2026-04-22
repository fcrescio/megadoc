import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test.db")
os.environ.setdefault("STORAGE_BACKEND", "filesystem")
os.environ.setdefault("LOCAL_STORAGE_PATH", "./.test-storage")
os.environ.setdefault("OCR_BACKEND", "fake")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")

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
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

