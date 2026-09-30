from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import jwt
from jwt.exceptions import InvalidTokenError as JWTError
from datetime import datetime, timedelta
import hashlib
import secrets
from uuid import uuid4
from . import analytics_service, models, database, beta_access_service
from .email_service import email_service
from .observability import redact
from .security import hash_password, verify_password
import re

def get_session_token():
    # Placeholder implementation for get_session_token
    return "mocked-session-token"

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token", auto_error=False)

SECRET_KEY = database.APP_CONFIG.secret_key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = database.APP_CONFIG.session_lifetime_minutes
EMAIL_VERIFICATION_EXPIRE_HOURS = 24
PASSWORD_RESET_EXPIRE_MINUTES = 30
EMAIL_RESEND_COOLDOWN_SECONDS = 60


class TokenRequest(BaseModel):
    token: str = Field(..., min_length=20)


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetConfirm(BaseModel):
    token: str = Field(..., min_length=20)
    password: str


class RecoveryRequest(BaseModel):
    contact_email: str
    message: str = Field(..., min_length=4, max_length=4000)
    category: str = "account_recovery"


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=80)
    preferred_contact_email: str | None = Field(default=None, max_length=255)
    trading_experience_level: str | None = Field(default=None, max_length=80)

def get_user_by_username(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()

def authenticate_user(db: Session, username: str, password: str):
    user = get_user_by_username(db, username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def _hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _new_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, _hash_value(token)


def _ip_hash(request: Request | None) -> str | None:
    if not request or not request.client:
        return None
    return _hash_value(request.client.host)


def _user_agent_summary(request: Request | None) -> str | None:
    if not request:
        return None
    user_agent = request.headers.get("user-agent")
    if not user_agent:
        return None
    return user_agent[:180]


def _validate_password(password: str) -> None:
    if len(password) < 10:
        raise HTTPException(status_code=400, detail="Password must be at least 10 characters long.")
    if not re.search(r"[A-Z]", password):
        raise HTTPException(status_code=400, detail="Password must include an uppercase letter.")
    if not re.search(r"[a-z]", password):
        raise HTTPException(status_code=400, detail="Password must include a lowercase letter.")
    if not re.search(r"\d", password):
        raise HTTPException(status_code=400, detail="Password must include a digit.")


def _sanitize_support_message(message: str) -> str:
    sanitized = re.sub(
        r"(?i)\b(api[_-]?key|secret|token|password)\s*[:=]\s*\S+",
        lambda match: f"{match.group(1)}=[REDACTED]",
        message,
    )
    return str(redact({"message": sanitized})["message"])


def _create_email_verification(db: Session, user: models.User) -> str:
    token, token_hash = _new_token()
    now = datetime.utcnow()
    record = models.EmailVerificationToken(
        user_id=user.id,
        token_hash=token_hash,
        email=user.email,
        expires_at=now + timedelta(hours=EMAIL_VERIFICATION_EXPIRE_HOURS),
        last_sent_at=now,
    )
    db.add(record)
    db.flush()
    return token


def _create_password_reset(db: Session, user: models.User) -> str:
    token, token_hash = _new_token()
    db.add(
        models.PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            email=user.email,
            expires_at=datetime.utcnow() + timedelta(minutes=PASSWORD_RESET_EXPIRE_MINUTES),
        )
    )
    db.flush()
    return token


def _serialize_session(session: models.UserSession) -> dict:
    return {
        "id": session.id,
        "session_id": session.session_id,
        "user_agent_summary": session.user_agent_summary,
        "created_at": session.created_at.isoformat() + "Z" if session.created_at else None,
        "expires_at": session.expires_at.isoformat() + "Z" if session.expires_at else None,
        "last_seen_at": session.last_seen_at.isoformat() + "Z" if session.last_seen_at else None,
        "revoked_at": session.revoked_at.isoformat() + "Z" if session.revoked_at else None,
        "revocation_reason": session.revocation_reason,
    }


def _authenticated_repository(db: Session, user: models.User):
    from .authorization import TenantContext
    from .tenant_repository import TenantRepository

    return TenantRepository(
        db, TenantContext(user.id, user.username, actor_user_id=user.id, source="session")
    )


def _assert_session_active(db: Session, payload: dict) -> models.UserSession:
    session_id = payload.get("sid")
    if not session_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session identifier is required")
    session = db.query(models.UserSession).filter(models.UserSession.session_id == session_id).first()
    if not session or session.revoked_at is not None or session.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session revoked or expired")
    session.last_seen_at = datetime.utcnow()
    db.commit()
    return session


def _request_token(request: Request, bearer_token: str | None) -> tuple[str, bool]:
    if bearer_token:
        return bearer_token, False
    cookie_token = request.cookies.get(database.APP_CONFIG.session_cookie_name)
    if cookie_token:
        return cookie_token, True
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


def _enforce_csrf(request: Request, session: models.UserSession, cookie_authenticated: bool) -> None:
    if not cookie_authenticated or request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    header_token = request.headers.get("X-CSRF-Token")
    cookie_token = request.cookies.get(database.APP_CONFIG.csrf_cookie_name)
    if (
        not header_token
        or not cookie_token
        or not secrets.compare_digest(header_token, cookie_token)
        or not session.csrf_token_hash
        or not secrets.compare_digest(_hash_value(header_token), session.csrf_token_hash)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")


def _set_session_cookies(response: Response, token: str, csrf_token: str) -> None:
    secure = database.APP_CONFIG.is_production
    max_age = database.APP_CONFIG.session_lifetime_minutes * 60
    response.set_cookie(
        database.APP_CONFIG.session_cookie_name,
        token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        database.APP_CONFIG.csrf_cookie_name,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(database.APP_CONFIG.session_cookie_name, path="/")
    response.delete_cookie(database.APP_CONFIG.csrf_cookie_name, path="/")


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
    _validate_password(user.password)
    try:
        hashed = hash_password(user.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    new_user = models.User(username=user.username, email=user.email, hashed_password=hashed)
    db.add(new_user)
    db.flush()
    verification_token = _create_email_verification(db, new_user)
    email_service.send_verification(to_email=new_user.email, token=verification_token)
    analytics_service.capture_event(
        db,
        event_name="registration_completed",
        user_id=new_user.id,
        metadata={"email_verification_sent": True},
        source="auth",
    )
    analytics_service.capture_event(
        db,
        event_name="email_verification_sent",
        user_id=new_user.id,
        metadata={"delivery_provider": "resend" if database.APP_CONFIG.resend_api_key else "local"},
        source="auth",
    )
    db.commit()
    db.refresh(new_user)
    return models.UserPublic.from_orm(new_user)

@router.post("/token")
def login(
    request: Request,
    response: Response,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(database.get_db),
):
    user = authenticate_user(db, form.username, form.password)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid credentials")
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    expires_at = datetime.utcnow() + access_token_expires
    session_id = uuid4().hex
    csrf_token = secrets.token_urlsafe(32)
    db.add(
        models.UserSession(
            user_id=user.id,
            session_id=session_id,
            user_agent_summary=_user_agent_summary(request),
            ip_hash=_ip_hash(request),
            expires_at=expires_at,
            csrf_token_hash=_hash_value(csrf_token),
        )
    )
    db.commit()
    token = create_access_token(
        data={"sub": user.username, "sid": session_id}, expires_delta=access_token_expires
    )
    _set_session_cookies(response, token, csrf_token)
    return {"access_token": token, "token_type": "bearer"}

# Dependency to get current user

def decode_jwt_payload(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token: username not found")
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def decode_jwt_token(token: str):
    return decode_jwt_payload(token).get("sub")


def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(database.get_db),
):
    resolved_token, cookie_authenticated = _request_token(request, token)
    payload = decode_jwt_payload(resolved_token)
    session = _assert_session_active(db, payload)
    _enforce_csrf(request, session, cookie_authenticated)
    username = payload.get("sub")
    user = get_user_by_username(db, username)
    if not user or getattr(user, "account_status", "active") != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    _bind_authenticated_context(request, db, user, session)
    return username


def get_current_user_model(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(database.get_db),
):
    resolved_token, cookie_authenticated = _request_token(request, token)
    payload = decode_jwt_payload(resolved_token)
    session = _assert_session_active(db, payload)
    _enforce_csrf(request, session, cookie_authenticated)
    username = payload.get("sub")
    user = get_user_by_username(db, username)
    if not user or getattr(user, "account_status", "active") != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    _bind_authenticated_context(request, db, user, session)
    return user


def _bind_authenticated_context(
    request: Request,
    db: Session,
    user: models.User,
    session: models.UserSession,
) -> None:
    """Construct tenant authority only after JWT, session, CSRF, and user validation."""
    from .authorization import TenantContext
    from .tenant_repository import bind_tenant_context
    from .time_utils import as_utc, utc_now

    context = TenantContext(
        user_id=user.id,
        username=user.username,
        actor_user_id=user.id,
        session_id=session.session_id,
        roles=("operator",) if user.is_admin else ("user",),
        source="session",
        request_id=request.headers.get("X-Request-ID"),
        created_at=utc_now(),
        expires_at=as_utc(session.expires_at),
        integrity_verified=True,
    )
    bind_tenant_context(db, context)
    request.state.tenant_context = context


@router.get("/me")
def read_users_me(current_user: models.User = Depends(get_current_user_model)):
    return models.UserPublic.from_orm(current_user)


def require_verified_user_model(current_user: models.User = Depends(get_current_user_model)):
    if current_user.email_verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification is required before beta access.",
            headers={"X-Readiness-Blocker": "email_verification_required"},
        )
    return current_user


@router.get("/beta-readiness")
def beta_readiness(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    return beta_access_service.combined_beta_readiness(db, current_user)


@router.post("/verify-email")
def verify_email(request: TokenRequest, db: Session = Depends(database.get_db)):
    record = (
        db.query(models.EmailVerificationToken)
        .filter(models.EmailVerificationToken.token_hash == _hash_value(request.token))
        .first()
    )
    if not record or record.consumed_at is not None or record.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification token.")
    user = db.query(models.User).filter(models.User.id == record.user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification token.")
    now = datetime.utcnow()
    user.email_verified_at = now
    record.consumed_at = now
    analytics_service.capture_event(
        db,
        event_name="email_verification_completed",
        user_id=user.id,
        metadata={"completed": True},
        source="auth",
    )
    db.commit()
    return {"status": "verified"}


@router.post("/resend-verification")
def resend_verification(current_user: models.User = Depends(get_current_user_model), db: Session = Depends(database.get_db)):
    if current_user.email_verified_at is not None:
        return {"status": "already_verified"}
    latest_rows = _authenticated_repository(db, current_user).list(
        models.EmailVerificationToken,
        order_by=(models.EmailVerificationToken.created_at.desc(),), limit=1,
    )
    latest = latest_rows[0] if latest_rows else None
    now = datetime.utcnow()
    if latest and latest.last_sent_at and (now - latest.last_sent_at).total_seconds() < EMAIL_RESEND_COOLDOWN_SECONDS:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Verification email was sent recently.")
    token = _create_email_verification(db, current_user)
    email_service.send_verification(to_email=current_user.email, token=token)
    db.commit()
    return {"status": "sent"}


@router.post("/password-reset/request")
def request_password_reset(request: PasswordResetRequest, db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.email == request.email).first()
    if user:
        token = _create_password_reset(db, user)
        email_service.send_password_reset(to_email=user.email, token=token)
        db.commit()
    return {"status": "accepted"}


@router.post("/password-reset/confirm")
def confirm_password_reset(request: PasswordResetConfirm, db: Session = Depends(database.get_db)):
    _validate_password(request.password)
    record = (
        db.query(models.PasswordResetToken)
        .filter(models.PasswordResetToken.token_hash == _hash_value(request.token))
        .first()
    )
    if not record or record.consumed_at is not None or record.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token.")
    user = db.query(models.User).filter(models.User.id == record.user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token.")
    try:
        user.hashed_password = hash_password(request.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    now = datetime.utcnow()
    record.consumed_at = now
    (
        db.query(models.UserSession)
        .filter(models.UserSession.user_id == user.id, models.UserSession.revoked_at.is_(None))
        .update({"revoked_at": now, "revocation_reason": "password_reset"})
    )
    db.commit()
    return {"status": "password_reset"}


@router.post("/account-recovery")
def account_recovery(request: RecoveryRequest, db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.email == request.contact_email).first()
    reference_id = f"rec_{uuid4().hex[:12]}"
    record = models.AccountRecoveryRequest(
        user_id=user.id if user else None,
        reference_id=reference_id,
        contact_email=request.contact_email,
        category=request.category or "account_recovery",
        sanitized_message=_sanitize_support_message(request.message),
        request_metadata={"source": "account_lifecycle"},
    )
    db.add(record)
    db.commit()
    return {"status": "received", "reference_id": reference_id}


@router.get("/account-recovery")
def list_account_recovery_requests(
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    records = _authenticated_repository(db, current_user).list(
        models.AccountRecoveryRequest,
        order_by=(models.AccountRecoveryRequest.created_at.desc(),), limit=50,
    )
    return [
        {
            "reference_id": record.reference_id,
            "category": record.category,
            "status": record.status,
            "created_at": record.created_at.isoformat() + "Z" if record.created_at else None,
        }
        for record in records
    ]


@router.get("/profile")
def get_profile(current_user: models.User = Depends(get_current_user_model)):
    return models.UserPublic.from_orm(current_user)


@router.put("/profile")
def update_profile(
    request: ProfileUpdate,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    if request.preferred_contact_email is not None and "@" not in request.preferred_contact_email:
        raise HTTPException(status_code=400, detail="Preferred contact email must be valid.")
    for field in ("display_name", "timezone", "preferred_contact_email", "trading_experience_level"):
        value = getattr(request, field)
        if value is not None:
            setattr(current_user, field, value.strip() or None)
    db.commit()
    db.refresh(current_user)
    return models.UserPublic.from_orm(current_user)


@router.get("/sessions")
def list_sessions(current_user: models.User = Depends(get_current_user_model), db: Session = Depends(database.get_db)):
    sessions = _authenticated_repository(db, current_user).list(
        models.UserSession, order_by=(models.UserSession.created_at.desc(),), limit=100
    )
    return [_serialize_session(session) for session in sessions]


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    token: str | None = Depends(oauth2_scheme),
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    resolved_token, _ = _request_token(request, token)
    payload = decode_jwt_payload(resolved_token)
    session = _authenticated_repository(db, current_user).first(
        models.UserSession, models.UserSession.session_id == payload.get("sid")
    )
    if session and session.revoked_at is None:
        session.revoked_at = datetime.utcnow()
        session.revocation_reason = "logout"
        db.commit()
    _clear_session_cookies(response)
    return {"status": "logged_out"}


@router.post("/sessions/rotate")
def rotate_session(
    request: Request,
    response: Response,
    token: str | None = Depends(oauth2_scheme),
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    old_token, _ = _request_token(request, token)
    old_payload = decode_jwt_payload(old_token)
    repository = _authenticated_repository(db, current_user)
    old_session = repository.first(models.UserSession, models.UserSession.session_id == old_payload.get("sid"))
    if not old_session:
        raise HTTPException(status_code=401, detail="Session not found")
    now = datetime.utcnow()
    old_session.revoked_at = now
    old_session.revocation_reason = "rotated"
    session_id = uuid4().hex
    csrf_token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    repository.add(
        models.UserSession(
            user_id=current_user.id,
            session_id=session_id,
            user_agent_summary=_user_agent_summary(request),
            ip_hash=_ip_hash(request),
            expires_at=expires_at,
            csrf_token_hash=_hash_value(csrf_token),
        )
    )
    db.commit()
    new_token = create_access_token(
        {"sub": current_user.username, "sid": session_id},
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    _set_session_cookies(response, new_token, csrf_token)
    return {"status": "rotated"}


@router.post("/sessions/{session_id}/revoke")
def revoke_session(
    session_id: str,
    current_user: models.User = Depends(get_current_user_model),
    db: Session = Depends(database.get_db),
):
    session = _authenticated_repository(db, current_user).first(
        models.UserSession, models.UserSession.session_id == session_id
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    if session.revoked_at is None:
        session.revoked_at = datetime.utcnow()
        session.revocation_reason = "user_revoked"
        db.commit()
        db.refresh(session)
    return _serialize_session(session)

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
