from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi.security import OAuth2PasswordRequestForm
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.security import get_password_hash, verify_password, create_access_token, create_refresh_token, decode_token
from app.core.dependencies import get_current_active_user
from app.models.user import User, Role, RefreshToken, RoleEnum
from app.schemas.user import UserCreate, UserResponse, Token, RefreshTokenRequest

router = APIRouter()

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    # Check if user exists
    result = await db.execute(select(User).where(User.email == user_in.email))
    user = result.scalars().first()
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        )

    # Check and get role
    result = await db.execute(select(Role).where(Role.name == user_in.role_name))
    role = result.scalars().first()
    if not role:
        # For simplicity, create role if it doesn't exist during initial setup.
        # In a real scenario, roles should be seeded separately.
        role = Role(name=user_in.role_name)
        db.add(role)
        await db.commit()
        await db.refresh(role)

    # Create new user
    user = User(
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        first_name=user_in.first_name,
        last_name=user_in.last_name,
        role_id=role.id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Pre-fetch the role relationship for the response
    result = await db.execute(select(User).where(User.id == user.id))
    user = result.scalars().first()
    # Explicitly load role since we didn't specify lazy="joined" in model
    result_role = await db.execute(select(Role).where(Role.id == user.role_id))
    user.role = result_role.scalars().first()

    return user

@router.post("/login", response_model=Token)
async def login(
    db: AsyncSession = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends()
):
    # Find user by email
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalars().first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect email or password"
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    # Create tokens
    access_token = create_access_token(subject=user.id)
    refresh_token = create_refresh_token(subject=user.id)

    # Decode refresh token to get expiration
    decoded_refresh = decode_token(refresh_token)
    expires_at = datetime.fromtimestamp(decoded_refresh["exp"], tz=timezone.utc)

    # Store refresh token in db
    db_token = RefreshToken(
        token=refresh_token,
        user_id=user.id,
        expires_at=expires_at
    )
    db.add(db_token)
    await db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }

@router.post("/refresh", response_model=Token)
async def refresh_token(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    try:
        payload = decode_token(request.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user_id = payload.get("sub")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    # Check if token exists and is valid in DB
    result = await db.execute(
        select(RefreshToken)
        .where(RefreshToken.token == request.refresh_token)
        .where(RefreshToken.is_revoked == False)
    )
    db_token = result.scalars().first()

    if not db_token:
        raise HTTPException(status_code=401, detail="Invalid or revoked refresh token")

    # Create new tokens
    new_access_token = create_access_token(subject=user_id)
    new_refresh_token = create_refresh_token(subject=user_id)

    # Decode new refresh token to get expiration
    decoded_refresh = decode_token(new_refresh_token)
    expires_at = datetime.fromtimestamp(decoded_refresh["exp"], tz=timezone.utc)

    # Revoke old token and save new one
    db_token.is_revoked = True

    new_db_token = RefreshToken(
        token=new_refresh_token,
        user_id=int(user_id),
        expires_at=expires_at
    )
    db.add(new_db_token)
    await db.commit()

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer"
    }

@router.post("/logout")
async def logout(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    result = await db.execute(
        select(RefreshToken)
        .where(RefreshToken.token == request.refresh_token)
        .where(RefreshToken.user_id == current_user.id)
    )
    db_token = result.scalars().first()

    if db_token:
        db_token.is_revoked = True
        await db.commit()

    return {"message": "Successfully logged out"}

@router.get("/me", response_model=UserResponse)
async def read_users_me(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    result_role = await db.execute(select(Role).where(Role.id == current_user.role_id))
    current_user.role = result_role.scalars().first()
    return current_user
