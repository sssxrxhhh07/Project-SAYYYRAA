"""
Schemas Package Init
====================
Exports all Pydantic schemas for auth, profile, and alarms.
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
]
