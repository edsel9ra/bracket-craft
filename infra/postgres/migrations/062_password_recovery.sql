BEGIN;

-- ============================================================================
-- Spec 039 (F3, T1): recuperación y cambio de contraseña.
--
-- Tablas de cuenta (no de tenant, como users y user_sessions): bracket_app no
-- recibe privilegios directos; solo ejecuta funciones SECURITY DEFINER con
-- search_path fijo. La petición pública solo encola el correo normalizado
-- (RNF-001); el worker resuelve la cuenta y emite el token, del que solo se
-- guarda el SHA-256 (RNF-002). Consumir el enlace bloquea el token y la cuenta
-- (RNF-003). Ningún correo ni secreto llega a account_security_events (RF-012).
-- ============================================================================

CREATE TABLE public.account_email_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind VARCHAR(40) NOT NULL
        CHECK (kind IN ('password_reset_request', 'password_changed_notice')),
    email VARCHAR(255),
    user_id UUID REFERENCES public.users(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'processed', 'failed')),
    attempts INT NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    available_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    locked_at TIMESTAMPTZ,
    processed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_account_email_job_target CHECK (
        (kind = 'password_reset_request' AND user_id IS NULL)
        OR (kind = 'password_changed_notice' AND email IS NULL AND user_id IS NOT NULL)
    )
);

CREATE INDEX idx_account_email_jobs_pending
    ON public.account_email_jobs (available_at)
    WHERE status IN ('pending', 'processing');
CREATE INDEX idx_account_email_jobs_retention
    ON public.account_email_jobs (processed_at)
    WHERE status IN ('processed', 'failed');

CREATE TABLE public.password_reset_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    token_hash CHAR(64) NOT NULL CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    invalidated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_password_reset_token_hash UNIQUE (token_hash),
    CONSTRAINT chk_password_reset_token_expiry CHECK (expires_at > created_at)
);

CREATE INDEX idx_password_reset_tokens_pending
    ON public.password_reset_tokens (user_id)
    WHERE used_at IS NULL AND invalidated_at IS NULL;
CREATE INDEX idx_password_reset_tokens_expiry ON public.password_reset_tokens (expires_at);

