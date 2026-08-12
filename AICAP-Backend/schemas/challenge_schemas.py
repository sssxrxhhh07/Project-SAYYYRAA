"""
Pydantic Schemas — Cognitive Challenges
=======================================
Validated request/response payloads for Module 4 (Cognitive Challenge System).

`ChallengeOut` is the only shape sent to the client while an attempt is in
progress; it deliberately has no `correct_answer` field.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from models import ChallengeStatusEnum, ChallengeTypeEnum, DifficultyEnum


class StartChallengeRequest(BaseModel):
    alarm_id: Optional[int] = None
    seed: Optional[int] = None


class SubmitAnswerRequest(BaseModel):
    answer: str = Field(..., max_length=500)


class ChallengeOut(BaseModel):
    """An in-progress challenge as the client sees it."""

    attempt_id: int
    alarm_id: Optional[int] = None
    challenge_type: ChallengeTypeEnum
    difficulty: DifficultyEnum
    prompt: str
    options: Optional[List[str]] = None
    answer_format: str
    metadata: dict = Field(default_factory=dict)
    time_limit_seconds: int
    seconds_remaining: int
    max_attempts: int
    attempts_used: int
    status: ChallengeStatusEnum
    started_at: datetime


class SubmitResultOut(BaseModel):
    attempt_id: int
    status: ChallengeStatusEnum
    is_correct: bool
    attempts_used: int
    attempts_remaining: int
    time_taken_seconds: Optional[int] = None
    score: int
    difficulty: DifficultyEnum
    next_difficulty: DifficultyEnum
    # True once the user may silence the alarm without solving a challenge.
    fallback_available: bool
    message: str


class AttemptOut(BaseModel):
    id: int
    alarm_id: Optional[int] = None
    challenge_type: ChallengeTypeEnum
    difficulty: DifficultyEnum
    prompt_snapshot: str
    status: ChallengeStatusEnum
    is_correct: Optional[bool] = None
    attempts_used: int
    max_attempts: int
    time_taken_seconds: Optional[int] = None
    time_limit_seconds: int
    score: int
    started_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TypeBreakdown(BaseModel):
    challenge_type: ChallengeTypeEnum
    attempts: int
    accuracy: Optional[float] = None
    average_time_seconds: Optional[float] = None


class ChallengeStatsOut(BaseModel):
    total_attempts: int
    completed: int
    failed: int
    accuracy: Optional[float] = None
    average_time_seconds: Optional[float] = None
    total_score: int
    current_difficulty: DifficultyEnum
    current_streak: int
    per_type: List[TypeBreakdown]
