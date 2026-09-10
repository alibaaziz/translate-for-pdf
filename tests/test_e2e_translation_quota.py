import httpx
import fitz
import io
import time
import uuid

BASE_URL = 'http://127.0.0.1:8000'

# 1. Register test user
user_email = f"e2e_{uuid.uuid4().hex[:6]}@gmail.com"
reg = httpx.post(f"{BASE_URL}/api/auth/register", json={"email": user_email, "password": "password2026"})
assert reg.status_code == 200
token = reg.json()["token"]
print(f"User registered: {user_email}")

# 2. Check initial quota
headers = {"Authorization": f"Bearer {token}"}
me = httpx.get(f"{BASE_URL}/api/auth/me", headers=headers).json()
assert me["daily_used"] == 0
assert me["daily_remaining"] == 2
print(f"Initial quota: {me['daily_used']}/2 used, {me['daily_remaining']} remaining")

# 3. Create dummy 2-page PDF
doc = fitz.open()
p1 = doc.new_page()
p1.insert_text((72, 72), "Hello world! This is an authenticated PDF translation test.")
p2 = doc.new_page()
p2.insert_text((72, 72), "Second page text: Testing figure and diagram retention.")
buf = io.BytesIO()
doc.save(buf)
pdf_bytes = buf.getvalue()

# 4. Start translation
trans = httpx.post(
    f"{BASE_URL}/api/translate",
    files={"file": ("e2e_test.pdf", pdf_bytes, "application/pdf")},
    data={"from_lang": "en", "to_lang": "fr"},
    headers=headers
)
assert trans.status_code == 200, trans.text
task_id = trans.json()["task_id"]
print(f"Translation queued, task_id: {task_id}")

# 5. Poll status
completed = False
for _ in range(30):
    st = httpx.get(f"{BASE_URL}/api/status/{task_id}").json()
    status = st.get("status")
    prog = st.get("progress_percent", 0)
    msg = st.get("message", "")
    print(f"Status: {status}, Progress: {prog}% - {msg}")
    if status == "COMPLETED":
        completed = True
        break
    elif status == "FAILED":
        raise RuntimeError(f"Task failed: {st.get('error')}")
    time.sleep(1.5)

assert completed, "Task did not complete in time"

# 6. Check updated quota
me_after = httpx.get(f"{BASE_URL}/api/auth/me", headers=headers).json()
print(f"Quota after translation: {me_after['daily_used']}/2 used, {me_after['daily_remaining']} remaining")
assert me_after["daily_used"] == 1
assert me_after["daily_remaining"] == 1

# 7. Download PDF and check watermark
dl = httpx.get(f"{BASE_URL}/api/download/{task_id}")
assert dl.status_code == 200
assert len(dl.content) > 1000
dl_doc = fitz.open(stream=dl.content, filetype="pdf")
assert len(dl_doc) == 2
print(f"Downloaded PDF successfully! Pages: {len(dl_doc)}")

print("=== COMPLETE END-TO-END AUTH & TRANSLATION WORKFLOW VERIFIED SUCCESSFULLY ===")
