"""
Frontend Routes
===============
Serves the single-page application (SPA) index.html for all browser
navigation paths. Hash-based routing (#/user, #/admin, etc.) is handled
entirely client-side by js/main.js, so every server route just returns
the same index.html shell.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["Frontend"])

templates = Jinja2Templates(directory="templates")


def _spa(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    return _spa(request)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return _spa(request)


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return _spa(request)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    return _spa(request)


@router.get("/dashboard/{path:path}", response_class=HTMLResponse)
def dashboard_deep(request: Request, path: str):
    return _spa(request)