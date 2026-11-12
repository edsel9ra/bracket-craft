BEGIN;

CREATE INDEX idx_user_sessions_expiry_retention ON public.user_sessions (expires_at);
CREATE INDEX idx_user_sessions_revocation_retention ON public.user_sessions (revoked_at)
    WHERE revoked_at IS NOT NULL;
CREATE INDEX idx_outbox_processed_retention ON public.outbox_events (processed_at)
    WHERE status = 'processed' AND locked_at IS NULL;

CREATE FUNCTION public.purge_retained_records(
    p_session_cutoff TIMESTAMPTZ,
    p_outbox_cutoff TIMESTAMPTZ,
    p_limit INT DEFAULT 500
)
RETURNS TABLE (sessions_deleted INT, outbox_deleted INT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF p_session_cutoff IS NULL OR p_outbox_cutoff IS NULL
       OR p_limit IS NULL OR p_limit < 1 OR p_limit > 500 THEN
        RAISE EXCEPTION 'invalid retention parameters';
    END IF;

    WITH candidates AS (
        SELECT id FROM public.user_sessions
        WHERE expires_at < p_session_cutoff OR revoked_at < p_session_cutoff
        LIMIT p_limit FOR UPDATE SKIP LOCKED
    )
    DELETE FROM public.user_sessions s USING candidates c WHERE s.id = c.id;
    GET DIAGNOSTICS sessions_deleted = ROW_COUNT;

    WITH candidates AS (
        SELECT id FROM public.outbox_events
        WHERE status = 'processed' AND processed_at < p_outbox_cutoff
          AND locked_at IS NULL
        LIMIT p_limit FOR UPDATE SKIP LOCKED
    )
    DELETE FROM public.outbox_events e USING candidates c WHERE e.id = c.id;
    GET DIAGNOSTICS outbox_deleted = ROW_COUNT;
    RETURN NEXT;
END;
$$;

REVOKE ALL ON FUNCTION public.purge_retained_records(TIMESTAMPTZ, TIMESTAMPTZ, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.purge_retained_records(TIMESTAMPTZ, TIMESTAMPTZ, INT) TO bracket_app;

COMMIT;
