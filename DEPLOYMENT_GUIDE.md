# Guide de Déploiement Cloud 100% Gratuit - translate-for-pdf.com

Ce guide vous explique comment mettre en ligne votre plateforme SaaS **gratuitement à vie** avec **16 Go de RAM** pour faire tourner le moteur d'IA NLLB-200 et la connecter à votre domaine personnalisé.

---

## Option Recommandée : Hugging Face Spaces (Docker)

Hugging Face Spaces est la seule plateforme au monde qui offre **16 Go de RAM**, **2 vCPU** et un certificat **SSL / HTTPS automatique** gratuitement sans exiger de carte bancaire.

### Étape 1 : Créer un Space sur Hugging Face

1. Rendez-vous sur [huggingface.co](https://huggingface.co) et créez un compte gratuit (ou connectez-vous).
2. Cliquez sur votre profil en haut à droite > **New Space** :
   - **Space name :** `translate-for-pdf`
   - **License :** `mit` ou `apache-2.0`
   - **Select the Space SDK :** Choisissez **Docker** > **Blank**
   - **Space hardware :** Laissez **CPU basic (2 vCPU · 16 GB RAM) - FREE**
   - **Public / Private :** Choisissez **Public**
3. Cliquez sur **Create Space**.

### Étape 2 : Configurer les Variables d'Environnement (.env) dans le Space

Dans votre Space sur Hugging Face :
1. Allez dans l'onglet **Settings** > descendez à la section **Variables and secrets** > **New secret** :
2. Ajoutez les variables suivantes (celles de votre fichier `.env`) :
   - `SUPABASE_URL` = `https://bosfcjbtansaqldgsmfd.supabase.co`
   - `SUPABASE_ANON_KEY` = `votre_cle_anon`
   - `SUPABASE_SERVICE_ROLE_KEY` = `votre_cle_service_role`
   - `STRIPE_PUBLISHABLE_KEY` = `pk_test_...`
   - `STRIPE_SECRET_KEY` = `sk_test_...`
   - `STRIPE_PRICE_ID_STARTER` = `price_1UEAsiAhvgYRx74KUxlwaX10`
   - `STRIPE_PRICE_ID_PRO` = `price_1UEAtFAhvgYRx74KNepTgvzH`

### Étape 3 : Pousser le Code vers le Space

Vous pouvez soit utiliser Git en ligne de commande :
```bash
git remote add space https://huggingface.co/spaces/VOTRE_USERNAME/translate-for-pdf
git push --force space main
```
Ou simplement glisser-déposer les fichiers du projet directement dans l'onglet **Files** de votre Space !

Hugging Face va automatiquement lire le `Dockerfile`, construire l'image, installer les dépendances et démarrer votre SaaS. En 3 minutes, votre site sera en ligne avec son URL publique sécurisée en `https://` !

---

## Connecter votre Nom de Domaine Personnalisé (www.translate-for-pdf.com)

1. Chez votre registrar (Hostinger, Namecheap, OVH, Cloudflare...) :
   - Créez un enregistrement **CNAME** :
     - **Nom :** `www`
     - **Cible :** l'URL de votre Space (ex: `votre-username-translate-for-pdf.hf.space`)
2. Ou via **Cloudflare** (Gratuit) :
   - Redirigez `translate-for-pdf.com` vers l'application avec SSL automatique et protection anti-DDoS.

---

## Configuration du Webhook Stripe en Production

Dès que votre site est en ligne :
1. Allez sur votre tableau de bord **Stripe** > **Développeurs** > **Webhooks**.
2. Cliquez sur **Ajouter une destination** :
   - **URL du endpoint :** `https://votre-site.com/api/stripe/webhook`
   - **Événements à écouter :**
     - `checkout.session.completed`
     - `invoice.payment_succeeded`
     - `customer.subscription.deleted`
3. Stripe vous donne un **Secret de signature** (`whsec_...`).
4. Ajoutez `STRIPE_WEBHOOK_SECRET=whsec_...` dans vos secrets Hugging Face !
