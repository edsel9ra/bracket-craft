BEGIN;

-- NULL must not satisfy an administrative role check.
CREATE OR REPLACE FUNCTION public.requeue_outbox_events(p_limit INT DEFAULT 100)
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_count INT;
BEGIN
    IF public.fn_platform_actor_role() IS DISTINCT FROM 'platform_admin' THEN
        RAISE EXCEPTION 'Permiso de plataforma requerido' USING ERRCODE = '42501';
    END IF;

    WITH candidates AS (
        SELECT oe.id
        FROM public.outbox_events oe
        WHERE oe.status = 'failed'
           OR (
               oe.status = 'processing'
               AND oe.locked_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes'
           )
        ORDER BY oe.created_at
        FOR UPDATE SKIP LOCKED
        LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 100), 1000))
    )
    UPDATE public.outbox_events oe
    SET status = 'pending',
        attempts = 0,
        available_at = CURRENT_TIMESTAMP,
        last_error = NULL,
        locked_at = NULL,
        processed_at = NULL
    FROM candidates
    WHERE oe.id = candidates.id;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;

-- Photo metadata is managed by the SECURITY DEFINER functions, not by direct
-- writes from the application role.
REVOKE INSERT (photo_url) ON public.players FROM bracket_app;
REVOKE INSERT ON public.rosters FROM bracket_app;
GRANT INSERT (
    organization_id, tournament_id, team_id, player_id, dorsal_number, photo_consent,
    valid_from, valid_to, eligible_from
) ON public.rosters TO bracket_app;
REVOKE UPDATE ON public.rosters FROM bracket_app;
GRANT UPDATE (dorsal_number, is_active, valid_from, valid_to, eligible_from)
    ON public.rosters TO bracket_app;

COMMIT;
