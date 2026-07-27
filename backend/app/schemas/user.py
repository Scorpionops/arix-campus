from pydantic import BaseModel, EmailStr
from typing import Optional
from app.models.user import RoleEnum

# Role Schemas
class RoleBase(BaseModel):
    name: RoleEnum
    description: Optional[str] = None

class RoleCreate(RoleBase):
    pass

class RoleResponse(RoleBase):
    id: int
    class Config:
        from_attributes = True

# User Schemas
class UserBase(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str

class UserCreate(UserBase):
    password: str
    role_name: RoleEnum

class UserResponse(UserBase):
    id: int
    is_active: bool
    role: Optional[RoleResponse] = None

    class Config:
        from_attributes = True

# Auth Schemas
class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class RefreshTokenRequest(BaseModel):
    refresh_token: str
