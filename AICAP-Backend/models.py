"""
SQLAlchemy ORM Models — AICAP-Backend
=====================================
Source of truth for the `users` and `alarms` tables, matching:
  - Module 1 Guide (Auth & RBAC)
  - Module 3 Guide (Alarm Scheduling System)
"""

from datetime import datetime
import enum

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Enum as SAEnum,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ==========================================
# Enums
# ==========================================

class RoleEnum(str, enum.Enum):
    USER = "USER"
    WELLNESS_COACH = "WELLNESS_COACH"
    ADMIN = "ADMIN"


class ProviderEnum(str, enum.Enum):
    LOCAL = "LOCAL"
    GOOGLE = "GOOGLE"


class AlarmTypeEnum(str, enum.Enum):
    DAILY = "DAILY"
    WEEKDAY = "WEEKDAY"
    WEEKEND = "WEEKEND"
    ONE_TIME = "ONE_TIME"
    SMART_ADAPTIVE = "SMART_ADAPTIVE"


class DifficultyEnum(str, enum.Enum):
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"


# ==========================================
# Users
# ==========================================

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    password = Column(String, nullable=True)

    role = Column(
        SAEnum(RoleEnum, name="user_role", native_enum=False, length=32),
        default=RoleEnum.USER,
        nullable=False,
    )

    provider = Column(
        SAEnum(ProviderEnum, name="user_provider", native_enum=False, length=16),
        default=ProviderEnum.LOCAL,
        nullable=False,
    )

    profile_picture = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    bio = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    alarms = relationship(
        "Alarm",
        back_populates="owner",
        cascade="all, delete-orphan",
    )


# ==========================================
# Alarms
# ==========================================

class Alarm(Base):
    __tablename__ = "alarms"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title = Column(String, nullable=False)
    alarm_time = Column(String, nullable=False)  # 24-hour "HH:MM"

    alarm_type = Column(
        SAEnum(AlarmTypeEnum, name="alarm_type", native_enum=False, length=32),
        default=AlarmTypeEnum.DAILY,
        nullable=False,
    )

    repeat_days = Column(String, nullable=True)  # e.g., "MON,TUE,WED"
    is_active = Column(Boolean, default=True, nullable=False)

    difficulty_level = Column(
        SAEnum(DifficultyEnum, name="alarm_difficulty", native_enum=False, length=16),
        default=DifficultyEnum.EASY,
        nullable=False,
    )

    sound = Column(String, default="default", nullable=False)
    vibration = Column(Boolean, default=True, nullable=False)

    # SMART_ADAPTIVE tracking fields
    snooze_count = Column(Integer, default=0, nullable=False)
    last_snooze_time = Column(DateTime, nullable=True)
    avg_dismiss_time = Column(Integer, default=0, nullable=False)  # Average seconds to dismiss
    adaptive_offset = Column(Integer, default=0, nullable=False)  # Adaptive time offset in minutes
    trigger_count = Column(Integer, default=0, nullable=False)  # How many times alarm has triggered

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    owner = relationship("User", back_populates="alarms")


# ==========================================
# Alarm Events (for SMART_ADAPTIVE tracking)
# ==========================================

class AlarmEvent(Base):
    __tablename__ = "alarm_events"

    id = Column(Integer, primary_key=True, index=True)
    alarm_id = Column(
        Integer,
        ForeignKey("alarms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type = Column(String, nullable=False)  # "dismiss", "snooze", "missed"
    event_time = Column(DateTime, default=datetime.utcnow, nullable=False)
    seconds_to_dismiss = Column(Integer, nullable=True)  # Time from trigger to dismiss
    snooze_duration = Column(Integer, nullable=True)  # Snooze duration in minutes

    alarm = relationship("Alarm", backref="events")