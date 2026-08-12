"""Unit tests for the registration / login / logout endpoints."""

import bcrypt
from jose import jwt

import auth
from models import ProviderEnum, RoleEnum, User


def test_register_creates_local_user_with_hashed_password(client, db):
    response = client.post(
        "/api/auth/register",
        json={"name": "Ann", "email": "ann@example.com", "password": "Password1"},
    )

    assert response.status_code == 201
    user = db.query(User).filter(User.email == "ann@example.com").one()
    assert response.json() == {"message": "Registration Successful", "user_id": user.id}
    assert user.password != "Password1"
    assert bcrypt.checkpw(b"Password1", user.password.encode())
    assert user.role is RoleEnum.USER
    assert user.provider is ProviderEnum.LOCAL


def test_register_honours_wellness_coach_role(client, db):
    client.post(
        "/api/auth/register",
        json={
            "name": "Coach",
            "email": "coach@example.com",
            "password": "Password1",
            "role": "WELLNESS_COACH",
        },
    )

    user = db.query(User).filter(User.email == "coach@example.com").one()
    assert user.role is RoleEnum.WELLNESS_COACH


def test_register_rejects_admin_role(client, db):
    response = client.post(
        "/api/auth/register",
        json={
            "name": "Sneaky",
            "email": "sneaky@example.com",
            "password": "Password1",
            "role": "ADMIN",
        },
    )

    assert response.status_code == 422
    assert db.query(User).filter(User.email == "sneaky@example.com").count() == 0


def test_register_rejects_duplicate_email(client, make_user):
    make_user(email="taken@example.com")

    response = client.post(
        "/api/auth/register",
        json={"name": "Copy", "email": "taken@example.com", "password": "Password1"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Email already exists"


def test_register_rejects_weak_password(client):
    response = client.post(
        "/api/auth/register",
        json={"name": "Ann", "email": "weak@example.com", "password": "password"},
    )

    assert response.status_code == 422


def test_login_returns_jwt_with_user_claims(client, make_user):
    user = make_user(email="login@example.com", password="Password1", name="Ann")

    response = client.post(
        "/api/auth/login", json={"email": "login@example.com", "password": "Password1"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "USER"
    assert body["name"] == "Ann"
    payload = jwt.decode(
        body["access_token"], auth.SECRET_KEY, algorithms=[auth.ALGORITHM]
    )
    assert payload["id"] == user.id
    assert payload["sub"] == "login@example.com"


def test_login_rejects_wrong_password(client, make_user):
    make_user(email="login@example.com", password="Password1")

    response = client.post(
        "/api/auth/login", json={"email": "login@example.com", "password": "Wrong1234"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid Email or Password"


def test_login_rejects_unknown_email(client):
    response = client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "Password1"}
    )

    assert response.status_code == 401


def test_login_rejects_oauth_only_account(client, make_user):
    make_user(email="google@example.com", password=None, provider=ProviderEnum.GOOGLE)

    response = client.post(
        "/api/auth/login", json={"email": "google@example.com", "password": "Password1"}
    )

    assert response.status_code == 401


def test_login_validates_payload(client):
    assert (
        client.post(
            "/api/auth/login", json={"email": "not-an-email", "password": "x"}
        ).status_code
        == 422
    )


def test_logout_is_stateless_and_always_succeeds(client):
    response = client.post("/api/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"message": "Logout Successful"}
