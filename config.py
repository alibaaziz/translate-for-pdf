import os
import sys

# Determine application directories
if getattr(sys, "frozen", False):
    APP_ROOT = os.path.dirname(sys.executable)
    BUNDLE_DIR = getattr(sys, "_MEIPASS", APP_ROOT)
else:
    APP_ROOT = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = APP_ROOT

# Supported languages for the dropdowns
# (ISO 639-1 code, Display Name in French)
SUPPORTED_LANGUAGES = [
    ("en", "Anglais (English)"),
    ("fr", "Français"),
    ("es", "Espagnol (Español)"),
    ("de", "Allemand (Deutsch)"),
    ("it", "Italien (Italiano)"),
    ("pt", "Portugais (Português)"),
    ("ru", "Russe (Русский)"),
    ("zh", "Chinois (中文 - Simplifié)"),
    ("ja", "Japonais (日本語)"),
    ("ar", "Arabe (العربية)"),
    ("nl", "Néerlandais (Nederlands)"),
    ("pl", "Polonais (Polski)"),
    ("tr", "Turc (Türkçe)"),
    ("hi", "Hindi (हिन्दी)"),
]

LANGUAGE_CODE_TO_NAME = {code: name for code, name in SUPPORTED_LANGUAGES}
LANGUAGE_NAME_TO_CODE = {name: code for code, name in SUPPORTED_LANGUAGES}

# Fonts on Windows
WINDOWS_FONTS_DIR = os.environ.get("WINDIR", "C:\\Windows") + "\\Fonts"

SYSTEM_FONTS = {
    "default": os.path.join(WINDOWS_FONTS_DIR, "arial.ttf"),
    "sans": os.path.join(WINDOWS_FONTS_DIR, "arial.ttf"),
    "serif": os.path.join(WINDOWS_FONTS_DIR, "times.ttf"),
    "mono": os.path.join(WINDOWS_FONTS_DIR, "cour.ttf"),
    "chinese": os.path.join(WINDOWS_FONTS_DIR, "msyh.ttc"),
    "segoe": os.path.join(WINDOWS_FONTS_DIR, "segoeui.ttf"),
}

# NLLB-200 Language Codes (FLORES-200)
ISO_TO_NLLB = {
    "en": "eng_Latn",
    "fr": "fra_Latn",
    "es": "spa_Latn",
    "de": "deu_Latn",
    "it": "ita_Latn",
    "pt": "por_Latn",
    "ru": "rus_Cyrl",
    "zh": "zho_Hans",
    "ja": "jpn_Jpan",
    "ar": "arb_Arab",
    "nl": "nld_Latn",
    "pl": "pol_Latn",
    "tr": "tur_Latn",
    "hi": "hin_Deva",
}

NLLB_MODEL_REPO = "JustFrederik/nllb-200-distilled-600M-ct2-int8"

# Robust model location resolution:
# 1. Look next to executable in models/nllb-200-int8
# 2. Look in PyInstaller internal bundle directory (_MEIPASS)
# 3. Look in user local cache ~/.pdf_translator_offline/models/nllb-200-int8
EXE_MODELS_DIR = os.path.join(APP_ROOT, "models", "nllb-200-int8")
BUNDLE_MODELS_DIR = os.path.join(BUNDLE_DIR, "models", "nllb-200-int8")
USER_MODELS_DIR = os.path.join(os.path.expanduser("~"), ".pdf_translator_offline", "models", "nllb-200-int8")

if os.path.exists(os.path.join(EXE_MODELS_DIR, "model.bin")):
    NLLB_LOCAL_DIR = EXE_MODELS_DIR
elif os.path.exists(os.path.join(BUNDLE_MODELS_DIR, "model.bin")):
    NLLB_LOCAL_DIR = BUNDLE_MODELS_DIR
elif os.path.exists(os.path.join(USER_MODELS_DIR, "model.bin")):
    NLLB_LOCAL_DIR = USER_MODELS_DIR
else:
    NLLB_LOCAL_DIR = EXE_MODELS_DIR
