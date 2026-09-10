import time
import hmac
import hashlib
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Header
from backend.config import UserTier
from backend.database import db_service
from backend.shields import anti_abus_shield

SECRET_AUTH_KEY = "translate_for_pdf_secret_auth_token_key_2026"

auth_router = APIRouter(tags=["Authentication"])


class RegisterSchema(BaseModel):
    email: str
    password: str


class LoginSchema(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    token: str
    user_id: str
    email: str
    plan_tier: str
    message: str


def generate_auth_token(user_id: str, email: str) -> str:
    timestamp = str(int(time.time()))
    payload = f"{user_id}:{email}:{timestamp}"
    signature = hmac.new(SECRET_AUTH_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def parse_and_validate_token(token: str) -> Optional[dict]:
    if not token or ":" not in token:
        return None
    parts = token.split(":")
    if len(parts) != 4:
        return None
    user_id, email, timestamp, signature = parts
    payload = f"{user_id}:{email}:{timestamp}"
    expected_sig = hmac.new(SECRET_AUTH_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_sig):
        return None
    # Valide pendant 30 jours
    try:
        if time.time() - int(timestamp) > 30 * 86400:
            return None
    except Exception:
        return None
    return {"user_id": user_id, "email": email}


def get_current_user_from_header(authorization: Optional[str] = None) -> Optional[dict]:
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "").strip()
    data = parse_and_validate_token(token)
    if not data:
        return None
    return db_service.get_user_profile(data["user_id"])


@auth_router.post("/register", response_model=AuthResponse)
def register(body: RegisterSchema):
    email = body.email.strip().lower()
    password = body.password.strip()

    if not email or "@" not in email or "." not in email:
        raise HTTPException(status_code=400, detail="Veuillez fournir une adresse email valide.")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Le mot de passe doit contenir au moins 6 caractères.")

    # Bouclier 3: Rejet des emails jetables
    if anti_abus_shield.is_disposable_email(email):
        raise HTTPException(
            status_code=400,
            detail="Les adresses emails temporaires ou jetables sont strictement refusées pour protéger la plateforme."
        )

    try:
        user = db_service.register_account(email, password, UserTier.FREE)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    token = generate_auth_token(user["user_id"], user["email"])
    msg = "Compte gratuit créé avec succès ! Quota de 2 documents/jour jusqu'à 10 pages activé."
    if user.get("confirmation_sent"):
        msg = "Compte créé ! Un email de confirmation vous a été envoyé. Veuillez vérifier votre boîte de réception."

    return AuthResponse(
        token=token,
        user_id=user["user_id"],
        email=user["email"],
        plan_tier=user["plan_tier"].value,
        message=msg
    )


@auth_router.post("/login", response_model=AuthResponse)
def login(body: LoginSchema):
    email = body.email.strip().lower()
    password = body.password.strip()
    try:
        user = db_service.authenticate_account(email, password)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    if not user:
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect.")

    token = generate_auth_token(user["user_id"], user["email"])
    return AuthResponse(
        token=token,
        user_id=user["user_id"],
        email=user["email"],
        plan_tier=user["plan_tier"].value,
        message="Connexion réussie !"
    )


@auth_router.get("/me")
def get_me(authorization: Optional[str] = Header(None)):
    user = get_current_user_from_header(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Session expirée ou non authentifié.")
    quotas = db_service.get_quota_summary(user["user_id"])
    return quotas
