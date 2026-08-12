"""Unit tests for the ORM models, enums and the DB session provider."""

import pytest
from sqlalchemy.exc import IntegrityError

import database
from models import (
    Alarm,
    AlarmEvent,
    AlarmTypeEnum,
    DifficultyEnum,
    ProviderEnum,
    RoleEnum,
    User,
)


# ==========================================
# Enums
# ==========================================

def test_enums_are_string_valued():
    assert RoleEnum.ADMIN == "ADMIN"
    assert ProviderEnum.GOOGLE == "GOOGLE"
    assert AlarmTypeEnum.SMART_ADAPTIVE == "SMART_ADAPTIVE"
    assert DifficultyEnum.MEDIUM == "MEDIUM"


def test_enum_membership():
    assert {r.value for r in RoleEnum} == {"USER", "WELLNESS_COACH", "ADMIN"}
    assert {t.value for t in AlarmTypeEnum} == {
        "DAILY",
        "WEEKDAY",
        "WEEKEND",
        "ONE_TIME",
        "SMART_ADAPTIVE",
    }


# ==========================================
# User model
# ==========================================

def test_user_defaults(db):
    user = User(name="Ann", email="defaults@example.com", password="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    assert user.role is RoleEnum.USER
    assert user.provider is ProviderEnum.LOCAL
    assert user.created_at is not None
    assert user.updated_at is not None
    assert user.alarms == []


def test_user_email_must_be_unique(db):
    db.add(User(name="A", email="dup@example.com", password="x"))
    db.commit()

    db.add(User(name="B", email="dup@example.com", password="y"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_user_name_is_required(db):
    db.add(User(email="noname@example.com", password="x"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ==========================================
# Alarm model
# ==========================================

def test_alarm_defaults_and_relationship(db, make_user):
    user = make_user()
    alarm = Alarm(user_id=user.id, title="Wake", alarm_time="07:00")
    db.add(alarm)
    db.commit()
    db.refresh(alarm)
    db.refresh(user)

    assert alarm.alarm_type is AlarmTypeEnum.DAILY
    assert alarm.difficulty_level is DifficultyEnum.EASY
    assert alarm.is_active is True
    assert alarm.sound == "default"
    assert alarm.vibration is True
    assert (alarm.snooze_count, alarm.trigger_count) == (0, 0)
    assert (alarm.avg_dismiss_time, alarm.adaptive_offset) == (0, 0)
    assert alarm.last_snooze_time is None
    assert alarm.owner.id == user.id
    assert user.alarms == [alarm]


def test_alarm_requires_a_user(db):
    db.add(Alarm(title="Orphan", alarm_time="07:00"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_deleting_user_cascades_to_alarms(db, make_user, make_alarm):
    user = make_user()
    make_alarm(user)
    assert db.query(Alarm).count() == 1

    db.delete(user)
    db.commit()

    assert db.query(Alarm).count() == 0


# ==========================================
# AlarmEvent model
# ==========================================

def test_alarm_event_defaults_and_backref(db, make_user, make_alarm):
    alarm = make_alarm(make_user())
    event = AlarmEvent(alarm_id=alarm.id, event_type="snooze", snooze_duration=5)
    db.add(event)
    db.commit()
    db.refresh(event)
    db.refresh(alarm)

    assert event.event_time is not None
    assert event.seconds_to_dismiss is None
    assert event.alarm.id == alarm.id
    assert alarm.events == [event]


# ==========================================
# database.get_db
# ==========================================

def test_get_db_yields_a_session_and_closes_it():
    generator = database.get_db()
    session = next(generator)

    assert session.is_active
    with pytest.raises(StopIteration):
        next(generator)

    # A closed session has released its connection back to the pool.
    assert session.get_transaction() is None


def test_get_db_closes_session_even_when_consumer_raises():
    generator = database.get_db()
    session = next(generator)

    generator.close()

    assert session.get_transaction() is None


def test_engine_uses_sqlite_test_database():
    assert database.DATABASE_URL.startswith("sqlite")
    assert database.engine.url.database.endswith("aicap_test.db")
