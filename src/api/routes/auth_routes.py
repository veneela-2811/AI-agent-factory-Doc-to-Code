from datetime import timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Request, Body
from fastapi.responses import RedirectResponse
from src.api.schemas import TokenResponse, LoginRequest, RegisterRequest
from src.auth.jwt import create_access_token, get_password_hash, verify_password
from config.settings import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])

# In-memory single-user auth for assignment scope
USERS_DB = {
    "admin": get_password_hash("password123")
}


@router.get("/login", include_in_schema=False)
async def login_browser_redirect():
    # If user accesses /auth/login via browser GET, redirect them to Swagger UI
    return RedirectResponse(url="/docs")


@router.post("/register", response_model=TokenResponse, summary="Register a user (Dev)")
async def register(req: RegisterRequest):
    if req.username in USERS_DB:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": {"code": "USER_EXISTS", "message": f"User '{req.username}' already exists", "details": None}}
        )
    USERS_DB[req.username] = get_password_hash(req.password)
    token = create_access_token({"sub": req.username})
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in_minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )


@router.post("/login", response_model=TokenResponse, summary="Login and get JWT token")
async def login(
    request: Request,
    body: Optional[LoginRequest] = Body(default=None)
):
    username = None
    password = None

    if body is not None and body.username and body.password:
        username = body.username
        password = body.password
    else:
        # Check form-data / urlencoded fallback
        try:
            form = await request.form()
            username = form.get("username")
            password = form.get("password")
        except Exception:
            pass

    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": {"code": "VALIDATION_ERROR", "message": "Both username and password are required", "details": None}}
        )

    # Auto-register admin or user if not present in dev
    if username not in USERS_DB:
        USERS_DB[username] = get_password_hash(password)
    
    hashed = USERS_DB[username]
    if not verify_password(password, hashed):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "INVALID_CREDENTIALS", "message": "Incorrect username or password", "details": None}}
        )
    
    token = create_access_token({"sub": username})
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in_minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
