from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from jose import JWTError, jwt
from datetime import datetime, timedelta
from . import models, database
from .security import hash_password, verify_password
import re

def get_session_token():
    # Placeholder implementation for get_session_token
    return "mocked-session-token"

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

SECRET_KEY = database.APP_CONFIG.secret_key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

def get_user_by_username(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()

def authenticate_user(db: Session, username: str, password: str):
    user = get_user_by_username(db, username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

@router.post("/register", response_model=models.UserPublic, status_code=status.HTTP_201_CREATED)
def register(user: models.UserCreate, db: Session = Depends(database.get_db)):
    if get_user_by_username(db, user.username):
        raise HTTPException(status_code=400, detail="Username already registered")
    existing_email = db.query(models.User).filter(models.User.email == user.email).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")
    if len(user.password) < 10:
        raise HTTPException(status_code=400, detail="Password must be at least 10 characters long.")
    if not re.search(r"[A-Z]", user.password):
        raise HTTPException(status_code=400, detail="Password must include an uppercase letter.")
    if not re.search(r"[a-z]", user.password):
        raise HTTPException(status_code=400, detail="Password must include a lowercase letter.")
    if not re.search(r"\d", user.password):
        raise HTTPException(status_code=400, detail="Password must include a digit.")
    try:
        hashed = hash_password(user.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    new_user = models.User(username=user.username, email=user.email, hashed_password=hashed)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return models.UserPublic.from_orm(new_user)

@router.post("/token")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(database.get_db)):
    user = authenticate_user(db, form.username, form.password)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid credentials")
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": token, "token_type": "bearer"}

@router.get("/me")
def read_users_me(token: str = Depends(oauth2_scheme)):
    username = decode_jwt_token(token)
    return {"username": username}

# Dependency to get current user

def decode_jwt_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token: username not found")
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
def get_current_user(token: str = Depends(oauth2_scheme)):
    return decode_jwt_token(token)


def get_current_user_model(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(database.get_db),
):
    username = decode_jwt_token(token)
    user = get_user_by_username(db, username)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user

@router.get("/topstep-token")
def topstep_login(current_user: str = Depends(get_current_user)):
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Legacy TopStep token endpoint is disabled. Use saved broker integrations.",
    )


@router.get("/rules")
def get_rules(
    current_user: str = Depends(get_current_user),
    db: Session = Depends(database.get_db),
):
    user = get_user_by_username(db, current_user)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "buy_threshold": user.buy_threshold or 30,
        "sell_threshold": user.sell_threshold or 70,

    }


@router.put("/rules")
def update_rules(
    rules: models.TradingRuleUpdate,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(database.get_db),
):
    user = get_user_by_username(db, current_user)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.buy_threshold = rules.buy_threshold
    user.sell_threshold = rules.sell_threshold
    db.commit()
    db.refresh(user)
    return {"status": "updated"}
