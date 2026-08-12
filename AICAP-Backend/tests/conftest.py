"""
Shared pytest fixtures for the AICAP backend test-suite.

The application modules (``database``, ``auth``, ``main`` …) are imported with
top-level absolute imports, so the tests must run with ``AICAP-Backend`` as the
working directory / rootdir (see ``pytest.ini``).

``DATABASE_URL`` and ``SECRET_KEY`` are pinned *before* the application modules
are imported, because ``database.py`` builds its engine at import time.
"""

import os
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

_TEST_DB_PATH = Path(tempfile.gettempdir()) / "aicap_test.db"
if _TEST_DB_PATH.exists():
    _TEST_DB_PATH.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"
os.environ["SECRET_KEY"] = "test-secret-key"

import bcrypt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import database  # noqa: E402
import scheduler as scheduler_module  # noqa: E402
from auth import create_access_token  # noqa: E402
from main import app  # noqa: E402
from models import (  # noqa: E402
    Alarm,
    AlarmEvent,
    AlarmTypeEnum,
    Base,
    DifficultyEnum,
    ProviderEnum,
    RoleEnum,
    User,
)


@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    Base.metadata.create_all(bind=database.engine)
    yield
    Base.metadata.drop_all(bind=database.engine)


@pytest.fixture(autouse=True)
def db(_create_schema):
    """A clean database session per test."""
    session = database.SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
        session.close()


@pytest.fixture(autouse=True)
def clean_scheduler():
    """Keep the module-level APScheduler free of jobs between tests."""
    yield
    for job in list(scheduler_module.scheduler.get_jobs()):
        scheduler_module.scheduler.remove_job(job.id)


@pytest.fixture
def client():
    # Instantiated without the context-manager form so the lifespan hook (which
    # would start the real APScheduler daemon) does not run.
    return TestClient(app)


@pytest.fixture
def make_user(db):
    counter = {"n": 0}

    def _make(
        email=None,
        password="Password1",
        role=RoleEnum.USER,
        provider=ProviderEnum.LOCAL,
        name="Test User",
    ):
        counter["n"] += 1
        hashed = (
            bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            if password is not None
            else None
        )
        user = User(
            name=name,
            email=email or f"user{counter['n']}@example.com",
            password=hashed,
            role=role,
            provider=provider,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    return _make


@pytest.fixture
def make_alarm(db):
    def _make(user, **overrides):
        fields = dict(
            user_id=user.id,
            title="Wake up",
            alarm_time="07:00",
            alarm_type=AlarmTypeEnum.DAILY,
            repeat_days=None,
            is_active=True,
            difficulty_level=DifficultyEnum.EASY,
            sound="default",
            vibration=True,
        )
        fields.update(overrides)
        alarm = Alarm(**fields)
        db.add(alarm)
        db.commit()
        db.refresh(alarm)
        return alarm

    return _make


@pytest.fixture
def make_event(db):
    def _make(alarm, event_type, **overrides):
        event = AlarmEvent(alarm_id=alarm.id, event_type=event_type, **overrides)
        db.add(event)
        db.commit()
        db.refresh(event)
        return event

    return _make


@pytest.fixture
def auth_headers():
    def _headers(user):
        return {"Authorization": f"Bearer {create_access_token(user)}"}

    return _headers
