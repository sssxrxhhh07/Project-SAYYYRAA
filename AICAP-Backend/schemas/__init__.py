"""
Schemas Package Init
====================
Exports all Pydantic schemas for auth, profile, alarms, and challenges.
"""

from schemas.user_schemas import (
    RegisterRequest,
    LoginRequest,
    UserProfile,
    UpdateProfileRequest,
    TokenResponse,
    SELF_REGISTERABLE_ROLES,
)

from schemas.alarm_schemas import (
    AlarmBase,
    AlarmCreate,
    AlarmUpdate,
    AlarmOut,
    SnoozeRequest,
    DismissRequest,
)

from schemas.challenge_schemas import (
    StartChallengeRequest,
    SubmitAnswerRequest,
    ChallengeOut,
    SubmitResultOut,
    AttemptOut,
    TypeBreakdown,
    ChallengeStatsOut,
)

__all__ = [
    "RegisterRequest",
    "LoginRequest",
    "UserProfile",
    "UpdateProfileRequest",
    "TokenResponse",
    "SELF_REGISTERABLE_ROLES",
    "AlarmBase",
    "AlarmCreate",
    "AlarmUpdate",
    "AlarmOut",
    "SnoozeRequest",
    "DismissRequest",
    "StartChallengeRequest",
    "SubmitAnswerRequest",
    "ChallengeOut",
    "SubmitResultOut",
    "AttemptOut",
    "TypeBreakdown",
    "ChallengeStatsOut",
]
