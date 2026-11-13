BEGIN;

CREATE FUNCTION public.refresh_served_sanctions(target_match UUID, as_of TIMESTAMPTZ)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE org UUID := NULLIF(current_setting('app.current_organization_id', true), '')::UUID;
    target public.player_suspensions; duration INTEGER;
BEGIN
    IF NOT public.sanction_can_close_match(org, target_match) OR as_of IS NULL THEN
        RAISE EXCEPTION 'SANCTION_OPERATION_DENIED' USING ERRCODE = '42501';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('discipline:' || org::TEXT, 0));
    FOR target IN SELECT * FROM public.player_suspensions
        WHERE organization_id = org AND status = 'active' ORDER BY id FOR UPDATE
    LOOP
        SELECT CASE WHEN r.action = 'annul' THEN 0 ELSE r.new_duration END INTO duration
            FROM public.sanction_resolutions r
            WHERE r.suspension_id = target.id AND r.organization_id = org AND r.created_at <= as_of
                AND (r.is_declarative OR EXISTS (SELECT 1 FROM public.sanction_effect_applications a
                    WHERE a.resolution_id = r.id AND a.organization_id = org AND a.effective_at <= as_of))
                AND NOT EXISTS (SELECT 1 FROM public.sanction_case_events e
                    WHERE e.case_id = r.case_id AND e.organization_id = org AND e.event_type = 'affected_by_rectification')
            ORDER BY r.created_at DESC, r.id DESC LIMIT 1;
        duration := COALESCE(duration, target.matches_suspended);
        IF (SELECT count(*) FROM public.player_suspension_serves
            WHERE suspension_id = target.id AND organization_id = org AND NOT is_voided) >= duration THEN
            UPDATE public.player_suspensions SET status = 'served'
                WHERE id = target.id AND organization_id = org AND status = 'active';
        END IF;
    END LOOP;
END;
$$;
REVOKE ALL ON FUNCTION public.refresh_served_sanctions(UUID, TIMESTAMPTZ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.refresh_served_sanctions(UUID, TIMESTAMPTZ) TO bracket_app;

COMMIT;
