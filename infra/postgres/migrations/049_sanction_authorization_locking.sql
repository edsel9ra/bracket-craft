BEGIN;

CREATE FUNCTION public.sanction_lock_authorization_case(target_case UUID)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
    IF public.sanction_owner(NULLIF(current_setting('app.current_organization_id',true),'')::UUID) IS NULL THEN
        RAISE EXCEPTION 'SANCTION_OWNER_AUTHORIZATION_REQUIRED' USING ERRCODE='42501';
    END IF;
    PERFORM public.sanction_lock_case(target_case);
END;
$$;
REVOKE ALL ON FUNCTION public.sanction_lock_authorization_case(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sanction_lock_authorization_case(UUID) TO bracket_app;

COMMIT;
