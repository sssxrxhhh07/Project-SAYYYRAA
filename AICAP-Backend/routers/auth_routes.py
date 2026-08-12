import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from database import get_db
from models import User, ProviderEnum
from schemas import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
)
from auth import (
    create_access_token,
    oauth,
)

router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"]
)


# --------------------------
# Register
# --------------------------

@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(
    data: RegisterRequest,
    db: Session = Depends(get_db)
):
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already exists"
        )

    hashed = bcrypt.hashpw(
        data.password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")

    user = User(
        name=data.name,
        email=data.email,
        password=hashed,
        role=data.role,
        provider=ProviderEnum.LOCAL
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "message": "Registration Successful",
        "user_id": user.id
    }


# --------------------------
# Login
# --------------------------

@router.post("/login", response_model=TokenResponse)
def login(
    data: LoginRequest,
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not user.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Email or Password"
        )

    if not bcrypt.checkpw(
        data.password.encode("utf-8"),
        user.password.encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Email or Password"
        )

    jwt_token = create_access_token(user)

    return TokenResponse(
        access_token=jwt_token,
        token_type="bearer",
        role=user.role,
        name=user.name,
        email=user.email,
    )


# --------------------------
# Google Login
# --------------------------

@router.get("/google")
async def google_login(request: Request):
    redirect_uri = request.url_for("google_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


# --------------------------
# Google Callback
# --------------------------

@router.get("/google/callback", response_model=TokenResponse)
async def google_callback(
    request: Request,
    db: Session = Depends(get_db)
):
    token = await oauth.google.authorize_access_token(request)
    info = token.get("userinfo")
    if not info:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Login Failed"
        )

    email = info.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google user email not provided"
        )

    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            name=info.get("name", email.split("@")[0]),
            email=email,
            password=None,
            role="USER",
            provider=ProviderEnum.GOOGLE,
            profile_picture=info.get("picture")
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    jwt_token = create_access_token(user)

    return TokenResponse(
        access_token=jwt_token,
        token_type="bearer",
        role=user.role,
        name=user.name,
        email=user.email,
    )


# --------------------------
# Logout
# --------------------------

@router.post("/logout")
def logout():
    return {
        "message": "Logout Successful"
    }