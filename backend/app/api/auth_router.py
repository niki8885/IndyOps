from fastapi import HTTPException, Depends, APIRouter
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext

from app.core.security import create_access_token
from app.core.database import UserDB, get_db

router = APIRouter()


class UserRegister(BaseModel):
    username: str
    password: str
    email:    EmailStr

class UserLogin(BaseModel):
    username: str
    password: str


_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def _hash_password(password: str) -> str:
    return _pwd_context.hash(password)

def _verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)

def _user_profile(user: UserDB) -> dict:
    return {
        "user_id":  user.id,
        "username": user.username,
        "email":    user.email,
    }


@router.post("/register", summary="Register a new user")
async def register(user: UserRegister, db: Session = Depends(get_db)):
    if db.query(UserDB).filter(UserDB.username == user.username).first():
        raise HTTPException(status_code=400, detail="Username already registered")
    if db.query(UserDB).filter(UserDB.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    new_user = UserDB(
        username=user.username,
        hashed_password=_hash_password(user.password),
        email=user.email,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"status": "user created", **_user_profile(new_user)}


@router.post("/login", summary="Login and receive JWT token")
async def login(user: UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(UserDB).filter(UserDB.username == user.username).first()
    if not db_user or not _verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token({"sub": str(db_user.id)})
    return {"access_token": token, "token_type": "bearer", **_user_profile(db_user)}

