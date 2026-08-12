"""Unit tests for the health probe, JWT sanity check and RBAC dashboards."""

import pytest

from models import RoleEnum


def test_health_is_public(client):
    body = client.get("/api/health").json()

    assert body["status"] == "running"
    assert body["application"] == "AICAP Backend"
    assert body["timestamp"]


def test_protected_echoes_jwt_claims(client, make_user, auth_headers):
    user = make_user(email="claims@example.com", role=RoleEnum.ADMIN)

    body = client.get("/api/protected", headers=auth_headers(user)).json()

    assert body["user_id"] == user.id
    assert body["email"] == "claims@example.com"
    assert body["role"] == "ADMIN"


def test_protected_requires_valid_token(client):
    assert client.get("/api/protected").status_code == 401
    assert (
        client.get(
            "/api/protected", headers={"Authorization": "Bearer garbage"}
        ).status_code
        == 401
    )


# ==========================================
# Admin dashboard
# ==========================================

def test_admin_dashboard_aggregates_platform_stats(
    client, make_user, make_alarm, auth_headers
):
    admin = make_user(role=RoleEnum.ADMIN, name="Root")
    regular = make_user(role=RoleEnum.USER)
    make_user(role=RoleEnum.WELLNESS_COACH)
    make_alarm(regular)
    make_alarm(regular, is_active=False)

    body = client.get("/api/admin/dashboard", headers=auth_headers(admin)).json()

    stats = body["stats"]
    assert stats["total_users"] == 3
    assert stats["total_alarms"] == 2
    assert stats["active_alarms"] == 1
    assert stats["inactive_alarms"] == 1
    assert stats["users_by_role"] == {"USER": 1, "WELLNESS_COACH": 1, "ADMIN": 1}
    assert len(body["recent_users"]) == 3
    assert set(body["recent_users"][0]) == {"id", "name", "email", "role", "created_at"}


def test_admin_dashboard_caps_recent_users_at_five(client, make_user, auth_headers):
    admin = make_user(role=RoleEnum.ADMIN)
    for _ in range(6):
        make_user()

    body = client.get("/api/admin/dashboard", headers=auth_headers(admin)).json()

    assert len(body["recent_users"]) == 5


@pytest.mark.parametrize(
    "path", ["/api/admin/dashboard", "/api/admin/users", "/api/admin/alarms"]
)
@pytest.mark.parametrize("role", [RoleEnum.USER, RoleEnum.WELLNESS_COACH])
def test_admin_endpoints_forbid_non_admin_roles(
    client, make_user, auth_headers, path, role
):
    response = client.get(path, headers=auth_headers(make_user(role=role)))

    assert response.status_code == 403
    assert response.json()["detail"] == "Access Denied"


def test_admin_list_users_includes_alarm_counts(
    client, make_user, make_alarm, auth_headers
):
    admin = make_user(role=RoleEnum.ADMIN, email="admin@example.com")
    regular = make_user(email="regular@example.com")
    make_alarm(regular)
    make_alarm(regular)

    body = client.get("/api/admin/users", headers=auth_headers(admin)).json()

    by_email = {u["email"]: u for u in body}
    assert by_email["regular@example.com"]["alarm_count"] == 2
    assert by_email["admin@example.com"]["alarm_count"] == 0
    assert by_email["admin@example.com"]["role"] == "ADMIN"
    assert by_email["admin@example.com"]["provider"] == "LOCAL"


def test_admin_list_alarms_spans_all_users(client, make_user, make_alarm, auth_headers):
    admin = make_user(role=RoleEnum.ADMIN)
    owner = make_user(name="Owner")
    make_alarm(owner, title="Theirs", alarm_time="06:00")

    body = client.get("/api/admin/alarms", headers=auth_headers(admin)).json()

    assert len(body) == 1
    assert body[0]["title"] == "Theirs"
    assert body[0]["user_name"] == "Owner"
    assert body[0]["alarm_type"] == "DAILY"
    assert body[0]["difficulty_level"] == "EASY"
    assert body[0]["is_active"] is True


# ==========================================
# User & wellness dashboards
# ==========================================

def test_user_dashboard_reports_personal_stats(
    client, make_user, make_alarm, auth_headers
):
    user = make_user(name="Ann")
    make_alarm(user)
    make_alarm(user, is_active=False)
    make_alarm(make_user())  # another user's alarm must not be counted

    body = client.get("/api/user/dashboard", headers=auth_headers(user)).json()

    assert body["message"] == "Welcome, Ann"
    assert body["user"]["role"] == "USER"
    assert body["stats"] == {
        "total_alarms": 2,
        "active_alarms": 1,
        "inactive_alarms": 1,
    }


@pytest.mark.parametrize(
    "role", [RoleEnum.USER, RoleEnum.ADMIN, RoleEnum.WELLNESS_COACH]
)
def test_user_dashboard_open_to_every_role(client, make_user, auth_headers, role):
    response = client.get(
        "/api/user/dashboard", headers=auth_headers(make_user(role=role))
    )

    assert response.status_code == 200


def test_wellness_dashboard_aggregates_user_roster(
    client, make_user, make_alarm, auth_headers
):
    coach = make_user(role=RoleEnum.WELLNESS_COACH, name="Cid")
    client_user = make_user(role=RoleEnum.USER)
    make_alarm(client_user)
    make_alarm(client_user, is_active=False)
    make_alarm(coach)  # coach's own alarm is outside the USER roster

    body = client.get("/api/wellness/dashboard", headers=auth_headers(coach)).json()

    assert body["message"] == "Welcome, Coach Cid"
    assert body["coach"]["id"] == coach.id
    assert body["roster_stats"] == {
        "total_users": 1,
        "total_alarms": 2,
        "active_alarms": 1,
    }


def test_wellness_dashboard_forbidden_for_plain_user(client, make_user, auth_headers):
    response = client.get(
        "/api/wellness/dashboard", headers=auth_headers(make_user(role=RoleEnum.USER))
    )

    assert response.status_code == 403
