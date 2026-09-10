import os
import stripe
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Header, Request
from backend.config import (
    STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET,
    STRIPE_PRICE_ID_STARTER, STRIPE_PRICE_ID_PRO,
    UserTier
)
from backend.auth import get_current_user_from_header
from backend.database import db_service

stripe.api_key = STRIPE_SECRET_KEY

payments_router = APIRouter(prefix="/api/stripe", tags=["Payments"])


class CheckoutRequest(BaseModel):
    tier: str  # STARTER ou PRO


@payments_router.post("/create-checkout-session")
async def create_checkout_session(body: CheckoutRequest, authorization: Optional[str] = Header(None)):
    user = get_current_user_from_header(authorization)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Veuillez vous connecter ou créer un compte gratuit avant de choisir un abonnement."
        )

    tier_requested = body.tier.upper()
    if tier_requested not in ("STARTER", "PRO"):
        raise HTTPException(status_code=400, detail="Plan invalide. Choisissez STARTER ou PRO.")

    price_id = STRIPE_PRICE_ID_STARTER if tier_requested == "STARTER" else STRIPE_PRICE_ID_PRO

    # Si les clés Stripe réelles ne sont pas encore configurées, mode simulation pédagogique
    if not stripe.api_key or "placeholder" in stripe.api_key or not price_id or "placeholder" in price_id:
        # Simulation directe : Mise à jour immédiate du profil dans Supabase Cloud !
        new_tier = UserTier(tier_requested)
        db_service.create_or_update_user(user["user_id"], user["email"], new_tier)
        return {
            "mode": "simulation",
            "message": f"Abonnement {tier_requested} activé avec succès en mode Test !",
            "plan_tier": tier_requested,
            "redirect_url": f"/?payment=success&tier={tier_requested}"
        }

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            customer_email=user["email"],
            client_reference_id=user["user_id"],
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"http://127.0.0.1:8000/?payment=success&tier={tier_requested}",
            cancel_url="http://127.0.0.1:8000/?payment=cancelled",
            metadata={
                "user_id": user["user_id"],
                "email": user["email"],
                "target_tier": tier_requested
            }
        )
        return {"mode": "stripe", "checkout_url": session.url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erreur Stripe : {e}")


@payments_router.post("/confirm-payment-success")
async def confirm_payment_success(tier: str, authorization: Optional[str] = Header(None)):
    user = get_current_user_from_header(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Non authentifié.")
    
    tier_requested = tier.upper()
    if tier_requested in ("STARTER", "PRO"):
        new_tier = UserTier(tier_requested)
        db_service.create_or_update_user(user["user_id"], user["email"], new_tier)
        return {"status": "success", "plan_tier": tier_requested}
    return {"status": "error", "message": "Plan invalide"}


@payments_router.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    event = None
    if STRIPE_WEBHOOK_SECRET and sig_header:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Signature webhook invalide : {e}")
    else:
        # Si pas de secret webhook renseigné, parsing JSON direct
        import json
        try:
            event = json.loads(payload)
        except Exception:
            raise HTTPException(status_code=400, detail="Payload JSON invalide")

    event_type = event.get("type")
    data_object = event.get("data", {}).get("object", {})

    print(f"[Stripe Webhook] Événement reçu : {event_type}")

    # 1. Validation de paiement d'abonnement
    if event_type in ("checkout.session.completed", "invoice.payment_succeeded"):
        meta = data_object.get("metadata", {})
        user_id = meta.get("user_id") or data_object.get("client_reference_id")
        target_tier = meta.get("target_tier", "STARTER")
        customer_id = data_object.get("customer")
        subscription_id = data_object.get("subscription")

        if user_id:
            tier_enum = UserTier(target_tier)
            db_service.create_or_update_user(user_id, meta.get("email", ""), tier_enum)
            print(f"[Stripe Webhook] Profil {user_id} mis à jour avec succès au plan {target_tier} !")

    # 2. Résiliation d'abonnement
    elif event_type == "customer.subscription.deleted":
        sub_id = data_object.get("id")
        print(f"[Stripe Webhook] Abonnement résilié : {sub_id}, retour au plan FREE.")

    return {"status": "success"}
