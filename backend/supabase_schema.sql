-- ==============================================================================
-- Schema SQL de Production pour Supabase (PostgreSQL)
-- translate-for-pdf.com
-- A executer dans : Supabase Dashboard > SQL Editor > New Query
-- ==============================================================================

-- 1. Table des profils utilisateurs liee a l'authentification Supabase (auth.users)
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT UNIQUE NOT NULL,
    plan_tier TEXT NOT NULL DEFAULT 'FREE' CHECK (plan_tier IN ('FREE', 'STARTER', 'PRO')),
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_profiles_email ON public.profiles(email);
CREATE INDEX IF NOT EXISTS idx_profiles_plan_tier ON public.profiles(plan_tier);

-- 2. Table de suivi des quotas journaliers (Free: max 2 docs/jour, Pro: max 10 docs/jour)
CREATE TABLE IF NOT EXISTS public.daily_usage (
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    usage_date DATE NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, usage_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_usage_date ON public.daily_usage(usage_date);

-- 3. Table de suivi des quotas mensuels (Starter: max 150 docs/mois)
CREATE TABLE IF NOT EXISTS public.monthly_usage (
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    month_key TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, month_key)
);

-- 4. Table d'historique et d'audit des traductions
CREATE TABLE IF NOT EXISTS public.translations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    filename TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    source_lang TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED' CHECK (status IN ('QUEUED', 'PROCESSING', 'COMPLETED', 'FAILED')),
    hardware_device TEXT NOT NULL DEFAULT 'cpu',
    watermarked BOOLEAN NOT NULL DEFAULT FALSE,
    surcharge_usd NUMERIC(5, 2) DEFAULT 0.00,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_translations_user_id ON public.translations(user_id);
CREATE INDEX IF NOT EXISTS idx_translations_created_at ON public.translations(created_at DESC);

-- 5. Trigger d'automatisation : Cree automatiquement un profil 'FREE' lors de l'inscription
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, email, plan_tier, created_at, updated_at)
    VALUES (
        NEW.id,
        NEW.email,
        'FREE',
        NOW(),
        NOW()
    )
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- 6. Securite : Activation de Row Level Security (RLS)
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.daily_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.monthly_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.translations ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Les utilisateurs peuvent voir leur propre profil"
    ON public.profiles FOR SELECT
    USING (auth.uid() = id);

CREATE POLICY "Les utilisateurs peuvent voir leur consommation journaliere"
    ON public.daily_usage FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Les utilisateurs peuvent voir leur consommation mensuelle"
    ON public.monthly_usage FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Les utilisateurs peuvent voir leurs traductions"
    ON public.translations FOR SELECT
    USING (auth.uid() = user_id);
