import os
from enum import Enum

# Base directories
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
STORAGE_DIR = os.path.join(BACKEND_DIR, 'storage')
UPLOADS_DIR = os.path.join(STORAGE_DIR, 'uploads')
TRANSLATED_DIR = os.path.join(STORAGE_DIR, 'translated')

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(TRANSLATED_DIR, exist_ok=True)


class UserTier(str, Enum):
    ANONYMOUS = 'ANONYMOUS'
    FREE = 'FREE'
    STARTER = 'STARTER'
    PRO = 'PRO'


# Business Rules & Quotas by Tier
TIER_RULES = {
    UserTier.ANONYMOUS: {
        'max_pages': 5,
        'daily_docs': 1,
        'monthly_docs': None,
        'hardware_device': 'cpu',     # Bouclier 1: CPU gratuit
        'watermark_required': True,    # Bouclier 5: Filigrane viral
        'priority': 0                  # Bouclier 4: Basse priorité
    },
    UserTier.FREE: {
        'max_pages': 10,
        'daily_docs': 2,
        'monthly_docs': None,
        'hardware_device': 'cpu',     # Bouclier 1: CPU gratuit
        'watermark_required': True,    # Bouclier 5: Filigrane viral
        'priority': 1                  # Bouclier 4: Priorité normale
    },
    UserTier.STARTER: {
        'max_pages': 20,
        'daily_docs': None,
        'monthly_docs': 150,
        'hardware_device': 'cuda',    # GPU haute performance
        'watermark_required': False,   # Zéro filigrane
        'priority': 2,                 # Prioritaire
        'price_monthly_usd': 4.99
    },
    UserTier.PRO: {
        'max_pages': 50,              # Inclus sans surcoût
        'max_pages_ceiling': 100,     # Plafond avec surcoût 0.99$
        'daily_docs': 10,             # Fair Use Policy (FUP) anti-abus
        'monthly_docs': None,         # Illimité
        'surcharge_over_50_pages_usd': 0.99,
        'hardware_device': 'cuda',    # GPU haute performance
        'watermark_required': False,   # Zéro filigrane
        'priority': 3,                 # Priorité maximale absolue
        'price_monthly_usd': 14.99
    }
}

# Plafond absolu plateforme (tout utilisateur confondu)
PLATFORM_ABSOLUTE_MAX_PAGES = 100

# Bouclier 2 : Disjoncteur Global (Circuit Breaker)
# Plafonne le nombre total de documents gratuits offerts quotidiennement sur toute la plateforme
GLOBAL_DAILY_FREE_DOC_LIMIT = 200

# Bouclier 5 : Texte du filigrane publicitaire viral
WATERMARK_TEXT = 'Traduit gratuitement sur www.translate-for-pdf.com - Obtenez vos documents sans filigrane avec Starter ou Pro'

# Rétention des fichiers
FILE_RETENTION_HOURS = 24

# Chargement automatique du fichier .env
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, '.env'))

# Supabase (Configurable via variables d environnement dans .env)
SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
SUPABASE_ANON_KEY = os.environ.get('SUPABASE_ANON_KEY', '')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', os.environ.get('SUPABASE_KEY', ''))

# Stripe Payments (Mode Test sandbox gratuit)
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
STRIPE_PRICE_ID_STARTER = os.environ.get('STRIPE_PRICE_ID_STARTER', '')
STRIPE_PRICE_ID_PRO = os.environ.get('STRIPE_PRICE_ID_PRO', '')

# Groq Cloud Translation (LPU ultra-haute vitesse Llama-3.3 70B & 3.1 8B)
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_MODEL = os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')

