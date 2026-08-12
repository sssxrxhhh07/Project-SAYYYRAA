from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user
from models import User
from schemas import UserProfile, UpdateProfileRequest

router = APIRouter(
    prefix="/api",
    tags=["Profile"]
)


@router.get("/me", response_model=UserProfile)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/profile", response_model=UserProfile)
def get_profile(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/profile", response_model=UserProfile)
def update_profile(
    data: UpdateProfileRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if data.name is not None:
        current_user.name = data.name

    if data.phone is not None:
        current_user.phone = data.phone

    if data.bio is not None:
        current_user.bio = data.bio

    if data.profile_picture is not None:
        current_user.profile_picture = data.profile_picture

    # Role and Email updates are explicitly omitted to prevent privilege escalation
    db.commit()
    db.refresh(current_user)

    return current_user