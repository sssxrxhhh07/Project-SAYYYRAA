from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from models import Base
from database import engine
from scheduler import start_scheduler, stop_scheduler

from routers import (
    frontend_routes,
    auth_routes,
    profile_routes,
    admin_routes,
    alarm_routes,
)

# ==========================================
# Create Database Tables
# ==========================================

# Create all tables including the new AlarmEvent table
Base.metadata.create_all(bind=engine)


# ==========================================
# FastAPI Lifespan (Startup / Shutdown)
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start APScheduler
    start_scheduler()
    yield
    # Shutdown: Stop APScheduler
    stop_scheduler()


# ==========================================
# FastAPI Application
# ==========================================

app = FastAPI(
    title="AICAP Backend",
    description="Module 1 (Auth & RBAC) and Module 3 (Alarm Scheduling System)",
    version="1.0.0",
    lifespan=lifespan,
)

# ==========================================
# CORS
# ==========================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# Static Files
# ==========================================

if os.path.exists("static"):
    app.mount(
        "/static",
        StaticFiles(directory="static"),
        name="static"
    )

# ==========================================
# Include Routers
# ==========================================

app.include_router(frontend_routes.router)
app.include_router(auth_routes.router)
app.include_router(profile_routes.router)
app.include_router(admin_routes.router)
app.include_router(alarm_routes.router)