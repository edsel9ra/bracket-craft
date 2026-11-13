BEGIN;

ALTER TABLE public.match_segments ADD UNIQUE (id, organization_id);
ALTER TABLE public.sanction_transaction_provenance ADD COLUMN segment_id UUID UNIQUE;
ALTER TABLE public.sanction_transaction_provenance ADD FOREIGN KEY (segment_id, organization_id)
    REFERENCES public.match_segments(id, organization_id) ON DELETE RESTRICT;
ALTER TABLE public.sanction_transaction_provenance DROP CONSTRAINT sanction_transaction_provenance_check;
ALTER TABLE public.sanction_transaction_provenance ADD CHECK (num_nonnulls(version_id, decision_id, case_event_id, segment_id) = 1);

CREATE OR REPLACE FUNCTION public.sanction_record_transaction()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_TABLE_SCHEMA <> 'public' OR TG_TABLE_NAME NOT IN
        ('match_report_versions', 'sanction_case_decisions', 'sanction_case_events', 'match_segments') THEN
        RAISE EXCEPTION 'SANCTION_INVALID_TRANSACTION_SOURCE' USING ERRCODE = '42501';
    END IF;
    INSERT INTO public.sanction_transaction_provenance(organization_id, version_id, decision_id, case_event_id, segment_id, transaction_id)
        VALUES (NEW.organization_id,
            CASE WHEN TG_TABLE_NAME = 'match_report_versions' THEN NEW.id END,
            CASE WHEN TG_TABLE_NAME = 'sanction_case_decisions' THEN NEW.id END,
            CASE WHEN TG_TABLE_NAME = 'sanction_case_events' THEN NEW.id END,
            CASE WHEN TG_TABLE_NAME = 'match_segments' THEN NEW.id END,
            pg_current_xact_id());
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_sanction_segment_transaction AFTER INSERT ON public.match_segments
    FOR EACH ROW EXECUTE FUNCTION public.sanction_record_transaction();

CREATE FUNCTION public.record_sanction_opening(target_match UUID, target_segment UUID)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE org UUID := NULLIF(current_setting('app.current_organization_id', true), '')::UUID;
    opened_at TIMESTAMPTZ; target public.player_suspensions; resolution public.sanction_resolutions;
    duration INTEGER; applicable TEXT; selected_resolution UUID; served INTEGER; next_status TEXT;
BEGIN
    IF NOT public.sanction_can_operate_match(org, target_match) THEN
        RAISE EXCEPTION 'SANCTION_OPERATION_DENIED' USING ERRCODE = '42501';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('discipline:' || org::TEXT, 0));
    PERFORM 1 FROM public.matches WHERE id = target_match AND organization_id = org
        AND NOT result_confirmed AND status NOT IN ('finished', 'cancelled', 'administrative_resolution') FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'SANCTION_OPENING_REQUIRED' USING ERRCODE = '42501'; END IF;
    SELECT s.created_at INTO opened_at FROM public.match_segments s
        JOIN public.sanction_transaction_provenance p ON p.segment_id = s.id AND p.organization_id = s.organization_id
        WHERE s.id = target_segment AND s.match_id = target_match AND s.organization_id = org
            AND p.transaction_id = pg_current_xact_id()
            AND NOT EXISTS (SELECT 1 FROM public.match_segments other
                WHERE other.match_id = s.match_id AND other.organization_id = org AND other.id <> s.id);
    IF opened_at IS NULL THEN RAISE EXCEPTION 'SANCTION_OPENING_REQUIRED' USING ERRCODE = '42501'; END IF;
    FOR target IN SELECT ps.* FROM public.player_suspensions ps
        JOIN public.matches m ON m.id = target_match AND m.organization_id = ps.organization_id
        WHERE ps.organization_id = org AND ps.created_at <= opened_at
            AND (ps.scope_type = 'organization' OR ps.source_tournament_id = m.tournament_id)
            AND EXISTS (SELECT 1 FROM public.rosters r WHERE r.organization_id = org AND r.is_active
                AND r.tournament_id = m.tournament_id AND r.team_id IN (m.home_team_id, m.away_team_id) AND r.player_id = ps.player_id)
        ORDER BY ps.id FOR UPDATE OF ps
    LOOP
        SELECT count(*) INTO served FROM public.player_suspension_serves
            WHERE suspension_id = target.id AND organization_id = org AND NOT is_voided;
        FOR resolution IN SELECT r.* FROM public.sanction_resolutions r
            WHERE r.suspension_id = target.id AND r.organization_id = org AND NOT r.is_declarative
                AND r.created_at <= opened_at
                AND NOT EXISTS (SELECT 1 FROM public.sanction_effect_applications a WHERE a.resolution_id = r.id)
                AND NOT EXISTS (SELECT 1 FROM public.sanction_case_events e WHERE e.case_id = r.case_id
                    AND e.organization_id = org AND e.event_type = 'affected_by_rectification')
            ORDER BY r.created_at, r.id
        LOOP
            IF target.status = 'cancelled' THEN CONTINUE; END IF;
            next_status := CASE WHEN resolution.action = 'annul' THEN 'cancelled'
                WHEN served >= resolution.new_duration THEN 'served' ELSE 'active' END;
            INSERT INTO public.sanction_effect_applications(organization_id, resolution_id, suspension_id,
                match_id, effective_at, before_status, after_status)
                VALUES (org, resolution.id, target.id, target_match, opened_at, target.status, next_status);
            UPDATE public.player_suspensions SET status = next_status WHERE id = target.id AND organization_id = org;
            target.status := next_status;
        END LOOP;
        selected_resolution := NULL;
        SELECT r.* INTO resolution FROM public.sanction_resolutions r
            WHERE r.suspension_id = target.id AND r.organization_id = org AND r.created_at <= opened_at
                AND (r.is_declarative OR EXISTS (SELECT 1 FROM public.sanction_effect_applications a
                    WHERE a.resolution_id = r.id AND a.effective_at <= opened_at))
                AND NOT EXISTS (SELECT 1 FROM public.sanction_case_events e WHERE e.case_id = r.case_id
                    AND e.organization_id = org AND e.event_type = 'affected_by_rectification')
            ORDER BY r.created_at DESC, r.id DESC LIMIT 1;
        duration := target.matches_suspended;
        applicable := target.status;
        IF resolution.id IS NOT NULL THEN
            selected_resolution := resolution.id;
            duration := CASE WHEN resolution.action = 'annul' THEN 0 ELSE resolution.new_duration END;
        END IF;
        INSERT INTO public.sanction_match_eligibility(organization_id, suspension_id, match_id, effective_duration,
            applicable_status, resolution_id, started_at, served_count)
            VALUES (org, target.id, target_match, duration, applicable, selected_resolution, opened_at, served)
            ON CONFLICT (suspension_id, match_id) DO NOTHING;
    END LOOP;
END;
$$;
REVOKE ALL ON FUNCTION public.record_sanction_opening(UUID, UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.record_sanction_opening(UUID, UUID) TO bracket_app;

COMMIT;