CREATE TABLE public.account_security_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    event_type VARCHAR(30) NOT NULL CHECK (event_type IN ('password_reset', 'password_changed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_account_security_events_user
    ON public.account_security_events (user_id, created_at DESC);

ALTER TABLE public.account_email_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.password_reset_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.account_security_events ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.account_email_jobs, public.password_reset_tokens,
    public.account_security_events FROM PUBLIC, bracket_app;

CREATE FUNCTION public.enqueue_password_reset_request(p_email TEXT)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_email TEXT := LOWER(BTRIM(p_email));
BEGIN
    IF v_email IS NULL OR v_email = '' OR length(v_email) > 255 THEN
        RAISE EXCEPTION 'invalid password reset request';
    END IF;
    INSERT INTO public.account_email_jobs (kind, email)
    VALUES ('password_reset_request', v_email);
END;
$$;

CREATE FUNCTION public.claim_account_email_jobs(p_limit INT DEFAULT 20)
RETURNS TABLE (id UUID, kind VARCHAR, attempts INT, created_at TIMESTAMPTZ)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100 THEN
        RAISE EXCEPTION 'invalid claim limit';
    END IF;
    RETURN QUERY
    WITH candidates AS (
        SELECT j.id
        FROM public.account_email_jobs j
        WHERE (j.status = 'pending' AND j.available_at <= CURRENT_TIMESTAMP)
           OR (j.status = 'processing' AND j.locked_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes')
        ORDER BY j.available_at, j.id
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    )
    UPDATE public.account_email_jobs j
    SET status = 'processing', locked_at = CURRENT_TIMESTAMP, attempts = j.attempts + 1
    FROM candidates c
    WHERE j.id = c.id
    RETURNING j.id, j.kind, j.attempts, j.created_at;
END;
$$;

CREATE FUNCTION public.issue_password_reset(
    p_job_id UUID,
    p_token_hash TEXT,
    p_expires_at TIMESTAMPTZ
)
RETURNS TABLE (outcome TEXT, recipient TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_email TEXT;
    v_user RECORD;
BEGIN
    IF p_expires_at IS NULL OR p_expires_at <= CURRENT_TIMESTAMP
       OR p_expires_at > CURRENT_TIMESTAMP + INTERVAL '1 hour' THEN
        RAISE EXCEPTION 'invalid password reset expiry';
    END IF;
    SELECT j.email INTO v_email
    FROM public.account_email_jobs j
    WHERE j.id = p_job_id AND j.kind = 'password_reset_request' AND j.status = 'processing'
    FOR UPDATE;
    IF v_email IS NULL THEN
        RAISE EXCEPTION 'password reset job not claimable';
    END IF;

    SELECT u.id, u.email, u.password_hash INTO v_user
    FROM public.users u
    WHERE LOWER(u.email) = v_email AND u.is_active = TRUE
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'none'::TEXT, NULL::TEXT;
        RETURN;
    END IF;
    IF v_user.password_hash IS NULL THEN
        RETURN QUERY SELECT 'google_reminder'::TEXT, v_user.email::TEXT;
        RETURN;
    END IF;

    UPDATE public.password_reset_tokens
    SET invalidated_at = CURRENT_TIMESTAMP
    WHERE user_id = v_user.id AND used_at IS NULL AND invalidated_at IS NULL;
    INSERT INTO public.password_reset_tokens (user_id, token_hash, expires_at)
    VALUES (v_user.id, p_token_hash, p_expires_at);
    RETURN QUERY SELECT 'reset'::TEXT, v_user.email::TEXT;
END;
$$;

CREATE FUNCTION public.invalidate_password_reset_token(p_token_hash TEXT)
RETURNS VOID
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    UPDATE public.password_reset_tokens
    SET invalidated_at = CURRENT_TIMESTAMP
    WHERE token_hash = p_token_hash AND used_at IS NULL AND invalidated_at IS NULL;
$$;

CREATE FUNCTION public.account_email_notice_target(p_job_id UUID)
RETURNS TABLE (recipient TEXT)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT u.email::TEXT
    FROM public.account_email_jobs j
    JOIN public.users u ON u.id = j.user_id
    WHERE j.id = p_job_id AND j.kind = 'password_changed_notice'
      AND j.status = 'processing' AND u.is_active = TRUE;
$$;

CREATE FUNCTION public.complete_account_email_job(p_job_id UUID)
RETURNS VOID
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    UPDATE public.account_email_jobs
    SET status = 'processed', email = NULL, locked_at = NULL, processed_at = CURRENT_TIMESTAMP
    WHERE id = p_job_id AND status = 'processing';
$$;

CREATE FUNCTION public.fail_account_email_job(p_job_id UUID, p_max_attempts INT DEFAULT 5)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF p_max_attempts IS NULL OR p_max_attempts < 1 OR p_max_attempts > 20 THEN
        RAISE EXCEPTION 'invalid max attempts';
    END IF;
    UPDATE public.account_email_jobs
    SET status = CASE WHEN attempts >= p_max_attempts THEN 'failed' ELSE 'pending' END,
        email = CASE WHEN attempts >= p_max_attempts THEN NULL ELSE email END,
        processed_at = CASE WHEN attempts >= p_max_attempts THEN CURRENT_TIMESTAMP ELSE NULL END,
        available_at = CURRENT_TIMESTAMP + make_interval(secs => 30 * power(2, LEAST(attempts, 6))),
        locked_at = NULL
    WHERE id = p_job_id AND status = 'processing';
END;
$$;

CREATE FUNCTION public.password_reset_target(p_token_hash TEXT)
RETURNS TABLE (user_id UUID, password_hash TEXT)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT u.id, u.password_hash::TEXT
    FROM public.password_reset_tokens t
    JOIN public.users u ON u.id = t.user_id
    WHERE t.token_hash = p_token_hash
      AND t.used_at IS NULL AND t.invalidated_at IS NULL
      AND t.expires_at > CURRENT_TIMESTAMP
      AND u.is_active = TRUE AND u.password_hash IS NOT NULL;
$$;

CREATE FUNCTION public.complete_password_reset(
    p_token_hash TEXT,
    p_current_hash TEXT,
    p_new_hash TEXT
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_token_id UUID;
    v_user_id UUID;
BEGIN
    IF p_new_hash IS NULL OR p_new_hash NOT LIKE '$argon2%' THEN
        RAISE EXCEPTION 'invalid password hash';
    END IF;
    -- Orden de bloqueo usuario → enlace, el mismo que change_account_password
    -- e issue_password_reset, para que dos operaciones simultáneas no se
    -- bloqueen mutuamente.
    SELECT t.user_id INTO v_user_id
    FROM public.password_reset_tokens t
    WHERE t.token_hash = p_token_hash;
    IF v_user_id IS NULL THEN
        RETURN NULL;
    END IF;
    PERFORM 1
    FROM public.users u
    WHERE u.id = v_user_id AND u.is_active = TRUE AND u.password_hash = p_current_hash
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    SELECT t.id INTO v_token_id
    FROM public.password_reset_tokens t
    WHERE t.token_hash = p_token_hash
      AND t.used_at IS NULL AND t.invalidated_at IS NULL
      AND t.expires_at > CURRENT_TIMESTAMP
    FOR UPDATE;
    IF v_token_id IS NULL THEN
        RETURN NULL;
    END IF;

    UPDATE public.users SET password_hash = p_new_hash WHERE id = v_user_id;
    UPDATE public.password_reset_tokens SET used_at = CURRENT_TIMESTAMP WHERE id = v_token_id;
    UPDATE public.password_reset_tokens
    SET invalidated_at = CURRENT_TIMESTAMP
    WHERE user_id = v_user_id AND id <> v_token_id AND used_at IS NULL AND invalidated_at IS NULL;
    UPDATE public.user_sessions
    SET revoked_at = CURRENT_TIMESTAMP
    WHERE user_id = v_user_id AND revoked_at IS NULL;
    INSERT INTO public.account_email_jobs (kind, user_id) VALUES ('password_changed_notice', v_user_id);
    INSERT INTO public.account_security_events (user_id, event_type) VALUES (v_user_id, 'password_reset');
    RETURN v_user_id;
END;
$$;

CREATE FUNCTION public.change_account_password(
    p_user_id UUID,
    p_session_id UUID,
    p_current_hash TEXT,
    p_new_hash TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF p_new_hash IS NULL OR p_new_hash NOT LIKE '$argon2%' THEN
        RAISE EXCEPTION 'invalid password hash';
    END IF;
    PERFORM 1
    FROM public.users u
    JOIN public.user_sessions s ON s.user_id = u.id
    WHERE u.id = p_user_id AND u.is_active = TRUE AND u.password_hash = p_current_hash
      AND s.id = p_session_id AND s.revoked_at IS NULL AND s.expires_at > CURRENT_TIMESTAMP
    FOR UPDATE OF u;
    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    UPDATE public.users SET password_hash = p_new_hash WHERE id = p_user_id;
    UPDATE public.user_sessions
    SET revoked_at = CURRENT_TIMESTAMP
    WHERE user_id = p_user_id AND id <> p_session_id AND revoked_at IS NULL;
    UPDATE public.password_reset_tokens
    SET invalidated_at = CURRENT_TIMESTAMP
    WHERE user_id = p_user_id AND used_at IS NULL AND invalidated_at IS NULL;
    INSERT INTO public.account_email_jobs (kind, user_id) VALUES ('password_changed_notice', p_user_id);
    INSERT INTO public.account_security_events (user_id, event_type) VALUES (p_user_id, 'password_changed');
    RETURN TRUE;
END;
$$;

CREATE FUNCTION public.purge_account_recovery_records(p_cutoff TIMESTAMPTZ, p_limit INT DEFAULT 500)
RETURNS TABLE (tokens_deleted INT, jobs_deleted INT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF p_cutoff IS NULL OR p_limit IS NULL OR p_limit < 1 OR p_limit > 500 THEN
        RAISE EXCEPTION 'invalid retention parameters';
    END IF;

    WITH candidates AS (
        SELECT id FROM public.password_reset_tokens
        WHERE expires_at < p_cutoff OR used_at < p_cutoff OR invalidated_at < p_cutoff
        LIMIT p_limit FOR UPDATE SKIP LOCKED
    )
    DELETE FROM public.password_reset_tokens t USING candidates c WHERE t.id = c.id;
    GET DIAGNOSTICS tokens_deleted = ROW_COUNT;

    WITH candidates AS (
        SELECT id FROM public.account_email_jobs
        WHERE status IN ('processed', 'failed') AND processed_at < p_cutoff
        LIMIT p_limit FOR UPDATE SKIP LOCKED
    )
    DELETE FROM public.account_email_jobs j USING candidates c WHERE j.id = c.id;
    GET DIAGNOSTICS jobs_deleted = ROW_COUNT;
    RETURN NEXT;
END;
$$;

REVOKE ALL ON FUNCTION
    public.enqueue_password_reset_request(TEXT),
    public.claim_account_email_jobs(INT),
    public.issue_password_reset(UUID, TEXT, TIMESTAMPTZ),
    public.invalidate_password_reset_token(TEXT),
    public.account_email_notice_target(UUID),
    public.complete_account_email_job(UUID),
    public.fail_account_email_job(UUID, INT),
    public.password_reset_target(TEXT),
    public.complete_password_reset(TEXT, TEXT, TEXT),
    public.change_account_password(UUID, UUID, TEXT, TEXT),
    public.purge_account_recovery_records(TIMESTAMPTZ, INT)
FROM PUBLIC;

GRANT EXECUTE ON FUNCTION
    public.enqueue_password_reset_request(TEXT),
    public.claim_account_email_jobs(INT),
    public.issue_password_reset(UUID, TEXT, TIMESTAMPTZ),
    public.invalidate_password_reset_token(TEXT),
    public.account_email_notice_target(UUID),
    public.complete_account_email_job(UUID),
    public.fail_account_email_job(UUID, INT),
    public.password_reset_target(TEXT),
    public.complete_password_reset(TEXT, TEXT, TEXT),
    public.change_account_password(UUID, UUID, TEXT, TEXT),
    public.purge_account_recovery_records(TIMESTAMPTZ, INT)
TO bracket_app;

COMMIT;
