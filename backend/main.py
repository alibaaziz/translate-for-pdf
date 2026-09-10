import os
import sys
import fitz
from typing import Optional
from fastapi import FastAPI, File, UploadFile, Form, Header, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import SUPPORTED_LANGUAGES, ISO_TO_NLLB
from backend.config import (
    UserTier, TIER_RULES, PLATFORM_ABSOLUTE_MAX_PAGES, UPLOADS_DIR, TRANSLATED_DIR
)
from backend.models import QuoteResponse, TranslationTaskStatus, CircuitBreakerStatus
from backend.shields import circuit_breaker, anti_abus_shield
from backend.database import db_service
from backend.worker import queue_translation_task, TASKS

from backend.auth import auth_router, get_current_user_from_header
from backend.payments import payments_router

app = FastAPI(
    title="translate-for-pdf.com API",
    description="API REST de traduction haute-fidelite de documents PDF avec preservation vectorielle integrale.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/auth")
app.include_router(payments_router)

from fastapi.staticfiles import StaticFiles

STATIC_DIR = os.path.join(CURRENT_DIR, "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def resolve_user_tier(user_id: Optional[str] = None, authorization: Optional[str] = None) -> tuple[UserTier, Optional[dict]]:
    if authorization and authorization.strip():
        user = get_current_user_from_header(authorization)
        if user:
            return (user["plan_tier"], user)
    if user_id and user_id.strip():
        profile = db_service.get_user_profile(user_id)
        return (profile["plan_tier"], profile)
    return (UserTier.ANONYMOUS, None)


@app.get("/")
def serve_home():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {
        "service": "translate-for-pdf.com API",
        "status": "online",
        "docs_url": "/docs",
        "version": "1.0.0"
    }


@app.get("/api/languages")
def get_languages():
    return [{"code": code, "name": name} for code, name in SUPPORTED_LANGUAGES]


@app.get("/api/shields/status", response_model=CircuitBreakerStatus)
def get_shields_status():
    status = circuit_breaker.get_status()
    return CircuitBreakerStatus(**status)


@app.post("/api/quote", response_model=QuoteResponse)
async def get_quote(
    request: Request,
    file: UploadFile = File(...),
    user_id: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None)
):
    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Fichier PDF vide.")

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        page_count = len(doc)
        doc.close()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Fichier PDF invalide : {e}")

    tier, profile = resolve_user_tier(user_id, authorization)
    effective_user_id = profile["user_id"] if profile else user_id
    client_ip = request.client.host if request.client else "127.0.0.1"

    # REGLE ABSOLUE 1 : Plafond plateforme a 100 pages
    if page_count > PLATFORM_ABSOLUTE_MAX_PAGES:
        return QuoteResponse(
            page_count=page_count,
            user_tier=tier,
            can_translate=False,
            status="REJECTED_TOO_LARGE",
            message=f"La plateforme ne traduit pas les documents de plus de 100 pages ({page_count} pages detectees). Veuillez scinder votre PDF.",
            device_assigned="none",
            watermark_applied=False
        )

    # BOUCLIER 2 : Circuit Breaker pour gratuits
    if tier in (UserTier.ANONYMOUS, UserTier.FREE):
        can_free, breaker_msg = circuit_breaker.can_process_free()
        if not can_free:
            return QuoteResponse(
                page_count=page_count,
                user_tier=tier,
                can_translate=False,
                status="CIRCUIT_BREAKER_TRIPPED",
                message=breaker_msg,
                suggested_tier=UserTier.STARTER,
                device_assigned="none",
                watermark_applied=False
            )

    # CAS 1 : Visiteur Anonyme (Max 5 pages, 1 doc/jour)
    if tier == UserTier.ANONYMOUS:
        if page_count > 5:
            return QuoteResponse(
                page_count=page_count,
                user_tier=tier,
                can_translate=False,
                status="UPGRADE_REQUIRED",
                message=f"Ce document fait {page_count} pages. Les visiteurs anonymes sont limites a 5 pages. Creez un compte gratuit pour traduire jusqu a 10 pages !",
                suggested_tier=UserTier.FREE,
                device_assigned="cpu",
                watermark_applied=True
            )

        can_anon, ip_msg = anti_abus_shield.check_anonymous_ip(client_ip)
        if not can_anon:
            return QuoteResponse(
                page_count=page_count,
                user_tier=tier,
                can_translate=False,
                status="QUOTA_EXCEEDED",
                message=ip_msg,
                suggested_tier=UserTier.FREE,
                device_assigned="cpu",
                watermark_applied=True
            )

        return QuoteResponse(
            page_count=page_count,
            user_tier=tier,
            can_translate=True,
            status="APPROVED",
            message="Traduction gratuite disponible (Mode Anonyme, 1 doc/jour, max 5 pages).",
            device_assigned="cpu",
            watermark_applied=True
        )

    # CAS 2 : Inscrit Gratuit (Max 10 pages, 2 docs/jour)
    if tier == UserTier.FREE:
        if page_count > 10:
            return QuoteResponse(
                page_count=page_count,
                user_tier=tier,
                can_translate=False,
                status="UPGRADE_REQUIRED",
                message=f"Ce document fait {page_count} pages. Le compte gratuit est limite a 10 pages. Passez a Starter (jusqu a 20 pages) ou Pro !",
                suggested_tier=UserTier.STARTER,
                device_assigned="cpu",
                watermark_applied=True
            )

        used_today = db_service.get_daily_usage(effective_user_id) if effective_user_id else 0
        if used_today >= 2:
            return QuoteResponse(
                page_count=page_count,
                user_tier=tier,
                can_translate=False,
                status="QUOTA_EXCEEDED",
                message="Vous avez atteint votre quota de 2 documents gratuits aujourd hui. Revenez demain ou passez a Starter pour 150 docs/mois !",
                suggested_tier=UserTier.STARTER,
                device_assigned="cpu",
                watermark_applied=True
            )

        return QuoteResponse(
            page_count=page_count,
            user_tier=tier,
            can_translate=True,
            status="APPROVED",
            message=f"Traduction gratuite validee ({2 - used_today} traduction(s) restante(s) aujourd hui).",
            device_assigned="cpu",
            watermark_applied=True
        )

    # CAS 3 : Abonne Starter (4.99$/mois - 150 docs/mois, max 20 pages)
    if tier == UserTier.STARTER:
        if page_count > 20:
            return QuoteResponse(
                page_count=page_count,
                user_tier=tier,
                can_translate=False,
                status="UPGRADE_REQUIRED",
                message=f"Ce document fait {page_count} pages. L offre Starter est limitee a 20 pages par document. Passez a Pro pour traduire jusqu a 100 pages !",
                suggested_tier=UserTier.PRO,
                device_assigned="cuda",
                watermark_applied=False
            )

        used_month = db_service.get_monthly_usage(effective_user_id) if effective_user_id else 0
        if used_month >= 150:
            return QuoteResponse(
                page_count=page_count,
                user_tier=tier,
                can_translate=False,
                status="QUOTA_EXCEEDED",
                message="Vous avez atteint votre quota mensuel de 150 documents. Passez a l offre Pro Illimitee !",
                suggested_tier=UserTier.PRO,
                device_assigned="cuda",
                watermark_applied=False
            )

        return QuoteResponse(
            page_count=page_count,
            user_tier=tier,
            can_translate=True,
            status="APPROVED",
            message=f"Traduction Starter GPU validee ({150 - used_month} documents restants ce mois-ci). Zero filigrane.",
            device_assigned="cuda",
            watermark_applied=False
        )

    # CAS 4 : Abonne Pro (14.99$/mois - Illimite, max 10 docs/jour, jusqu a 100 pages)
    if tier == UserTier.PRO:
        used_today = db_service.get_daily_usage(effective_user_id) if effective_user_id else 0
        if used_today >= 10:
            return QuoteResponse(
                page_count=page_count,
                user_tier=tier,
                can_translate=False,
                status="DAILY_FAIR_USE_LIMIT",
                message="Plafond journalier de securite atteint (10 documents/jour). Vos traductions illimitees reprennent des demain 00:00 UTC !",
                device_assigned="cuda",
                watermark_applied=False
            )

        extra_fee = 0.99 if page_count > 50 else 0.0
        msg = "Traduction Pro Haute Priorite GPU validee. Zero filigrane."
        if extra_fee > 0:
            msg = f"Document de {page_count} pages (> 50 pages) : un surcout de 0,99 $ s applique pour le calcul lourd."

        return QuoteResponse(
            page_count=page_count,
            user_tier=tier,
            can_translate=True,
            status="APPROVED",
            extra_fee_usd=extra_fee,
            message=msg,
            device_assigned="cuda",
            watermark_applied=False
        )

    return QuoteResponse(
        page_count=page_count,
        user_tier=tier,
        can_translate=True,
        status="APPROVED",
        message="Document pret pour la traduction.",
        device_assigned="cpu",
        watermark_applied=True
    )


