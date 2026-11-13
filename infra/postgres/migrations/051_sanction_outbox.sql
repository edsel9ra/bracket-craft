BEGIN;

CREATE FUNCTION public.sanction_enqueue_act_notices()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE recipient UUID; channel TEXT; notice_id UUID; event_id UUID; kind TEXT;
    decision_id UUID; case_event_id UUID;
BEGIN
    IF TG_TABLE_NAME='sanction_case_events' THEN
        IF NEW.event_type NOT IN ('withdrawn','closed_by_rectification') THEN RETURN NEW; END IF;
        kind := NEW.event_type;
        case_event_id := NEW.id;
    ELSE
        kind := 'decision';
        decision_id := NEW.id;
    END IF;
    FOR recipient IN SELECT DISTINCT ou.user_id FROM public.organization_users ou
        WHERE ou.organization_id=NEW.organization_id AND public.sanction_recipient_allowed(NEW.case_id,ou.user_id)
        ORDER BY ou.user_id
    LOOP
        FOREACH channel IN ARRAY ARRAY['internal','email'] LOOP
            notice_id := gen_random_uuid();
            INSERT INTO public.outbox_events(organization_id,event_type,payload)
                VALUES (NEW.organization_id,CASE WHEN channel='email' THEN 'SANCTION_CASE_NOTICE_EMAIL' ELSE 'SANCTION_CASE_NOTICE_INTERNAL' END,
                    jsonb_build_object('notification_id',notice_id::TEXT)) RETURNING id INTO event_id;
            INSERT INTO public.sanction_notifications(id,organization_id,case_id,recipient_user_id,channel,
                notification_type,reason,outbox_event_id,decision_id,case_event_id)
                VALUES (notice_id,NEW.organization_id,NEW.case_id,recipient,channel,kind,NEW.reason,event_id,decision_id,case_event_id);
        END LOOP;
    END LOOP;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.sanction_enqueue_act_notices() FROM PUBLIC;
CREATE TRIGGER trg_zz_sanction_decision_notices AFTER INSERT ON public.sanction_case_decisions
    FOR EACH ROW EXECUTE FUNCTION public.sanction_enqueue_act_notices();
CREATE TRIGGER trg_zz_sanction_event_notices AFTER INSERT ON public.sanction_case_events
    FOR EACH ROW EXECUTE FUNCTION public.sanction_enqueue_act_notices();

COMMIT;
