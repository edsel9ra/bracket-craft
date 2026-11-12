BEGIN;

ALTER TABLE public.administrative_audit_logs
    ADD COLUMN performed_by_user_id UUID REFERENCES public.users(id) ON DELETE RESTRICT,
    ALTER COLUMN performed_by_member_id DROP NOT NULL,
    ADD CONSTRAINT chk_administrative_audit_actor CHECK (
        performed_by_member_id IS NOT NULL OR performed_by_user_id IS NOT NULL
    );

CREATE FUNCTION public.rectification_owner(target_org UUID)
RETURNS UUID LANGUAGE SQL STABLE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT ou.id FROM public.organization_users ou
    JOIN public.organizations o ON o.id = ou.organization_id AND o.is_active
    JOIN public.users u ON u.id = ou.user_id AND u.is_active
    WHERE ou.organization_id = target_org AND ou.is_active
      AND target_org = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
      AND ou.user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
      AND EXISTS (
          SELECT 1 FROM public.organization_user_roles our
          JOIN public.roles r ON r.id = our.role_id AND r.organization_id = our.organization_id
          JOIN public.role_definitions rd ON rd.id = r.role_definition_id AND rd.code = 'owner'
          WHERE our.organization_id = ou.organization_id AND our.organization_user_id = ou.id
      );
$$;

CREATE FUNCTION public.rectification_platform_candidate(target_email TEXT)
RETURNS UUID LANGUAGE SQL STABLE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT u.id FROM public.users u
    JOIN public.platform_admins pa ON pa.user_id = u.id
    WHERE lower(u.email) = lower(btrim(target_email)) AND u.is_active AND pa.is_active
      AND pa.role_code = 'platform_admin'
      AND public.rectification_owner(NULLIF(current_setting('app.current_organization_id', true), '')::UUID) IS NOT NULL;
$$;

CREATE FUNCTION public.rectification_platform_scopes()
RETURNS TABLE (id UUID, organization_id UUID, request_id UUID, granted_by_member_id UUID)
LANGUAGE SQL STABLE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT a.id, a.organization_id, a.request_id, a.granted_by_member_id
    FROM public.match_report_platform_authorizations a
    JOIN public.match_report_rectification_requests q ON q.id = a.request_id
        AND q.organization_id = a.organization_id AND q.status = 'pending'
    JOIN public.platform_admins pa ON pa.user_id = a.platform_admin_user_id
        AND pa.is_active AND pa.role_code = 'platform_admin'
    JOIN public.users actor ON actor.id = pa.user_id AND actor.is_active
    JOIN public.organizations o ON o.id = a.organization_id AND o.is_active
    JOIN public.organization_users owner ON owner.id = a.granted_by_member_id
        AND owner.organization_id = a.organization_id AND owner.is_active
    JOIN public.users owner_user ON owner_user.id = owner.user_id AND owner_user.is_active
    WHERE a.platform_admin_user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
      AND a.revoked_at IS NULL AND a.consumed_at IS NULL
      AND EXISTS (
          SELECT 1 FROM public.organization_user_roles our
          JOIN public.roles r ON r.id = our.role_id AND r.organization_id = our.organization_id
          JOIN public.role_definitions rd ON rd.id = r.role_definition_id AND rd.code = 'owner'
          WHERE our.organization_id = owner.organization_id AND our.organization_user_id = owner.id
      );
$$;

CREATE OR REPLACE FUNCTION public.fn_verify_user_org_membership(target_org_id UUID)
RETURNS BOOLEAN LANGUAGE SQL STABLE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.organization_users ou
        JOIN public.organizations o ON o.id = ou.organization_id
        JOIN public.users u ON u.id = ou.user_id
        WHERE ou.organization_id = target_org_id
          AND ou.user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
          AND ou.is_active = TRUE AND o.is_active = TRUE AND u.is_active = TRUE
    ) OR EXISTS (
        SELECT 1 FROM public.rectification_platform_scopes() a
        WHERE a.id = NULLIF(current_setting('app.rectification_authorization_id', true), '')::UUID
          AND a.organization_id = target_org_id
          AND a.organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
    );
$$;

CREATE FUNCTION public.record_rectification_platform_audit(target_decision UUID)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    INSERT INTO public.platform_audit_logs
        (actor_user_id, action, target_type, target_id, organization_id, payload)
    SELECT d.decided_by_user_id, 'DECIDE_MATCH_REPORT_RECTIFICATION',
        'match_report_rectification_requests', d.request_id, d.organization_id,
        jsonb_build_object('decision_id', d.id, 'authorization_id', d.authorization_id, 'decision', d.decision)
    FROM public.match_report_rectification_decisions d
    JOIN public.rectification_platform_scopes() a ON a.id = d.authorization_id
        AND a.request_id = d.request_id AND a.organization_id = d.organization_id
    WHERE d.id = target_decision AND d.decided_as = 'platform_admin'
      AND d.decided_by_user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
      AND a.id = NULLIF(current_setting('app.rectification_authorization_id', true), '')::UUID
      AND a.organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'RECTIFICATION_AUTHORIZATION_REQUIRED' USING ERRCODE = '42501';
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION public.rectification_owner(UUID),
    public.rectification_platform_candidate(TEXT), public.rectification_platform_scopes(),
    public.record_rectification_platform_audit(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.rectification_owner(UUID),
    public.rectification_platform_candidate(TEXT), public.rectification_platform_scopes(),
    public.record_rectification_platform_audit(UUID) TO bracket_app;

COMMIT;
