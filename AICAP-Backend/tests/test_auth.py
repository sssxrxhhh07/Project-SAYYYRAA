"""Unit tests for JWT issuance/verification and the RBAC dependencies."""

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt

import auth
from models import RoleEnum, User


def _credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


# ==========================================
# create_access_token
# ==========================================

def test_create_access_token_encodes_identity_and_role(make_user):
    user = make_user(email="claims@example.com", role=RoleEnum.WELLNESS_COACH)

    payload = jwt.decode(
        auth.create_access_token(user), auth.SECRET_KEY, algorithms=[auth.ALGORITHM]
    )

    assert payload["id"] == user.id
    assert payload["sub"] == "claims@example.com"
    assert payload["role"] == "WELLNESS_COACH"
    assert payload["exp"] > datetime.utcnow().timestamp()


def test_create_access_token_accepts_plain_string_role():
    token = auth.create_access_token(User(id=7, email="s@example.com", role="ADMIN"))

    payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
    assert payload["role"] == "ADMIN"


# ==========================================
# verify_token
# ==========================================

def test_verify_token_returns_payload_for_valid_token(make_user):
    user = make_user()

    payload = auth.verify_token(_credentials(auth.create_access_token(user)))

    assert payload["id"] == user.id


def test_verify_token_rejects_malformed_token():
    with pytest.raises(HTTPException) as exc:
        auth.verify_token(_credentials("not.a.jwt"))

    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid or Expired Token"


def test_verify_token_rejects_expired_token(make_user):
    expired = jwt.encode(
        {
            "id": 1,
            "sub": "expired@example.com",
            "role": "USER",
            "exp": datetime.utcnow() - timedelta(minutes=1),
        },
        auth.SECRET_KEY,
        algorithm=auth.ALGORITHM,
    )

    with pytest.raises(HTTPException) as exc:
        auth.verify_token(_credentials(expired))

    assert exc.value.status_code == 401


def test_verify_token_rejects_token_signed_with_other_key():
    foreign = jwt.encode(
        {"id": 1, "role": "ADMIN", "exp": datetime.utcnow() + timedelta(minutes=5)},
        "a-different-secret",
        algorithm=auth.ALGORITHM,
    )

    with pytest.raises(HTTPException) as exc:
        auth.verify_token(_credentials(foreign))

    assert exc.value.status_code == 401


# ==========================================
# get_current_user
# ==========================================

def test_get_current_user_returns_live_row(db, make_user):
    user = make_user(email="live@example.com")

    resolved = auth.get_current_user(payload={"id": user.id}, db=db)

    assert resolved.id == user.id
    assert resolved.email == "live@example.com"


def test_get_current_user_rejects_deleted_user(db, make_user):
    user = make_user()
    db.delete(user)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        auth.get_current_user(payload={"id": user.id}, db=db)

    assert exc.value.status_code == 401
    assert exc.value.detail == "User no longer exists"


def test_get_current_user_rejects_payload_without_id(db):
    with pytest.raises(HTTPException) as exc:
        auth.get_current_user(payload={}, db=db)

    assert exc.value.status_code == 401


# ==========================================
# require_role
# ==========================================

def test_require_role_allows_matching_role():
    checker = auth.require_role("ADMIN")

    payload = {"role": "ADMIN", "id": 1}
    assert checker(user_payload=payload) is payload


def test_require_role_allows_any_of_several_roles():
    checker = auth.require_role("ADMIN", "WELLNESS_COACH")

    assert checker(user_payload={"role": "WELLNESS_COACH"})["role"] == "WELLNESS_COACH"


def test_require_role_accepts_role_enum_members():
    checker = auth.require_role(RoleEnum.ADMIN)

    assert checker(user_payload={"role": "ADMIN"})["role"] == "ADMIN"


@pytest.mark.parametrize("payload", [{"role": "USER"}, {"role": None}, {}])
def test_require_role_denies_other_roles(payload):
    checker = auth.require_role("ADMIN")

    with pytest.raises(HTTPException) as exc:
        checker(user_payload=payload)

    assert exc.value.status_code == 403
    assert exc.value.detail == "Access Denied"


def test_google_oauth_client_is_registered():
    assert auth.oauth.google is not None
