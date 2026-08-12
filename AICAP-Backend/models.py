"""
SQLAlchemy ORM Models — AICAP-Backend
=====================================
Source of truth for the `users`, `alarms` and `challenge_attempts` tables, matching:
  - Module 1 Guide (Auth & RBAC)
  - Module 3 Guide (Alarm Scheduling System)
  - Module 4 Guide (Cognitive Challenge System)
"""

from datetime import datetime
import enum

from sqlalchemy import (
    Column,
    Index,
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


class ChallengeTypeEnum(str, enum.Enum):
    MATH = "MATH"
    LOGIC_PUZZLE = "LOGIC_PUZZLE"
    MEMORY = "MEMORY"
    WORD_GAME = "WORD_GAME"
    PATTERN_RECOGNITION = "PATTERN_RECOGNITION"
    RIDDLE = "RIDDLE"
    QUICK_QUIZ = "QUICK_QUIZ"


class ChallengeStatusEnum(str, enum.Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


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

    # Module 4: adaptive per-user challenge difficulty. An alarm whose
    # difficulty_level is left at the EASY default follows this level;
    # explicitly choosing MEDIUM/HARD on an alarm overrides it.
    current_difficulty = Column(
        SAEnum(DifficultyEnum, name="user_challenge_difficulty", native_enum=False, length=16),
        default=DifficultyEnum.EASY,
        nullable=False,
    )

    alarms = relationship(
        "Alarm",
        back_populates="owner",
        cascade="all, delete-orphan",
    )

    challenge_attempts = relationship(
        "ChallengeAttempt",
        back_populates="user",
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
    events = relationship(
        "AlarmEvent",
        back_populates="alarm",
        cascade="all, delete-orphan",
    )
    challenge_attempts = relationship(
        "ChallengeAttempt",
        back_populates="alarm",
        cascade="all, delete-orphan",
    )


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

    alarm = relationship("Alarm", back_populates="events")


# ==========================================
# Cognitive Challenge Attempts (Module 4)
# ==========================================

class ChallengeAttempt(Base):
    __tablename__ = "challenge_attempts"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alarm_id = Column(
        Integer,
        ForeignKey("alarms.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    challenge_type = Column(
        SAEnum(ChallengeTypeEnum, name="challenge_type", native_enum=False, length=32),
        nullable=False,
    )
    difficulty = Column(
        SAEnum(DifficultyEnum, name="challenge_difficulty", native_enum=False, length=16),
        nullable=False,
    )

    # What the user actually saw, so /submit validates against the exact
    # problem instead of regenerating a differently randomized one.
    prompt_snapshot = Column(String, nullable=False)
    options_json = Column(String, nullable=True)   # JSON list for MCQ-style prompts
    metadata_json = Column(String, nullable=True)  # JSON dict, e.g. MEMORY sequence
    answer_format = Column(String, nullable=False)  # text | number | mcq | sequence
    correct_answer = Column(String, nullable=False)  # server-only, never serialized

    status = Column(
        SAEnum(ChallengeStatusEnum, name="challenge_status", native_enum=False, length=16),
        default=ChallengeStatusEnum.IN_PROGRESS,
        nullable=False,
    )
    is_correct = Column(Boolean, nullable=True)

    attempts_used = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, nullable=False)

    time_taken_seconds = Column(Integer, nullable=True)
    time_limit_seconds = Column(Integer, nullable=False)

    score = Column(Integer, default=0, nullable=False)

    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="challenge_attempts")
    alarm = relationship("Alarm", back_populates="challenge_attempts")

    # Selection logic queries "recent attempts for this user", optionally
    # narrowed to one challenge type, on every alarm trigger.
    __table_args__ = (
        Index("ix_challenge_attempts_user_started", "user_id", "started_at"),
        Index("ix_challenge_attempts_user_type", "user_id", "challenge_type"),
    )