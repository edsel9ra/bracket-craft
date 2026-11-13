BEGIN;

CREATE FUNCTION public.record_sanction_email_delivery(target_event UUID)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE notice public.sanction_notifications;
BEGIN
    notice := public.sanction_claimed_notice(target_event);
    IF notice.channel <> 'email' THEN RAISE EXCEPTION 'SANCTION_EMAIL_NOTICE_REQUIRED' USING ERRCODE='42501'; END IF;
    INSERT INTO public.sanction_notification_deliveries(organization_id,notification_id,outcome)
        VALUES (notice.organization_id,notice.id,'delivered') ON CONFLICT DO NOTHING;
END;
$$;
REVOKE ALL ON FUNCTION public.record_sanction_email_delivery(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.record_sanction_email_delivery(UUID) TO bracket_app;

COMMIT;
