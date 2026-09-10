import io
import fitz
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import UserTier
from backend.database import db_service
from backend.shields import circuit_breaker, anti_abus_shield, apply_freemium_watermark

client = TestClient(app)

def create_dummy_pdf(num_pages: int) -> bytes:
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 50), f"Page {i+1} test content. Fig. 1.{i+1} Sample.")
    b = doc.tobytes()
    doc.close()
    return b

print("=== [TEST 1] VERIFICATION DU HEALTHCHECK ET LANGUES ===")
res = client.get("/")
assert res.status_code == 200
print(" Root API:", res.json())

res_lang = client.get("/api/languages")
assert res_lang.status_code == 200
assert len(res_lang.json()) >= 10
print(f" Langues disponibles : {len(res_lang.json())} langues répertoriées.")

print("\n=== [TEST 2] TEST DU DIAGNOSTIC QUOTE & REGLES DES 5 PALIERS ===")

# 2.1 Anonyme avec 3 pages -> APPROVED (gratuit, cpu, filigrane)
pdf_3p = create_dummy_pdf(3)
res_quote = client.post("/api/quote", files={"file": ("test3.pdf", pdf_3p, "application/pdf")})
assert res_quote.status_code == 200
data = res_quote.json()
print(" 3 pages Anonyme ->", data["status"], "| Device:", data["device_assigned"], "| Filigrane:", data["watermark_applied"])
assert data["status"] == "APPROVED"
assert data["device_assigned"] == "cpu"
assert data["watermark_applied"] is True

# 2.2 Anonyme avec 7 pages -> UPGRADE_REQUIRED (doit proposer Free)
pdf_7p = create_dummy_pdf(7)
res_quote = client.post("/api/quote", files={"file": ("test7.pdf", pdf_7p, "application/pdf")})
data = res_quote.json()
print(" 7 pages Anonyme ->", data["status"], "| Suggéré:", data["suggested_tier"], "| Msg:", data["message"][:60])
assert data["status"] == "UPGRADE_REQUIRED"
assert data["suggested_tier"] == "FREE"

# 2.3 Compte Gratuit avec 7 pages -> APPROVED (max 10 pages)
user_free = "user_free_123"
db_service.create_or_update_user(user_free, "free@example.com", UserTier.FREE)
res_quote = client.post("/api/quote", files={"file": ("test7.pdf", pdf_7p, "application/pdf")}, data={"user_id": user_free})
data = res_quote.json()
print(" 7 pages Compte Gratuit ->", data["status"], "| Can translate:", data["can_translate"])
assert data["status"] == "APPROVED"

# 2.4 Compte Gratuit avec 15 pages -> UPGRADE_REQUIRED (doit proposer Starter)
pdf_15p = create_dummy_pdf(15)
res_quote = client.post("/api/quote", files={"file": ("test15.pdf", pdf_15p, "application/pdf")}, data={"user_id": user_free})
data = res_quote.json()
print(" 15 pages Compte Gratuit ->", data["status"], "| Suggéré:", data["suggested_tier"])
assert data["status"] == "UPGRADE_REQUIRED"
assert data["suggested_tier"] == "STARTER"

# 2.5 Compte Starter avec 15 pages -> APPROVED (GPU, pas de filigrane)
user_starter = "user_starter_456"
db_service.create_or_update_user(user_starter, "starter@example.com", UserTier.STARTER)
res_quote = client.post("/api/quote", files={"file": ("test15.pdf", pdf_15p, "application/pdf")}, data={"user_id": user_starter})
data = res_quote.json()
print(" 15 pages Starter ->", data["status"], "| Device:", data["device_assigned"], "| Filigrane:", data["watermark_applied"])
assert data["status"] == "APPROVED"
assert data["device_assigned"] == "cuda"
assert data["watermark_applied"] is False

# 2.6 Compte Starter avec 25 pages -> UPGRADE_REQUIRED (doit proposer Pro)
pdf_25p = create_dummy_pdf(25)
res_quote = client.post("/api/quote", files={"file": ("test25.pdf", pdf_25p, "application/pdf")}, data={"user_id": user_starter})
data = res_quote.json()
print(" 25 pages Starter ->", data["status"], "| Suggéré:", data["suggested_tier"])
assert data["status"] == "UPGRADE_REQUIRED"
assert data["suggested_tier"] == "PRO"

# 2.7 Compte Pro avec 35 pages -> APPROVED (inclus sans surcoût)
user_pro = "user_pro_789"
db_service.create_or_update_user(user_pro, "pro@example.com", UserTier.PRO)
res_quote = client.post("/api/quote", files={"file": ("test35.pdf", pdf_25p, "application/pdf")}, data={"user_id": user_pro})
data = res_quote.json()
print(" 25 pages Pro ->", data["status"], "| Extra fee:", data["extra_fee_usd"])
assert data["status"] == "APPROVED"
assert data["extra_fee_usd"] == 0.0

# 2.8 Compte Pro avec 65 pages -> APPROVED (+0.99$ surcoût)
pdf_65p = create_dummy_pdf(65)
res_quote = client.post("/api/quote", files={"file": ("test65.pdf", pdf_65p, "application/pdf")}, data={"user_id": user_pro})
data = res_quote.json()
print(" 65 pages Pro ->", data["status"], "| Extra fee:", data["extra_fee_usd"], "$ | Msg:", data["message"][:60])
assert data["status"] == "APPROVED"
assert data["extra_fee_usd"] == 0.99

# 2.9 Document > 100 pages (110 pages) -> REJECTED_TOO_LARGE
pdf_110p = create_dummy_pdf(110)
res_quote = client.post("/api/quote", files={"file": ("test110.pdf", pdf_110p, "application/pdf")}, data={"user_id": user_pro})
data = res_quote.json()
print(" 110 pages (tout compte) ->", data["status"], "| Can translate:", data["can_translate"])
assert data["status"] == "REJECTED_TOO_LARGE"
assert data["can_translate"] is False

print("\n=== [TEST 3] TEST DU CIRCUIT BREAKER & ANTI-ABUS ===")
cb_status = client.get("/api/shields/status").json()
print(" État Disjoncteur Global :", cb_status)
assert cb_status["is_tripped"] is False

print("\n=== [TEST 4] TEST DU FILIGRANE VIRAL (BOUCLIER 5) ===")
sample_pdf = create_dummy_pdf(1)
with open("test_sample_watermark.pdf", "wb") as f:
    f.write(sample_pdf)
apply_freemium_watermark("test_sample_watermark.pdf")
doc_wm = fitz.open("test_sample_watermark.pdf")
page_text = doc_wm[0].get_text()
doc_wm.close()
assert "www.translate-for-pdf.com" in page_text
print(" Filigrane viral injecté avec succès :", [l for l in page_text.splitlines() if "translate-for-pdf" in l][0])

print("\n=======================================================")
print(" TOUS LES TESTS DES 5 BOUCLIERS ET DE L'API ONT REUSSI AVEC SUCCES !")
print("=======================================================")
