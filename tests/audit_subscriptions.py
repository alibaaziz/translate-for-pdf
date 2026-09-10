import sys
import os
sys.path.insert(0, os.getcwd())

import httpx
import sqlite3
from backend.config import TIER_RULES, UserTier

print("=== 1. REGLES DES OFFRES & ABONNEMENTS DEFINIES ===")
for tier, rules in TIER_RULES.items():
    wm = "OUI (Viral)" if rules.get("watermark_required") else "NON (0 filigrane)"
    p_ceil = rules.get("max_pages_ceiling", rules.get("max_pages"))
    daily = rules.get("daily_docs", "N/A")
    monthly = rules.get("monthly_docs", "N/A")
    price = rules.get("price_monthly_usd", 0.00)
    dev = rules.get("hardware_device", "cpu").upper()
    print(f"Plan: {tier.value}")
    print(f"  - Pages max/doc: {rules.get('max_pages')} pages (Plafond max: {p_ceil} pages)")
    print(f"  - Quota documents: {daily} doc/jour | {monthly} docs/mois")
    print(f"  - Matériel de calcul: {dev}")
    print(f"  - Filigrane de sécurité: {wm}")
    print(f"  - Prix: {price} $/mois")
    print()

print("=== 2. PROFILS ENREGISTRES DANS SUPABASE CLOUD ===")
url = os.environ.get("SUPABASE_URL", "https://bosfcjbtansaqldgsmfd.supabase.co")
service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
try:
    r = httpx.get(f"{url}/rest/v1/profiles?select=*", headers=headers)
    profiles = r.json()
    print(f"Nombre total de profils dans Supabase: {len(profiles)}")
    for p in profiles:
        print(f" - ID: {p['id']} | Email: {p['email']} | Plan: {p['plan_tier']} | Stripe: {p.get('stripe_subscription_id') or 'Aucun (Non payant)'}")
except Exception as e:
    print("Erreur Supabase:", e)

print("\n=== 3. PROFILS ENREGISTRES EN BASE LOCALE SQLITE ===")
conn = sqlite3.connect("backend/local_dev.db")
c = conn.cursor()
c.execute("SELECT id, email, plan_tier FROM profiles")
rows = c.fetchall()
print(f"Nombre total de profils en local: {len(rows)}")
for r in rows:
    print(f" - ID: {r[0]} | Email: {r[1]} | Plan: {r[2]}")
