"""Unit tests for the Google OAuth login/callback endpoints.

The Authlib client is replaced with a stub so the flow can be exercised without
contacting Google.
"""

import pytest
from starlette.responses import RedirectResponse

from routers import auth_routes
from models import ProviderEnum, User


class _StubGoogleClient:
    def __init__(self, token=None):
        self._token = token
        self.redirect_uris = []

    async def authorize_redirect(self, request, redirect_uri):
        self.redirect_uris.append(redirect_uri)
        return RedirectResponse(url="https://accounts.google.com/o/oauth2/auth")

    async def authorize_access_token(self, request):
        return self._token


class _StubOAuth:
    def __init__(self, token=None):
        self.google = _StubGoogleClient(token)


@pytest.fixture
def stub_oauth(monkeypatch):
    def _install(token=None):
        stub = _StubOAuth(token)
        monkeypatch.setattr(auth_routes, "oauth", stub)
        return stub

    return _install


def test_google_login_redirects_to_google(client, stub_oauth):
    stub = stub_oauth()

    response = client.get("/api/auth/google", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].startswith("https://accounts.google.com")
    assert str(stub.google.redirect_uris[0]).endswith("/api/auth/google/callback")


def test_google_callback_creates_new_google_user(client, db, stub_oauth):
    stub_oauth(
        {
            "userinfo": {
                "email": "new@gmail.com",
                "name": "New Person",
                "picture": "http://img/pic.png",
            }
        }
    )

    response = client.get("/api/auth/google/callback")

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "new@gmail.com"
    assert body["name"] == "New Person"
    assert body["role"] == "USER"
    user = db.query(User).filter(User.email == "new@gmail.com").one()
    assert user.provider is ProviderEnum.GOOGLE
    assert user.password is None
    assert user.profile_picture == "http://img/pic.png"


def test_google_callback_derives_name_from_email_when_absent(client, db, stub_oauth):
    stub_oauth({"userinfo": {"email": "noname@gmail.com"}})

    body = client.get("/api/auth/google/callback").json()

    assert body["name"] == "noname"


def test_google_callback_reuses_existing_account(client, db, make_user, stub_oauth):
    existing = make_user(email="existing@gmail.com", name="Existing")
    stub_oauth({"userinfo": {"email": "existing@gmail.com", "name": "Ignored"}})

    body = client.get("/api/auth/google/callback").json()

    assert body["name"] == "Existing"
    assert db.query(User).filter(User.email == "existing@gmail.com").count() == 1
    assert existing.provider is ProviderEnum.LOCAL


def test_google_callback_rejects_token_without_userinfo(client, stub_oauth):
    stub_oauth({})

    response = client.get("/api/auth/google/callback")

    assert response.status_code == 400
    assert response.json()["detail"] == "Google Login Failed"


def test_google_callback_rejects_userinfo_without_email(client, stub_oauth):
    stub_oauth({"userinfo": {"name": "No Email"}})

    response = client.get("/api/auth/google/callback")

    assert response.status_code == 400
    assert response.json()["detail"] == "Google user email not provided"
