import os
import sys
import uuid
import threading
from datetime import datetime, timezone
from typing import Dict

# Ensure project root is on sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from translator_engine import NllbTranslatorEngine
from pdf_processor import PdfProcessor
from backend.config import UserTier, TIER_RULES, UPLOADS_DIR, TRANSLATED_DIR
from backend.models import TranslationTaskStatus
from backend.shields import circuit_breaker, apply_freemium_watermark
from backend.database import db_service

# Global in-memory engine and task registry
_ENGINE_GPU = None
_ENGINE_CPU = None

def get_engine(device: str = 'cuda'):
    global _ENGINE_GPU, _ENGINE_CPU
    if device == 'cuda':
        if _ENGINE_GPU is None:
            _ENGINE_GPU = NllbTranslatorEngine()
            # If system doesn't have cuda, it automatically falls back
        return _ENGINE_GPU
    else:
        if _ENGINE_CPU is None:
            _ENGINE_CPU = NllbTranslatorEngine()
            _ENGINE_CPU.device = 'cpu'
            _ENGINE_CPU.compute_type = 'int8'
            _ENGINE_CPU.translator = None # force CPU load
        return _ENGINE_CPU

TASKS: Dict[str, TranslationTaskStatus] = {}

def execute_translation_job(task_id: str, input_path: str, output_path: str,
                            from_lang: str, to_lang: str,
                            tier: UserTier, user_id: str = None, client_ip: str = None):
    task = TASKS[task_id]
    task.status = 'PROCESSING'
    task.message = 'Initialisation du moteur de traduction...'

    tier_rule = TIER_RULES.get(tier, {})
    requested_device = tier_rule.get('hardware_device', 'cpu')
    engine = get_engine(requested_device)

    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not groq_key and not engine.is_package_installed():
        task.status = 'FAILED'
        task.error = "La clé GROQ_API_KEY n'est pas configurée sur Render. Rendez-vous dans l'onglet 'Environment' de Render et ajoutez GROQ_API_KEY pour activer l'IA de traduction."
        task.message = task.error
        return

    def progress_callback(cur: int, total: int, msg: str):
        task.current_page = cur
        task.total_pages = total
        if total > 0:
            task.progress_percent = int((cur / total) * 100)
        task.message = msg

    try:
        success = PdfProcessor.translate_document(
            input_pdf_path=input_path,
            output_pdf_path=output_path,
            from_lang=from_lang,
            to_lang=to_lang,
            translator_func=engine.translate_batch_texts,
            skip_figures=True,
            progress_callback=progress_callback
        )

        if not success:
            task.status = 'FAILED'
            task.error = 'La traduction du PDF a échoué.'
            return

        # Bouclier 5 : Application du filigrane pour les utilisateurs gratuits
        if tier_rule.get('watermark_required', False):
            task.message = 'Application du filigrane de sécurité...'
            apply_freemium_watermark(output_path)
            task.watermarked = True

        # Enregistrement de l utilisation
        if tier in (UserTier.ANONYMOUS, UserTier.FREE):
            circuit_breaker.record_free_usage()

        if user_id:
            db_service.increment_daily_usage(user_id)
            db_service.increment_monthly_usage(user_id)

        task.status = 'COMPLETED'
        task.progress_percent = 100
        task.message = 'Traduction terminée avec succès !'
        task.completed_at = datetime.now(timezone.utc).isoformat()
        task.download_url = f'/api/download/{task_id}'

    except Exception as e:
        task.status = 'FAILED'
        task.error = str(e)
        task.message = f'Erreur : {e}'


def queue_translation_task(input_path: str, filename: str,
                           from_lang: str, to_lang: str,
                           tier: UserTier, user_id: str = None, client_ip: str = None) -> str:
    task_id = str(uuid.uuid4())
    output_filename = f'{task_id}_{to_lang}.pdf'
    output_path = os.path.join(TRANSLATED_DIR, output_filename)

    task = TranslationTaskStatus(
        task_id=task_id,
        status='QUEUED',
        source_lang=from_lang,
        target_lang=to_lang,
        filename=filename,
        created_at=datetime.now(timezone.utc).isoformat(),
        message='En attente dans la file de traitement...'
    )
    TASKS[task_id] = task

    # Launch background thread
    t = threading.Thread(
        target=execute_translation_job,
        args=(task_id, input_path, output_path, from_lang, to_lang, tier, user_id, client_ip),
        daemon=True
    )
    t.start()

    return task_id
