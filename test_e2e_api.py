import time
import fitz
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

# Créer un PDF de test simple de 2 pages
doc = fitz.open()
p1 = doc.new_page(width=595, height=842)
p1.insert_text((60, 100), "Chapter 1. Tunnel Excavation Dynamics and Rock Mechanics.", fontsize=12)
p1.insert_text((60, 150), "Fig. 1.1", fontsize=10)
p1.insert_text((60, 200), "The surrounding ground behaves elastically under moderate overburden pressure.", fontsize=11)

p2 = doc.new_page(width=595, height=842)
p2.insert_text((60, 100), "Chapter 2. Convergence and deformation response.", fontsize=12)
p2.insert_text((60, 150), "Fig. 2.1", fontsize=10)
p2.insert_text((60, 200), "The face stability is maintained through shotcrete and steel arches.", fontsize=11)

pdf_bytes = doc.tobytes()
doc.close()

print("=== [TEST END-TO-END] LANCEMENT D UNE TRADUCTION VIA L'API ===")
# 1. Envoi de la requête de traduction
res = client.post(
    "/api/translate",
    files={"file": ("test_e2e.pdf", pdf_bytes, "application/pdf")},
    data={"from_lang": "en", "to_lang": "fr"}
)
assert res.status_code == 200
task_id = res.json()["task_id"]
print(f" Tâche créée avec succès ! ID: {task_id}")

# 2. Attente de la fin du traitement en tâche de fond
max_wait = 30
start = time.time()
while time.time() - start < max_wait:
    res_status = client.get(f"/api/status/{task_id}")
    status_data = res_status.json()
    print(f"   Progression: {status_data['progress_percent']}% | Statut: {status_data['status']} | Msg: {status_data['message']}")
    if status_data["status"] in ("COMPLETED", "FAILED"):
        break
    time.sleep(2)

assert status_data["status"] == "COMPLETED"
print(" Traduction terminée avec succès !")

# 3. Téléchargement du PDF traduit
res_dl = client.get(f"/api/download/{task_id}")
assert res_dl.status_code == 200
assert len(res_dl.content) > 1000

# 4. Vérification du contenu du PDF traduit
doc_out = fitz.open(stream=res_dl.content, filetype="pdf")
text_p1 = doc_out[0].get_text()
text_p2 = doc_out[1].get_text()
doc_out.close()

print("\n--- Contenu Page 1 traduite ---")
print(text_p1.strip())
assert "Fig. 1.1" in text_p1
assert "www.translate-for-pdf.com" in text_p1 # Filigrane gratuit présent

print("\n--- Contenu Page 2 traduite ---")
print(text_p2.strip())
assert "Fig. 2.1" in text_p2

print("\n=======================================================")
print(" VERIFICATION INTEGRALE VALIDEE : FIG PRESERVEES + FILIGRANE + API ACTIVE !")
print("=======================================================")
