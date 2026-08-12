"""Unit tests for the application wiring in main.py."""

from fastapi.testclient import TestClient

import scheduler as scheduler_module
from main import app


def test_expected_routes_are_registered():
    paths = set(app.openapi()["paths"])

    assert {"/", "/login", "/register", "/dashboard"} <= paths
    assert {"/api/auth/register", "/api/auth/login", "/api/auth/logout"} <= paths
    assert {"/api/me", "/api/profile"} <= paths
    assert {"/api/health", "/api/admin/dashboard", "/api/user/dashboard"} <= paths
    assert {"/alarms", "/alarms/{alarm_id}", "/alarms/today"} <= paths


def test_cors_middleware_allows_cross_origin_requests(client):
    response = client.get("/api/health", headers={"Origin": "http://localhost:5500"})

    assert (
        response.headers["access-control-allow-origin"] == "http://localhost:5500"
    )
    assert response.headers["access-control-allow-credentials"] == "true"


def test_lifespan_starts_and_stops_the_scheduler(make_user, make_alarm):
    alarm = make_alarm(make_user())

    with TestClient(app):
        assert scheduler_module.scheduler.running is True
        assert scheduler_module.scheduler.get_job(f"alarm_{alarm.id}") is not None

    assert scheduler_module.scheduler.running is False
