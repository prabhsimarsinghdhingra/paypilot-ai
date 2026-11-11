from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.security import create_token, hash_password, verify_password
from app.db import get_db
from app.deps import current_user, rate_limit
from app.models import User

router = APIRouter(prefix="/auth", tags=["Auth"])

class Register(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="", max_length=100)

class Login(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)

def _out(u: User): return {"id": u.id, "email": u.email, "name": u.name}

@router.post("/register", status_code=201, dependencies=[Depends(rate_limit("register", 10))])
def register(b: Register, db: Session = Depends(get_db)):
    email = b.email.lower()
    if db.scalar(select(User).where(User.email == email)): raise HTTPException(409, "Email already registered")
    u = User(email=email, password_hash=hash_password(b.password), name=b.name); db.add(u); db.commit()
    return {"token": create_token(u.id), "user": _out(u)}

@router.post("/login", dependencies=[Depends(rate_limit("login", 10))])
def login(b: Login, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.email == b.email.lower()))
    if not u or not verify_password(b.password, u.password_hash): raise HTTPException(401, "Invalid email or password")
    return {"token": create_token(u.id), "user": _out(u)}

@router.get("/me")
def me(u: User = Depends(current_user)): return _out(u)
