import httpx
import sys

BASE_URL = "http://127.0.0.1:8000"

def test_auth_flow():
    print("=== TEST 1: Rejet email jetable (Bouclier 3) ===")
    r = httpx.post(f"{BASE_URL}/api/auth/register", json={
        "email": "hacker@tempmail.com",
        "password": "password123"
    })
    print(f"Status: {r.status_code}, Response: {r.json()}")
    assert r.status_code == 400, "Disposable email should be rejected!"
    assert "temporaires ou jetables" in r.json()["detail"]
    print("-> Test 1 PASS : Email jetable bloque !")

    print("\n=== TEST 2: Inscription d'un compte reel gratuit ===")
    import uuid
    unique_email = f"user_{uuid.uuid4().hex[:6]}@gmail.com"
    r = httpx.post(f"{BASE_URL}/api/auth/register", json={
        "email": unique_email,
        "password": "mypassword2026"
    })
    print(f"Status: {r.status_code}, Response: {r.json()}")
    assert r.status_code == 200, "Registration failed"
    data = r.json()
    token = data["token"]
    assert data["plan_tier"] == "FREE"
    print("-> Test 2 PASS : Compte cree avec succes !")

    print("\n=== TEST 3: Rejet des doublons ===")
    r_dup = httpx.post(f"{BASE_URL}/api/auth/register", json={
        "email": unique_email,
        "password": "anotherpassword"
    })
    print(f"Status: {r_dup.status_code}, Response: {r_dup.json()}")
    assert r_dup.status_code == 400
    print("-> Test 3 PASS : Doublon correctement bloque !")

    print("\n=== TEST 4: Connexion (Login) ===")
    r_login = httpx.post(f"{BASE_URL}/api/auth/login", json={
        "email": unique_email,
        "password": "mypassword2026"
    })
    print(f"Status: {r_login.status_code}, Response: {r_login.json()}")
    assert r_login.status_code == 200
    login_token = r_login.json()["token"]
    print("-> Test 4 PASS : Connexion valide avec jeton HMAC !")

    print("\n=== TEST 5: Verification de /api/auth/me ===")
    headers = {"Authorization": f"Bearer {login_token}"}
    r_me = httpx.get(f"{BASE_URL}/api/auth/me", headers=headers)
    print(f"Status: {r_me.status_code}, Response: {r_me.json()}")
    assert r_me.status_code == 200
    me_data = r_me.json()
    assert me_data["daily_limit"] == 2
    assert me_data["daily_remaining"] == 2
    print("-> Test 5 PASS : Quotas de compte gratuit (2 docs/jour) confirmes !")

    print("\n=== TOUS LES TESTS AUTH SONT REUSSIS AVEC SUCCES ===")

if __name__ == "__main__":
    try:
        test_auth_flow()
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
