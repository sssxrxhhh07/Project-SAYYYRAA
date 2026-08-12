"""Unit tests for the SPA shell routes."""

import pytest


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/login",
        "/register",
        "/dashboard",
        "/dashboard/user",
        "/dashboard/admin/settings",
    ],
)
def test_spa_shell_is_served_for_every_browser_path(client, path):
    response = client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<html" in response.text.lower()


def test_all_spa_routes_return_identical_markup(client):
    assert client.get("/login").text == client.get("/dashboard").text


def test_unknown_non_dashboard_path_is_not_handled(client):
    assert client.get("/definitely-not-a-route").status_code == 404
