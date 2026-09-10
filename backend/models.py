from typing import Optional
from pydantic import BaseModel
from backend.config import UserTier

class QuoteResponse(BaseModel):
    page_count: int
    user_tier: UserTier
    can_translate: bool
    status: str
    message: str
    extra_fee_usd: float = 0.0
    device_assigned: str = 'cpu'
    watermark_applied: bool = True
    suggested_tier: Optional[UserTier] = None

class TranslationTaskStatus(BaseModel):
    task_id: str
    status: str  # QUEUED, PROCESSING, COMPLETED, FAILED
    progress_percent: int = 0
    current_page: int = 0
    total_pages: int = 0
    message: str = ''
    source_lang: str = 'en'
    target_lang: str = 'fr'
    filename: str = ''
    download_url: Optional[str] = None
    error: Optional[str] = None
    created_at: str = ''
    completed_at: Optional[str] = None
    watermarked: bool = False

class CircuitBreakerStatus(BaseModel):
    date: str
    free_docs_today: int
    daily_limit: int
    quota_remaining: int
    is_tripped: bool

class UserProfile(BaseModel):
    user_id: str
    email: str
    plan_tier: UserTier
    daily_used_today: int = 0
    monthly_used_this_month: int = 0
