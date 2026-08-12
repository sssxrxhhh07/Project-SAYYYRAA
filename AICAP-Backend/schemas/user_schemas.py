"""
Pydantic Schemas — Auth & Profile
==================================
Validated request/response payloads for Module 1 (Auth & RBAC).
"""

import re
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from models import RoleEnum, ProviderEnum

# Roles a user is allowed to self-assign at registration. ADMIN accounts
# must be provisioned separately — never accepted straight from public registration.
SELF_REGISTERABLE_ROLES = {RoleEnum.USER, RoleEnum.WELLNESS_COACH}


class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    role: RoleEnum = RoleEnum.USER

    @field_validator("role")
    @classmethod
    def restrict_self_registerable_roles(cls, value: RoleEnum) -> RoleEnum:
        if value not in SELF_REGISTERABLE_ROLES:
            raise ValueError(
                "role must be one of: "
                + ", ".join(r.value for r in SELF_REGISTERABLE_ROLES)
            )
        return value

    @field_validator("password")
    @classmethod
    def enforce_password_strength(cls, value: str) -> str:
        if not re.search(r"[A-Z]", value):
            raise ValueError("password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", value):
            raise ValueError("password must contain at least one lowercase letter")
        if not re.search(r"\d", value):
            raise ValueError("password must contain at least one digit")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class UserProfile(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: RoleEnum
    provider: ProviderEnum
    profile_picture: Optional[str] = None
    phone: Optional[str] = None
    bio: Optional[str] = None

    class Config:
        from_attributes = True


class UpdateProfileRequest(BaseModel):
    # Deliberately excludes `role` and `email` — profile updates must never
    # let a client escalate privilege or change their login identity.
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
    bio: Optional[str] = Field(None, max_length=500)
    profile_picture: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: RoleEnum
    name: str
    email: EmailStr
