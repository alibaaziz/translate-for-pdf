import os
import sqlite3
import hashlib
import secrets
import uuid
import httpx
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from backend.config import UserTier, BACKEND_DIR, SUPABASE_URL, SUPABASE_KEY, SUPABASE_ANON_KEY

DB_PATH = os.path.join(BACKEND_DIR, "local_dev.db")


def init_local_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE,
            password_hash TEXT,
            salt TEXT,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE,
            plan_tier TEXT DEFAULT 'FREE',
            stripe_customer_id TEXT,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_usage (
            user_id TEXT,
            usage_date TEXT,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, usage_date)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS monthly_usage (
            user_id TEXT,
            month_key TEXT,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, month_key)
        )
    """)
    conn.commit()
    conn.close()


init_local_db()


def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000
    ).hex()
    return pwd_hash, salt


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    computed_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(computed_hash, expected_hash)


class DatabaseService:
    def __init__(self):
        self.db_path = DB_PATH
        self.supabase_url = SUPABASE_URL.rstrip("/") if SUPABASE_URL else ""
        self.supabase_key = SUPABASE_KEY
        self.supabase_anon_key = SUPABASE_ANON_KEY

    def is_supabase_active(self) -> bool:
        return bool(self.supabase_url and (self.supabase_anon_key or self.supabase_key))

    # 1. Accounts & Authentication
    def register_account(self, email: str, password: str, plan_tier: UserTier = UserTier.FREE) -> Dict[str, Any]:
        email_clean = email.strip().lower()
        now = datetime.now(timezone.utc).isoformat()
        user_id = str(uuid.uuid4())
        confirmation_sent = False

        # Si Supabase Auth est configuré, création du compte dans Supabase GoTrue
        if self.is_supabase_active():
            api_key = self.supabase_anon_key or self.supabase_key
            try:
                signup_res = httpx.post(
                    f"{self.supabase_url}/auth/v1/signup",
                    headers={"apikey": api_key, "Content-Type": "application/json"},
                    json={"email": email_clean, "password": password},
                    timeout=8.0
                )
                if signup_res.status_code >= 400:
                    err_json = signup_res.json()
                    msg = err_json.get("msg") or err_json.get("error_description") or "Erreur lors de l'inscription Supabase."
                    if "already registered" in msg.lower():
                        raise ValueError("Un compte existe déjà avec cette adresse email.")

                    # Si le quota d'emails par défaut de Supabase (3-4/heure) est dépassé,
                    # création instantanée du compte via l'API Admin Supabase avec service_role
                    if "rate limit" in msg.lower() and self.supabase_key:
                        print("[Supabase Auth] Limite email par défaut atteinte -> Création instantanée via Admin API Supabase...")
                        admin_headers = {
                            "apikey": self.supabase_key,
                            "Authorization": f"Bearer {self.supabase_key}",
                            "Content-Type": "application/json"
                        }
                        admin_res = httpx.post(
                            f"{self.supabase_url}/auth/v1/admin/users",
                            headers=admin_headers,
                            json={"email": email_clean, "password": password, "email_confirm": True},
                            timeout=8.0
                        )
                        if admin_res.status_code in (200, 201):
                            admin_data = admin_res.json()
                            user_id = admin_data.get("id", user_id)
                            confirmation_sent = False
                        else:
                            raise ValueError(msg)
                    else:
                        raise ValueError(msg)
                else:
                    sb_data = signup_res.json()
                    sb_user = sb_data.get("user") or sb_data
                    if sb_user and "id" in sb_user:
                        user_id = sb_user["id"]
                        if "confirmation_sent_at" in sb_user or not sb_data.get("access_token"):
                            confirmation_sent = True
            except ValueError:
                raise
            except Exception as e:
                print(f"[Supabase Auth] Erreur d appel : {e}, bascule sur la base locale.")

        pwd_hash, salt = hash_password(password)

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT id FROM accounts WHERE email = ?", (email_clean,))
        if c.fetchone():
            conn.close()
            raise ValueError("Un compte existe déjà avec cette adresse email.")

        c.execute("""
            INSERT INTO accounts (id, email, password_hash, salt, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, email_clean, pwd_hash, salt, now))

        c.execute("""
            INSERT INTO profiles (id, email, plan_tier, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET plan_tier = excluded.plan_tier
        """, (user_id, email_clean, plan_tier.value, now))
        conn.commit()
        conn.close()

        # Si Supabase REST est actif, synchroniser aussi la table profiles
        if self.is_supabase_active() and self.supabase_key:
            try:
                headers = {
                    "apikey": self.supabase_key,
                    "Authorization": f"Bearer {self.supabase_key}",
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates"
                }
                httpx.post(
                    f"{self.supabase_url}/rest/v1/profiles",
                    headers=headers,
                    json={"id": user_id, "email": email_clean, "plan_tier": plan_tier.value},
                    timeout=3.0
                )
            except Exception as e:
                print(f"[Supabase Sync Profiles] Avertissement: {e}")

        return {
            "user_id": user_id,
            "email": email_clean,
            "plan_tier": plan_tier,
            "confirmation_sent": confirmation_sent
        }

    def authenticate_account(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        email_clean = email.strip().lower()

        # Si Supabase Auth est actif, authentification via Supabase GoTrue
        if self.is_supabase_active():
            api_key = self.supabase_anon_key or self.supabase_key
            try:
                login_res = httpx.post(
                    f"{self.supabase_url}/auth/v1/token?grant_type=password",
                    headers={"apikey": api_key, "Content-Type": "application/json"},
                    json={"email": email_clean, "password": password},
                    timeout=8.0
                )
                if login_res.status_code == 200:
                    token_data = login_res.json()
                    user_info = token_data.get("user", {})
                    uid = user_info.get("id")
                    profile = self.get_user_profile(uid)
                    return {
                        "user_id": uid,
                        "email": email_clean,
                        "plan_tier": profile.get("plan_tier", UserTier.FREE),
                        "access_token": token_data.get("access_token")
                    }
                else:
                    err_json = login_res.json()
                    err_detail = err_json.get("error_description") or err_json.get("msg") or ""
                    if "email not confirmed" in err_detail.lower():
                        raise ValueError("Veuillez confirmer votre adresse email avant de vous connecter (vérifiez votre boîte de réception).")
            except ValueError:
                raise
            except Exception as e:
                print(f"[Supabase Auth Login] Erreur : {e}, tentative sur base locale.")

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT a.id, a.email, a.password_hash, a.salt, p.plan_tier FROM accounts a JOIN profiles p ON a.id = p.id WHERE a.email = ?", (email_clean,))
        row = c.fetchone()
        conn.close()

        if not row:
            return None

        uid, uemail, pwd_hash, salt, plan_tier_str = row
        if not verify_password(password, salt, pwd_hash):
            return None

        return {
            "user_id": uid,
            "email": uemail,
            "plan_tier": UserTier(plan_tier_str)
        }

    # 2. Profiles
    def get_user_profile(self, user_id: str) -> dict:
        if self.is_supabase_active() and self.supabase_key:
            try:
                headers = {"apikey": self.supabase_key, "Authorization": f"Bearer {self.supabase_key}"}
                r = httpx.get(f"{self.supabase_url}/rest/v1/profiles?id=eq.{user_id}&select=id,email,plan_tier", headers=headers, timeout=3.0)
                if r.status_code == 200 and r.json():
                    p = r.json()[0]
                    return {"user_id": p["id"], "email": p["email"], "plan_tier": UserTier(p["plan_tier"])}
            except Exception as e:
                print(f"[Supabase get_user_profile error] {e}")

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT id, email, plan_tier FROM profiles WHERE id = ?", (user_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return {"user_id": row[0], "email": row[1], "plan_tier": UserTier(row[2])}
        return {"user_id": user_id, "email": f"{user_id}@example.com", "plan_tier": UserTier.FREE}

    def create_or_update_user(self, user_id: str, email: str, plan_tier: UserTier):
        if self.is_supabase_active() and self.supabase_key:
            try:
                headers = {
                    "apikey": self.supabase_key,
                    "Authorization": f"Bearer {self.supabase_key}",
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates"
                }
                httpx.post(
                    f"{self.supabase_url}/rest/v1/profiles",
                    headers=headers,
                    json={"id": user_id, "email": email, "plan_tier": plan_tier.value},
                    timeout=3.0
                )
            except Exception as e:
                print(f"[Supabase create_or_update_user error] {e}")

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        c.execute("""
            INSERT INTO profiles (id, email, plan_tier, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET plan_tier = excluded.plan_tier, email = excluded.email
        """, (user_id, email, plan_tier.value, now))
        conn.commit()
        conn.close()

    # 3. Usage & Quotas
    def get_daily_usage(self, user_id: str) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.is_supabase_active() and self.supabase_key:
            try:
                headers = {"apikey": self.supabase_key, "Authorization": f"Bearer {self.supabase_key}"}
                r = httpx.get(f"{self.supabase_url}/rest/v1/daily_usage?user_id=eq.{user_id}&usage_date=eq.{today}&select=count", headers=headers, timeout=3.0)
                if r.status_code == 200 and r.json():
                    return r.json()[0]["count"]
                return 0
            except Exception as e:
                print(f"[Supabase get_daily_usage error] {e}")

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT count FROM daily_usage WHERE user_id = ? AND usage_date = ?", (user_id, today))
        row = c.fetchone()
        conn.close()
        return row[0] if row else 0

    def increment_daily_usage(self, user_id: str):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.is_supabase_active() and self.supabase_key:
            try:
                headers = {
                    "apikey": self.supabase_key,
                    "Authorization": f"Bearer {self.supabase_key}",
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates"
                }
                cur = self.get_daily_usage(user_id)
                httpx.post(f"{self.supabase_url}/rest/v1/daily_usage", headers=headers, json={"user_id": user_id, "usage_date": today, "count": cur + 1}, timeout=3.0)
            except Exception as e:
                print(f"[Supabase increment_daily_usage error] {e}")

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            INSERT INTO daily_usage (user_id, usage_date, count)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, usage_date) DO UPDATE SET count = count + 1
        """, (user_id, today))
        conn.commit()
        conn.close()

    def get_monthly_usage(self, user_id: str) -> int:
        month_key = datetime.now(timezone.utc).strftime("%Y-%m")
        if self.is_supabase_active() and self.supabase_key:
            try:
                headers = {"apikey": self.supabase_key, "Authorization": f"Bearer {self.supabase_key}"}
                r = httpx.get(f"{self.supabase_url}/rest/v1/monthly_usage?user_id=eq.{user_id}&month_key=eq.{month_key}&select=count", headers=headers, timeout=3.0)
                if r.status_code == 200 and r.json():
                    return r.json()[0]["count"]
                return 0
            except Exception as e:
                print(f"[Supabase get_monthly_usage error] {e}")

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT count FROM monthly_usage WHERE user_id = ? AND month_key = ?", (user_id, month_key))
        row = c.fetchone()
        conn.close()
        return row[0] if row else 0

    def increment_monthly_usage(self, user_id: str):
        month_key = datetime.now(timezone.utc).strftime("%Y-%m")
        if self.is_supabase_active() and self.supabase_key:
            try:
                headers = {
                    "apikey": self.supabase_key,
                    "Authorization": f"Bearer {self.supabase_key}",
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates"
                }
                cur = self.get_monthly_usage(user_id)
                httpx.post(f"{self.supabase_url}/rest/v1/monthly_usage", headers=headers, json={"user_id": user_id, "month_key": month_key, "count": cur + 1}, timeout=3.0)
            except Exception as e:
                print(f"[Supabase increment_monthly_usage error] {e}")

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            INSERT INTO monthly_usage (user_id, month_key, count)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, month_key) DO UPDATE SET count = count + 1
        """, (user_id, month_key))
        conn.commit()
        conn.close()

    def get_quota_summary(self, user_id: str) -> Dict[str, Any]:
        profile = self.get_user_profile(user_id)
        tier = profile["plan_tier"]
        daily_used = self.get_daily_usage(user_id)
        monthly_used = self.get_monthly_usage(user_id)

        daily_limit = 2 if tier == UserTier.FREE else (10 if tier == UserTier.PRO else None)
        monthly_limit = 150 if tier == UserTier.STARTER else None

        daily_remaining = max(0, daily_limit - daily_used) if daily_limit is not None else None
        monthly_remaining = max(0, monthly_limit - monthly_used) if monthly_limit is not None else None

        return {
            "user_id": user_id,
            "email": profile["email"],
            "plan_tier": tier.value,
            "daily_used": daily_used,
            "daily_limit": daily_limit,
            "daily_remaining": daily_remaining,
            "monthly_used": monthly_used,
            "monthly_limit": monthly_limit,
            "monthly_remaining": monthly_remaining
        }


db_service = DatabaseService()
