BEGIN;

CREATE UNIQUE INDEX uq_competitive_impact_version ON public.competitive_impact_procedures(version_id);
CREATE INDEX idx_competitive_impact_open_items ON public.competitive_impact_procedures
USING GIN (affected_items jsonb_path_ops) WHERE status='open';

CREATE FUNCTION public.assert_no_open_competitive_impact(p_match UUID, p_org UUID)
RETURNS VOID LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE m public.matches;
BEGIN
    SELECT * INTO m FROM public.matches WHERE id=p_match AND organization_id=p_org FOR UPDATE;
    IF NOT FOUND OR m.result_confirmed
       OR EXISTS (SELECT 1 FROM public.match_segments WHERE match_id=p_match AND organization_id=p_org)
    THEN RETURN; END IF;
    IF EXISTS (SELECT 1 FROM public.competitive_impact_procedures
        WHERE organization_id=p_org AND status='open'
          AND affected_items @> jsonb_build_array(jsonb_build_object('match_id',p_match::text)))
    THEN RAISE EXCEPTION 'COMPETITIVE_IMPACT_OPEN' USING ERRCODE='BC409'; END IF;
END;
$$;

CREATE FUNCTION public.guard_competitive_impact_match()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_TABLE_NAME = 'match_segments' THEN
        PERFORM public.assert_no_open_competitive_impact(NEW.match_id,NEW.organization_id);
    ELSIF NOT OLD.result_confirmed AND NEW.result_confirmed THEN
        PERFORM public.assert_no_open_competitive_impact(OLD.id,OLD.organization_id);
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_competitive_impact_segment BEFORE INSERT ON public.match_segments
FOR EACH ROW EXECUTE FUNCTION public.guard_competitive_impact_match();
CREATE TRIGGER trg_competitive_impact_confirmation BEFORE UPDATE ON public.matches
FOR EACH ROW EXECUTE FUNCTION public.guard_competitive_impact_match();

CREATE FUNCTION public.validate_competitive_impact_opening()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE item JSONB; target public.matches; source public.matches;
BEGIN
    IF NEW.status <> 'open' OR NEW.resolution IS NOT NULL OR NEW.reason IS NOT NULL
       OR NEW.closed_by_user_id IS NOT NULL OR NEW.closed_at IS NOT NULL
    THEN RAISE EXCEPTION 'RECTIFICATION_INVALID_TRANSITION' USING ERRCODE='23514'; END IF;
    SELECT * INTO source FROM public.matches WHERE id=NEW.match_id AND organization_id=NEW.organization_id;
    FOR item IN SELECT value FROM jsonb_array_elements(NEW.affected_items)
        WHERE value ? 'match_id' ORDER BY value->>'match_id'
    LOOP
        SELECT * INTO target FROM public.matches
        WHERE id=(item->>'match_id')::uuid AND organization_id=NEW.organization_id FOR UPDATE;
        IF NOT FOUND OR target.tournament_version_id IS DISTINCT FROM source.tournament_version_id
        THEN RAISE EXCEPTION 'RECTIFICATION_INVALID_CONTEXT' USING ERRCODE='23514'; END IF;
    END LOOP;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_competitive_impact_opening BEFORE INSERT ON public.competitive_impact_procedures
FOR EACH ROW EXECUTE FUNCTION public.validate_competitive_impact_opening();

COMMIT;
