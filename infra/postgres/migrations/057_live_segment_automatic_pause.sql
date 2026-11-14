BEGIN;

CREATE OR REPLACE FUNCTION public.match_live_segment_pause_allowed(
    previous public.match_live_state, proposed public.match_live_state
) RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY INVOKER SET search_path = pg_catalog, public AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.match_segments ms
        JOIN public.matches m ON m.id = ms.match_id AND m.organization_id = ms.organization_id
        JOIN public.organization_users ou ON ou.organization_id = m.organization_id
            AND ou.id = proposed.updated_by_member_id
            AND ou.user_id = NULLIF(current_setting('app.current_user_id',true),'')::UUID AND ou.is_active
        WHERE pg_trigger_depth() = 1
            AND ms.id = previous.segment_id AND ms.match_id = previous.match_id
            AND ms.organization_id = previous.organization_id AND ms.status IN ('interrupted','completed')
            AND m.status = 'live' AND NOT m.result_confirmed AND previous.frozen_at IS NULL
            AND previous.clock_state = 'running' AND proposed.clock_state = 'paused'
            AND proposed.clock_anchor_at IS NULL AND proposed.updated_at >= statement_timestamp()
            AND proposed.clock_elapsed_us = previous.clock_elapsed_us
                + (GREATEST(0, EXTRACT(EPOCH FROM (proposed.updated_at - previous.clock_anchor_at))) * 1000000)::BIGINT
            AND proposed.revision = previous.revision + 1
            AND (to_jsonb(previous) - ARRAY['clock_state','clock_anchor_at','clock_elapsed_us','revision','updated_at','updated_by_member_id'])
                = (to_jsonb(proposed) - ARRAY['clock_state','clock_anchor_at','clock_elapsed_us','revision','updated_at','updated_by_member_id'])
            AND public.match_live_has_permission(previous.organization_id,previous.match_id,'CLOSE_MATCH_REPORT')
    )
$$;
REVOKE ALL ON FUNCTION public.match_live_segment_pause_allowed(public.match_live_state,public.match_live_state) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.match_live_segment_pause_allowed(public.match_live_state,public.match_live_state) TO bracket_app;

DROP TRIGGER IF EXISTS trg_validate_live_write ON public.match_live_state;
DROP TRIGGER IF EXISTS trg_validate_live_insert ON public.match_live_state;
CREATE TRIGGER trg_validate_live_insert BEFORE INSERT ON public.match_live_state
    FOR EACH ROW EXECUTE FUNCTION public.validate_match_live_write();
CREATE TRIGGER trg_validate_live_write BEFORE UPDATE ON public.match_live_state
    FOR EACH ROW WHEN (NOT public.match_live_segment_pause_allowed(OLD,NEW))
    EXECUTE FUNCTION public.validate_match_live_write();

CREATE OR REPLACE FUNCTION public.validate_match_live_segment()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
BEGIN
    PERFORM 1 FROM public.matches WHERE id = NEW.match_id AND organization_id = NEW.organization_id FOR UPDATE;
    IF NEW.status <> 'active' AND EXISTS (SELECT 1 FROM public.match_live_state
        WHERE segment_id = NEW.id AND match_id = NEW.match_id AND organization_id = NEW.organization_id
            AND clock_state = 'running') THEN
        IF OLD.status <> 'active' OR NEW.status NOT IN ('interrupted','completed')
            OR NOT public.match_live_has_permission(NEW.organization_id,NEW.match_id,'CLOSE_MATCH_REPORT') THEN
            RAISE EXCEPTION 'LIVE_SEGMENT_PAUSE_NOT_AUTHORIZED' USING ERRCODE = '42501';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.validate_match_live_segment() FROM PUBLIC, bracket_app;

CREATE OR REPLACE FUNCTION public.pause_match_live_segment()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
DECLARE accepted_at TIMESTAMPTZ := clock_timestamp();
BEGIN
    IF OLD.status = 'active' AND NEW.status IN ('interrupted','completed') THEN
        UPDATE public.match_live_state SET clock_state = 'paused', clock_anchor_at = NULL,
            clock_elapsed_us = clock_elapsed_us
                + (GREATEST(0, EXTRACT(EPOCH FROM (accepted_at - clock_anchor_at))) * 1000000)::BIGINT,
            revision = revision + 1, updated_at = accepted_at,
            updated_by_member_id = (SELECT id FROM public.organization_users
                WHERE organization_id = NEW.organization_id
                    AND user_id = NULLIF(current_setting('app.current_user_id',true),'')::UUID AND is_active)
        WHERE segment_id = NEW.id AND match_id = NEW.match_id AND organization_id = NEW.organization_id
            AND clock_state = 'running';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.pause_match_live_segment() FROM PUBLIC, bracket_app;
DROP TRIGGER IF EXISTS trg_pause_match_live_segment ON public.match_segments;
CREATE TRIGGER trg_pause_match_live_segment AFTER UPDATE OF status ON public.match_segments
    FOR EACH ROW EXECUTE FUNCTION public.pause_match_live_segment();

COMMIT;
