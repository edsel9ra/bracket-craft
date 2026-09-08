BEGIN;

CREATE OR REPLACE FUNCTION public.platform_set_organization_active(
    p_organization_id UUID,
    p_is_active BOOLEAN
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_actor_id UUID := NULLIF(current_setting('app.current_user_id', true), '')::UUID;
    v_old_active BOOLEAN;
BEGIN
    IF public.fn_platform_actor_role() <> 'platform_admin' THEN
        RAISE EXCEPTION 'Permiso de plataforma requerido' USING ERRCODE = '42501';
    END IF;

    SELECT is_active INTO v_old_active
    FROM public.organizations
    WHERE id = p_organization_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;
    IF v_old_active IS NOT DISTINCT FROM p_is_active THEN
        RETURN TRUE;
    END IF;

    UPDATE public.organizations SET is_active = p_is_active WHERE id = p_organization_id;
    IF p_is_active = FALSE THEN
        UPDATE public.user_sessions
        SET revoked_at = CURRENT_TIMESTAMP
        WHERE user_id IN (
            SELECT ou.user_id
            FROM public.organization_users ou
            WHERE ou.organization_id = p_organization_id
        )
          AND revoked_at IS NULL;
    END IF;

    INSERT INTO public.platform_audit_logs
        (actor_user_id, action, target_type, target_id, organization_id, payload)
    VALUES
        (v_actor_id, 'SET_ORGANIZATION_ACTIVE', 'organizations', p_organization_id,
         p_organization_id, jsonb_build_object('before', v_old_active, 'after', p_is_active));
    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION public.platform_set_membership_active(
    p_organization_id UUID,
    p_organization_user_id UUID,
    p_is_active BOOLEAN
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_actor_id UUID := NULLIF(current_setting('app.current_user_id', true), '')::UUID;
    v_target_user_id UUID;
    v_old_active BOOLEAN;
BEGIN
    IF public.fn_platform_actor_role() <> 'platform_admin' THEN
        RAISE EXCEPTION 'Permiso de plataforma requerido' USING ERRCODE = '42501';
    END IF;

    SELECT ou.user_id, ou.is_active
    INTO v_target_user_id, v_old_active
    FROM public.organization_users ou
    WHERE ou.id = p_organization_user_id
      AND ou.organization_id = p_organization_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;
    IF v_old_active IS NOT DISTINCT FROM p_is_active THEN
        RETURN TRUE;
    END IF;

    IF p_is_active = FALSE
       AND EXISTS (
           SELECT 1
           FROM public.organization_user_roles our
           JOIN public.roles r ON r.id = our.role_id AND r.organization_id = our.organization_id
           JOIN public.role_definitions rd ON rd.id = r.role_definition_id
           WHERE our.organization_id = p_organization_id
             AND our.organization_user_id = p_organization_user_id
             AND rd.code = 'owner'
       )
       AND NOT EXISTS (
           SELECT 1
           FROM public.organization_user_roles other_our
           JOIN public.roles other_r
             ON other_r.id = other_our.role_id
            AND other_r.organization_id = other_our.organization_id
           JOIN public.role_definitions other_rd ON other_rd.id = other_r.role_definition_id
           JOIN public.organization_users other_ou
             ON other_ou.id = other_our.organization_user_id
            AND other_ou.organization_id = other_our.organization_id
           WHERE other_our.organization_id = p_organization_id
             AND other_ou.is_active = TRUE
             AND other_our.organization_user_id <> p_organization_user_id
             AND other_rd.code = 'owner'
       ) THEN
        RAISE EXCEPTION 'La organización debe conservar al menos un propietario activo' USING ERRCODE = '23514';
    END IF;

    UPDATE public.organization_users
    SET is_active = p_is_active
    WHERE id = p_organization_user_id AND organization_id = p_organization_id;
    IF p_is_active = FALSE THEN
        UPDATE public.user_sessions
        SET revoked_at = CURRENT_TIMESTAMP
        WHERE user_id = v_target_user_id AND revoked_at IS NULL;
    END IF;

    INSERT INTO public.platform_audit_logs
        (actor_user_id, action, target_type, target_id, organization_id, payload)
    VALUES
        (v_actor_id, 'SET_MEMBERSHIP_ACTIVE', 'organization_users', p_organization_user_id,
         p_organization_id, jsonb_build_object('before', v_old_active, 'after', p_is_active));
    RETURN TRUE;
END;
$$;

COMMIT;
