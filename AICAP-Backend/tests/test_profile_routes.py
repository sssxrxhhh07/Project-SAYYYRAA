"""Unit tests for the profile endpoints (/api/me, /api/profile)."""

import pytest

from models import RoleEnum


@pytest.mark.parametrize("path", ["/api/me", "/api/profile"])
def test_profile_endpoints_return_current_user(client, make_user, auth_headers, path):
    user = make_user(email="me@example.com", name="Ann")

    body = client.get(path, headers=auth_headers(user)).json()

    assert body["id"] == user.id
    assert body["email"] == "me@example.com"
    assert body["name"] == "Ann"
    assert body["role"] == RoleEnum.USER.value


@pytest.mark.parametrize("path", ["/api/me", "/api/profile"])
def test_profile_endpoints_require_a_token(client, path):
    assert client.get(path).status_code == 401


def test_profile_endpoint_rejects_invalid_token(client):
    response = client.get("/api/profile", headers={"Authorization": "Bearer nope"})

    assert response.status_code == 401


def test_update_profile_persists_editable_fields(
    client, db, make_user, auth_headers
):
    user = make_user(name="Old name")

    body = client.put(
        "/api/profile",
        headers=auth_headers(user),
        json={
            "name": "New name",
            "phone": "+15550001",
            "bio": "Sleeps early",
            "profile_picture": "http://img/avatar.png",
        },
    ).json()

    assert body["name"] == "New name"
    assert body["phone"] == "+15550001"
    assert body["bio"] == "Sleeps early"
    assert body["profile_picture"] == "http://img/avatar.png"
    db.expire_all()
    assert db.get(type(user), user.id).name == "New name"


def test_update_profile_leaves_omitted_fields_untouched(client, make_user, auth_headers):
    user = make_user(name="Keep")

    body = client.put(
        "/api/profile", headers=auth_headers(user), json={"bio": "Only bio"}
    ).json()

    assert body["name"] == "Keep"
    assert body["bio"] == "Only bio"


def test_update_profile_cannot_escalate_role_or_change_email(
    client, db, make_user, auth_headers
):
    user = make_user(email="user@example.com", role=RoleEnum.USER)

    body = client.put(
        "/api/profile",
        headers=auth_headers(user),
        json={"name": "Ann", "role": "ADMIN", "email": "admin@example.com"},
    ).json()

    assert body["role"] == RoleEnum.USER.value
    assert body["email"] == "user@example.com"
    db.expire_all()
    refreshed = db.get(type(user), user.id)
    assert refreshed.role is RoleEnum.USER
    assert refreshed.email == "user@example.com"


def test_update_profile_validates_field_limits(client, make_user, auth_headers):
    response = client.put(
        "/api/profile", headers=auth_headers(make_user()), json={"name": "A"}
    )

    assert response.status_code == 422
