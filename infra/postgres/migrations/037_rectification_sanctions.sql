BEGIN;

ALTER TABLE public.matches ADD COLUMN original_report_confirmed_at TIMESTAMPTZ;

UPDATE public.matches m
SET original_report_confirmed_at = (
    SELECT min(a.performed_at)
    FROM public.administrative_audit_logs a
    WHERE a.organization_id = m.organization_id AND a.entity_type = 'matches'
      AND a.entity_id = m.id
      AND a.action IN ('CLOSE_MATCH_REPORT', 'ADMINISTRATIVE_MATCH_RESOLUTION')
)
WHERE m.result_confirmed;

CREATE FUNCTION public.protect_original_report_confirmation_time()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.original_report_confirmed_at := CASE WHEN NEW.result_confirmed THEN now() ELSE NULL END;
    ELSIF NOT OLD.result_confirmed AND NEW.result_confirmed THEN
        NEW.original_report_confirmed_at := now();
    ELSIF NEW.original_report_confirmed_at IS DISTINCT FROM OLD.original_report_confirmed_at THEN
        RAISE EXCEPTION 'La fecha original de confirmación es inmutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_original_report_confirmation_time
BEFORE INSERT OR UPDATE ON public.matches
FOR EACH ROW EXECUTE FUNCTION public.protect_original_report_confirmation_time();

ALTER TABLE public.match_report_version_events
    ADD CONSTRAINT uq_version_event_suspension_context UNIQUE (id, match_id, player_id, organization_id);

ALTER TABLE public.player_suspensions
    ADD COLUMN source_version_event_id UUID,
    ADD CONSTRAINT fk_player_suspensions_version_event
        FOREIGN KEY (source_version_event_id, origin_match_id, player_id, organization_id)
        REFERENCES public.match_report_version_events(id, match_id, player_id, organization_id) ON DELETE RESTRICT,
    DROP CONSTRAINT chk_suspension_source,
    ADD CONSTRAINT chk_suspension_source CHECK (
        (source_type = 'match_event' AND origin_match_id IS NOT NULL
         AND num_nonnulls(source_event_id, source_version_event_id) = 1)
        OR (source_type IN ('administrative_resolution', 'competition_rule')
            AND source_event_id IS NULL AND source_version_event_id IS NULL)
    );

CREATE FUNCTION public.protect_suspension_columns()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF (to_jsonb(NEW) - 'status') IS DISTINCT FROM (to_jsonb(OLD) - 'status') THEN
        RAISE EXCEPTION 'Las columnas de una sanción son inmutables' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_protect_suspension_columns
BEFORE UPDATE ON public.player_suspensions
FOR EACH ROW EXECUTE FUNCTION public.protect_suspension_columns();

COMMIT;
