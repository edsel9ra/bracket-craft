BEGIN;

CREATE FUNCTION public.sanction_record_act_time()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_TABLE_SCHEMA <> 'public' THEN
        RAISE EXCEPTION 'SANCTION_INVALID_TRANSACTION_SOURCE' USING ERRCODE = '42501';
    END IF;
    IF TG_TABLE_NAME = 'sanction_case_decisions' THEN
        NEW.created_at := clock_timestamp();
    ELSIF TG_TABLE_NAME = 'sanction_resolutions' THEN
        SELECT d.created_at INTO NEW.created_at FROM public.sanction_case_decisions d
            WHERE d.id = NEW.decision_id AND d.organization_id = NEW.organization_id;
    ELSIF TG_TABLE_NAME IN ('sanction_case_events', 'sanction_effect_applications', 'sanction_match_eligibility') THEN
        NEW.created_at := clock_timestamp();
    ELSE
        RAISE EXCEPTION 'SANCTION_INVALID_TRANSACTION_SOURCE' USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.sanction_record_act_time() FROM PUBLIC, bracket_app;

CREATE TRIGGER zz_sanction_record_act_time BEFORE INSERT ON public.sanction_case_decisions
    FOR EACH ROW EXECUTE FUNCTION public.sanction_record_act_time();
CREATE TRIGGER zz_sanction_record_act_time BEFORE INSERT ON public.sanction_resolutions
    FOR EACH ROW EXECUTE FUNCTION public.sanction_record_act_time();
CREATE TRIGGER zz_sanction_record_act_time BEFORE INSERT ON public.sanction_case_events
    FOR EACH ROW EXECUTE FUNCTION public.sanction_record_act_time();
CREATE TRIGGER zz_sanction_record_act_time BEFORE INSERT ON public.sanction_effect_applications
    FOR EACH ROW EXECUTE FUNCTION public.sanction_record_act_time();
CREATE TRIGGER zz_sanction_record_act_time BEFORE INSERT ON public.sanction_match_eligibility
    FOR EACH ROW EXECUTE FUNCTION public.sanction_record_act_time();

COMMIT;
