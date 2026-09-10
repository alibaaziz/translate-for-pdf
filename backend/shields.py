import os
import time
import hashlib
from datetime import datetime, timezone
import fitz  # PyMuPDF

from backend.config import (
    UserTier, TIER_RULES, GLOBAL_DAILY_FREE_DOC_LIMIT, WATERMARK_TEXT
)

# -------------------------------------------------------------
# BOUCLIER 1 : ROUTAGE MATERIEL INTELLIGENT (CPU vs GPU)
# -------------------------------------------------------------
def get_hardware_device_for_tier(tier: UserTier, system_has_cuda: bool = True) -> str:
    requested = TIER_RULES.get(tier, {}).get("hardware_device", "cpu")
    if requested == "cuda" and system_has_cuda:
        return "cuda"
    return "cpu"


# -------------------------------------------------------------
# BOUCLIER 2 : LE DISJONCTEUR GLOBAL (CIRCUIT BREAKER)
# -------------------------------------------------------------
class CircuitBreaker:
    def __init__(self, daily_limit: int = GLOBAL_DAILY_FREE_DOC_LIMIT):
        self.daily_limit = daily_limit
        self.current_date = datetime.now(timezone.utc).date()
        self.free_docs_today = 0

    def _check_and_reset_if_new_day(self):
        today = datetime.now(timezone.utc).date()
        if today != self.current_date:
            self.current_date = today
            self.free_docs_today = 0

    def can_process_free(self) -> tuple[bool, str]:
        self._check_and_reset_if_new_day()
        if self.free_docs_today >= self.daily_limit:
            return (
                False,
                f"Le quota gratuit communautaire du jour ({self.daily_limit} docs) a ete atteint pour proteger nos serveurs. "
                "Il sera reinitialise a minuit UTC, ou passez a Starter (4,99 $) pour traduire sans attendre !"
            )
        return (True, "")

    def record_free_usage(self):
        self._check_and_reset_if_new_day()
        self.free_docs_today += 1

    def get_status(self) -> dict:
        self._check_and_reset_if_new_day()
        return {
            "date": str(self.current_date),
            "free_docs_today": self.free_docs_today,
            "daily_limit": self.daily_limit,
            "quota_remaining": max(0, self.daily_limit - self.free_docs_today),
            "is_tripped": self.free_docs_today >= self.daily_limit
        }


circuit_breaker = CircuitBreaker()


# -------------------------------------------------------------
# BOUCLIER 3 : ANTI-ABUS, RATE-LIMITING IP & JETABLES
# -------------------------------------------------------------
DISPOSABLE_EMAIL_DOMAINS = {
    "yopmail.com", "yopmail.fr", "tempmail.com", "10minutemail.com",
    "guerrillamail.com", "mailinator.com", "throwawaymail.com",
    "sharklasers.com", "dispostable.com", "getnada.com", "mytemp.email"
}


class AntiAbusShield:
    def __init__(self):
        self.ip_usage = {}

    @staticmethod
    def hash_ip(ip: str) -> str:
        return hashlib.sha256(f"salt_translate_{ip}".encode()).hexdigest()[:16]

    def check_anonymous_ip(self, client_ip: str) -> tuple[bool, str]:
        ip_hash = self.hash_ip(client_ip)
        today = datetime.now(timezone.utc).date()

        if ip_hash in self.ip_usage:
            last_date, count = self.ip_usage[ip_hash]
            if last_date == today and count >= 1:
                return (
                    False,
                    "Vous avez deja utilise votre traduction anonyme gratuite aujourd hui (1 doc/jour). "
                    "Creez un compte gratuit en 10 secondes pour obtenir 2 documents par jour !"
                )
        return (True, "")

    def record_anonymous_ip(self, client_ip: str):
        ip_hash = self.hash_ip(client_ip)
        today = datetime.now(timezone.utc).date()
        count = self.ip_usage.get(ip_hash, (today, 0))[1] + 1 if self.ip_usage.get(ip_hash, (today, 0))[0] == today else 1
        self.ip_usage[ip_hash] = (today, count)

    @staticmethod
    def is_disposable_email(email: str) -> bool:
        if not email or "@" not in email:
            return False
        domain = email.split("@")[-1].strip().lower()
        return domain in DISPOSABLE_EMAIL_DOMAINS


anti_abus_shield = AntiAbusShield()


# -------------------------------------------------------------
# BOUCLIER 5 : LE FILIGRANE PUBLICITAIRE VIRAL
# -------------------------------------------------------------
def apply_freemium_watermark(pdf_path: str, output_path: str = None) -> str:
    target_path = output_path or pdf_path
    doc = fitz.open(pdf_path)

    for page in doc:
        rect = page.rect
        footer_rect = fitz.Rect(10, rect.height - 18, rect.width - 10, rect.height - 3)
        page.draw_rect(footer_rect, color=(0.85, 0.85, 0.85), fill=(0.97, 0.97, 0.98), width=0.5)
        page.insert_textbox(
            footer_rect,
            WATERMARK_TEXT,
            fontsize=7.0,
            fontname="helv",
            color=(0.4, 0.4, 0.45),
            align=fitz.TEXT_ALIGN_CENTER
        )

    if target_path == pdf_path:
        doc.saveIncr()
    else:
        doc.save(target_path, garbage=3, deflate=True)
    doc.close()
    return target_path
