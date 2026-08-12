"""
Admin & Dashboard Routes
========================
Replaces the old placeholder stubs (RECRUITER/DOCTOR roles that don't exist,
empty return bodies) with production-ready endpoints that:
  - Enforce correct RBAC roles (ADMIN / WELLNESS_COACH / USER)
  - Query the live database for real metrics
  - Return structured, documented responses
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from auth import verify_token, require_role, get_current_user
from database import get_db
from models import User, Alarm, RoleEnum

router = APIRouter(prefix="/api", tags=["Dashboard & Admin"])


# ============================================================
# Health Check
# ============================================================

@router.get("/health", summary="Service health probe")
def health():
    return {
        "status": "running",
        "application": "AICAP Backend",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ============================================================
# Generic JWT-protected sanity check
# ============================================================

@router.get("/protected", summary="Verify JWT is valid")
def protected(user=Depends(verify_token)):
    return {
        "message": "JWT authentication successful",
        "user_id": user.get("id"),
        "email": user.get("sub"),
        "role": user.get("role"),
    }


# ============================================================
# ADMIN dashboard — platform-wide stats
# ============================================================

@router.get("/admin/dashboard", summary="Admin — platform overview")
def admin_dashboard(
    db: Session = Depends(get_db),
    _: dict = Depends(require_role("ADMIN")),
):
    total_users = db.query(User).count()
    total_alarms = db.query(Alarm).count()
    active_alarms = db.query(Alarm).filter(Alarm.is_active == True).count()
    inactive_alarms = total_alarms - active_alarms

    users_by_role = {}
    for role in RoleEnum:
        count = db.query(User).filter(User.role == role).count()
        users_by_role[role.value] = count

    recent_users = (
        db.query(User)
        .order_by(User.created_at.desc())
        .limit(5)
        .all()
    )

    return {
        "message": "Welcome, Admin",
        "stats": {
            "total_users": total_users,
            "total_alarms": total_alarms,
            "active_alarms": active_alarms,
            "inactive_alarms": inactive_alarms,
            "users_by_role": users_by_role,
        },
        "recent_users": [
            {
                "id": u.id,
                "name": u.name,
                "email": u.email,
                "role": u.role.value if hasattr(u.role, "value") else u.role,
                "created_at": u.created_at.isoformat(),
            }
            for u in recent_users
        ],
    }


@router.get("/admin/users", summary="Admin — list all users")
def admin_list_users(
    db: Session = Depends(get_db),
    _: dict = Depends(require_role("ADMIN")),
):
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [
        {
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "role": u.role.value if hasattr(u.role, "value") else u.role,
            "provider": u.provider.value if hasattr(u.provider, "value") else u.provider,
            "alarm_count": len(u.alarms),
            "created_at": u.created_at.isoformat(),
        }
        for u in users
    ]


@router.get("/admin/alarms", summary="Admin — list all alarms across users")
def admin_list_alarms(
    db: Session = Depends(get_db),
    _: dict = Depends(require_role("ADMIN")),
):
    alarms = db.query(Alarm).order_by(Alarm.created_at.desc()).all()
    return [
        {
            "id": a.id,
            "user_id": a.user_id,
            "user_name": a.owner.name if a.owner else "—",
            "title": a.title,
            "alarm_time": a.alarm_time,
            "alarm_type": a.alarm_type.value if hasattr(a.alarm_type, "value") else a.alarm_type,
            "is_active": a.is_active,
            "difficulty_level": a.difficulty_level.value if hasattr(a.difficulty_level, "value") else a.difficulty_level,
            "created_at": a.created_at.isoformat(),
        }
        for a in alarms
    ]


# ============================================================
# USER dashboard — personal stats
# ============================================================

@router.get("/user/dashboard", summary="User — personal dashboard stats")
def user_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: dict = Depends(require_role("USER", "ADMIN", "WELLNESS_COACH")),
):
    total_alarms = db.query(Alarm).filter(Alarm.user_id == current_user.id).count()
    active_alarms = db.query(Alarm).filter(
        Alarm.user_id == current_user.id,
        Alarm.is_active == True,
    ).count()

    return {
        "message": f"Welcome, {current_user.name}",
        "user": {
            "id": current_user.id,
            "name": current_user.name,
            "email": current_user.email,
            "role": current_user.role.value if hasattr(current_user.role, "value") else current_user.role,
        },
        "stats": {
            "total_alarms": total_alarms,
            "active_alarms": active_alarms,
            "inactive_alarms": total_alarms - active_alarms,
        },
    }


# ============================================================
# WELLNESS COACH dashboard — coaching stats
# ============================================================

@router.get("/wellness/dashboard", summary="Wellness Coach — coaching panel")
def wellness_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: dict = Depends(require_role("WELLNESS_COACH", "ADMIN")),
):
    # Coaches see aggregate stats across all USER accounts they oversee.
    # In Phase 3+ this would be filtered to a coach-user mapping table;
    # for now it returns platform-wide USER stats.
    user_count = db.query(User).filter(User.role == RoleEnum.USER).count()
    total_user_alarms = (
        db.query(Alarm)
        .join(User, Alarm.user_id == User.id)
        .filter(User.role == RoleEnum.USER)
        .count()
    )
    active_user_alarms = (
        db.query(Alarm)
        .join(User, Alarm.user_id == User.id)
        .filter(User.role == RoleEnum.USER, Alarm.is_active == True)
        .count()
    )

    return {
        "message": f"Welcome, Coach {current_user.name}",
        "coach": {
            "id": current_user.id,
            "name": current_user.name,
            "email": current_user.email,
        },
        "roster_stats": {
            "total_users": user_count,
            "total_alarms": total_user_alarms,
            "active_alarms": active_user_alarms,
        },
    }