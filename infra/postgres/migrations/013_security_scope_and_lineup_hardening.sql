BEGIN;

-- Older migrations are immutable. Rebuild every platform function that still
-- uses a nullable role comparison so an absent actor fails closed.
DO $$
DECLARE
    v_function_id OID;
    v_definition TEXT;
    v_hardened_definition TEXT;
BEGIN
    FOR v_function_id IN
        SELECT p.oid
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public'
          AND p.prokind = 'f'
          AND p.prosrc LIKE '%fn_platform_actor_role%'
    LOOP
        v_definition := pg_get_functiondef(v_function_id);
        v_hardened_definition := regexp_replace(
            v_definition,
            $pattern$fn_platform_actor_role\(\)[[:space:]]*<>[[:space:]]*'platform_admin'$pattern$,
            $replacement$fn_platform_actor_role() IS DISTINCT FROM 'platform_admin'$replacement$,
            'g'
        );
        IF v_hardened_definition IS DISTINCT FROM v_definition THEN
            EXECUTE v_hardened_definition;
        END IF;
    END LOOP;
END;
$$;

-- Public pages should expose the latest published tactical lineup for each
-- match/team, rather than the first published segment encountered.
DO $$
DECLARE
    v_definition TEXT;
    v_hardened_definition TEXT;
BEGIN
    IF to_regclass('public.v_public_match_lineups_unpublished') IS NOT NULL THEN
        SELECT pg_get_viewdef('public.v_public_match_lineups_unpublished'::regclass, true)
        INTO v_definition;
        v_hardened_definition := regexp_replace(
            v_definition,
            'ORDER BY tl\.match_id, tl\.team_id, ms\.segment_number, tl\.published_at, tl\.id',
            'ORDER BY tl.match_id, tl.team_id, tl.published_at DESC, ms.segment_number DESC, tl.id DESC',
            'g'
        );
        IF v_hardened_definition IS DISTINCT FROM v_definition THEN
            EXECUTE 'CREATE OR REPLACE VIEW public.v_public_match_lineups_unpublished '
                || 'WITH (security_barrier = true) AS '
                || v_hardened_definition;
        END IF;
    END IF;
END;
$$;

COMMIT;