@app.post("/api/translate")
async def start_translation(
    request: Request,
    file: UploadFile = File(...),
    from_lang: str = Form("en"),
    to_lang: str = Form("fr"),
    user_id: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None)
):
    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Fichier vide.")

    client_ip = request.client.host if request.client else "127.0.0.1"
    tier, profile = resolve_user_tier(user_id, authorization)
    effective_user_id = profile["user_id"] if profile else user_id

    temp_filename = f"upload_{file.filename}"
    save_path = os.path.join(UPLOADS_DIR, temp_filename)
    with open(save_path, "wb") as f:
        f.write(file_bytes)

    if tier == UserTier.ANONYMOUS:
        anti_abus_shield.record_anonymous_ip(client_ip)

    task_id = queue_translation_task(
        input_path=save_path,
        filename=file.filename,
        from_lang=from_lang,
        to_lang=to_lang,
        tier=tier,
        user_id=effective_user_id,
        client_ip=client_ip
    )

    return {
        "task_id": task_id,
        "status": "QUEUED",
        "message": "Traduction prise en charge avec succes."
    }


@app.get("/api/status/{task_id}", response_model=TranslationTaskStatus)
def get_task_status(task_id: str):
    if task_id not in TASKS:
        raise HTTPException(status_code=404, detail="Tache introuvable.")
    return TASKS[task_id]


@app.get("/api/download/{task_id}")
def download_translated_pdf(task_id: str):
    if task_id not in TASKS:
        raise HTTPException(status_code=404, detail="Tache introuvable.")
    task = TASKS[task_id]
    if task.status != "COMPLETED":
        raise HTTPException(status_code=400, detail="Traduction non encore terminee.")

    output_filename = f"{task_id}_{task.target_lang}.pdf"
    output_path = os.path.join(TRANSLATED_DIR, output_filename)
    if not os.path.exists(output_path):
        raise HTTPException(status_code=404, detail="Fichier traduit introuvable sur le serveur.")

    clean_name = f"traduit_{task.filename}"
    return FileResponse(
        output_path,
        media_type="application/pdf",
        filename=clean_name
    )
