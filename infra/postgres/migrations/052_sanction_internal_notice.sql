BEGIN;

CREATE FUNCTION public.sanction_internal_notice_payload(target_notice UUID)
RETURNS JSONB LANGUAGE SQL STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
    SELECT jsonb_build_object('id',n.id,'case_id',n.case_id,'notification_type',n.notification_type,
        'reason',n.reason,'created_at',n.created_at,'decision',d.decision)
    FROM public.sanction_notifications n
    LEFT JOIN public.sanction_case_decisions d ON d.id=n.decision_id AND d.organization_id=n.organization_id
    WHERE n.id=target_notice AND n.channel='internal' AND public.sanction_notice_visible(n.id)
        AND EXISTS (SELECT 1 FROM public.sanction_notification_deliveries delivery
            WHERE delivery.notification_id=n.id AND delivery.organization_id=n.organization_id AND delivery.outcome='delivered');
$$;
REVOKE ALL ON FUNCTION public.sanction_internal_notice_payload(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sanction_internal_notice_payload(UUID) TO bracket_app;

COMMIT;
