import os
from dotenv import load_dotenv

load_dotenv()
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')

# 1. Retrieve balance
bal = stripe.Balance.retrieve()
print("=== STRIPE BALANCE ===")
for b in bal["available"]:
    print(f"Disponible : {b['amount']/100} {b['currency'].upper()}")
for b in bal["pending"]:
    print(f"En attente : {b['amount']/100} {b['currency'].upper()}")

# 2. Retrieve recent charges
charges = stripe.Charge.list(limit=3)
print("\n=== DERNIERS PAIEMENTS ENREGISTRES SUR STRIPE ===")
for c in charges.data:
    email = c.billing_details.email if c.billing_details else "N/A"
    print(f"- Montant brut : {c.amount/100} {c.currency.upper()} | Statut : {c.status} | Client : {email}")

# 3. Retrieve subscriptions
subs = stripe.Subscription.list(limit=3)
print("\n=== DERNIERS ABONNEMENTS ACTIFS SUR STRIPE ===")
for s in subs.data:
    cust = stripe.Customer.retrieve(s.customer)
    print(f"- ID Abonnement : {s.id} | Statut : {s.status} | Client : {cust.email}")
