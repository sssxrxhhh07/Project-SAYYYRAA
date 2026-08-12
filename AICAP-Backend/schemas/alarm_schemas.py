"""
Pydantic Schemas — Alarms
=========================
Validated request/response payloads for Module 3 (Alarm Scheduling System).
"""

import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from models import AlarmTypeEnum, DifficultyEnum

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")  # "HH:MM", 24-hour
_VALID_DAYS = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}


def _validate_time(value: str) -> str:
    if not _TIME_RE.match(value):
        raise ValueError('alarm_time must be in 24-hour "HH:MM" format')
    return value


def _validate_days(value: Optional[List[str]]) -> Optional[List[str]]:
    if value is None:
        return value
    normalized = [d.strip().upper() for d in value]
    invalid = set(normalized) - _VALID_DAYS
    if invalid:
        raise ValueError(f"invalid repeat_days values: {sorted(invalid)}")
    return normalized


class AlarmBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    alarm_time: str
    alarm_type: AlarmTypeEnum = AlarmTypeEnum.DAILY
    repeat_days: Optional[List[str]] = None
    difficulty_level: DifficultyEnum = DifficultyEnum.EASY
    sound: str = Field(default="default", max_length=100)
    vibration: bool = True

    _check_time = field_validator("alarm_time")(_validate_time)
    _check_days = field_validator("repeat_days")(_validate_days)

    @field_validator("repeat_days")
    @classmethod
    def require_days_for_weekday_weekend(cls, value, info):
        alarm_type = info.data.get("alarm_type")
        if alarm_type in (AlarmTypeEnum.WEEKDAY, AlarmTypeEnum.WEEKEND) and not value:
            raise ValueError(
                "repeat_days is required when alarm_type is WEEKDAY or WEEKEND"
            )
        return value


class AlarmCreate(AlarmBase):
    is_active: bool = True


class AlarmUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=100)
    alarm_time: Optional[str] = None
    alarm_type: Optional[AlarmTypeEnum] = None
    repeat_days: Optional[List[str]] = None
    difficulty_level: Optional[DifficultyEnum] = None
    sound: Optional[str] = Field(None, max_length=100)
    vibration: Optional[bool] = None
    is_active: Optional[bool] = None

    _check_time = field_validator("alarm_time")(
        lambda v: _validate_time(v) if v is not None else v
    )
    _check_days = field_validator("repeat_days")(_validate_days)


class SnoozeRequest(BaseModel):
    snooze_minutes: Optional[int] = Field(default=None, ge=1, le=720)


class DismissRequest(BaseModel):
    seconds_to_dismiss: Optional[int] = Field(default=None, ge=0, le=86_400)


class AlarmOut(BaseModel):
    id: int
    user_id: int
    title: str
    alarm_time: str
    alarm_type: AlarmTypeEnum
    repeat_days: Optional[List[str]] = None
    is_active: bool
    difficulty_level: DifficultyEnum
    sound: str
    vibration: bool
    created_at: datetime
    updated_at: datetime
    # SMART_ADAPTIVE tracking fields
    snooze_count: int = 0
    last_snooze_time: Optional[datetime] = None
    avg_dismiss_time: int = 0
    adaptive_offset: int = 0
    trigger_count: int = 0

    class Config:
        from_attributes = True

    @field_validator("repeat_days", mode="before")
    @classmethod
    def split_repeat_days(cls, value):
        if isinstance(value, str):
            return [d for d in value.split(",") if d]
        return value
