BEGIN;

-- Member management is an organization-level capability. Keep the catalog and
-- already materialized organization roles in sync for existing installations.
UPDATE public.role_definitions
SET system_permissions = system_permissions || '["MANAGE_MEMBERS"]'::jsonb
WHERE code IN ('owner', 'administrator')
  AND NOT system_permissions @> '["MANAGE_MEMBERS"]'::jsonb;

UPDATE public.roles r
SET permissions = r.permissions || '["MANAGE_MEMBERS"]'::jsonb
FROM public.role_definitions rd
WHERE rd.id = r.role_definition_id
  AND rd.code IN ('owner', 'administrator')
  AND NOT r.permissions @> '["MANAGE_MEMBERS"]'::jsonb;

CREATE TABLE public.organization_invitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    role_code VARCHAR(50) NOT NULL CHECK (
        role_code IN ('administrator', 'operator', 'referee', 'viewer')
    ),
    token_hash CHAR(64) NOT NULL,
    token_encrypted BYTEA NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'accepted', 'expired', 'revoked')
    ),
    invited_by_member_id UUID NOT NULL,
    accepted_by_user_id UUID REFERENCES public.users(id) ON DELETE SET NULL,
    accepted_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (invited_by_member_id, organization_id)
        REFERENCES public.organization_users(id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_organization_invitation_token_hash UNIQUE (token_hash),
    CONSTRAINT chk_organization_invitation_email CHECK (email = LOWER(email)),
    CONSTRAINT chk_organization_invitation_dates CHECK (
        (status = 'accepted' AND accepted_at IS NOT NULL)
        OR status <> 'accepted'
    )
);

CREATE INDEX idx_organization_invitations_org_status
    ON public.organization_invitations (organization_id, status, created_at DESC);

CREATE INDEX idx_organization_invitations_expiration
    ON public.organization_invitations (expires_at)
    WHERE status = 'pending';

CREATE UNIQUE INDEX uq_pending_organization_invitation_email
    ON public.organization_invitations (organization_id, LOWER(email))
    WHERE status = 'pending';

ALTER TABLE public.organization_invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_invitations FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_policy ON public.organization_invitations
    FOR ALL
    USING (
        organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND public.fn_verify_user_org_membership(organization_id)
    )
    WITH CHECK (
        organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND public.fn_verify_user_org_membership(organization_id)
    );

-- The public invitation page needs a narrowly scoped read path. It only accepts
-- a token digest and never returns the encrypted token or the user password.
CREATE OR REPLACE FUNCTION public.get_organization_invitation_by_token(
    p_token_hash CHAR(64)
)
RETURNS TABLE (
    invitation_id UUID,
    organization_id UUID,
    organization_name VARCHAR,
    email VARCHAR,
    role_code VARCHAR,
    expires_at TIMESTAMPTZ,
    status VARCHAR,
    requires_login BOOLEAN
)
LANGUAGE SQL
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT i.id,
           i.organization_id,
           o.name,
           i.email,
           i.role_code,
           i.expires_at,
           CASE
               WHEN i.status = 'pending' AND i.expires_at <= CURRENT_TIMESTAMP THEN 'expired'
               ELSE i.status
           END::VARCHAR,
           EXISTS (
               SELECT 1
               FROM public.users u
               WHERE LOWER(u.email) = i.email
                 AND u.is_active = TRUE
           )
    FROM public.organization_invitations i
    JOIN public.organizations o ON o.id = i.organization_id
    WHERE i.token_hash = p_token_hash
      AND o.is_active = TRUE;
$$;

-- Atomically validates and consumes an invitation. The function is deliberately
-- the only public write path so token reuse and membership races fail closed.
CREATE OR REPLACE FUNCTION public.accept_organization_invitation(
    p_token_hash CHAR(64),
    p_password_hash VARCHAR(255),
    p_full_name VARCHAR(100)
)
RETURNS TABLE (
    user_id UUID,
    organization_id UUID,
    organization_user_id UUID,
    role_code VARCHAR,
    created_user BOOLEAN
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_invitation_id UUID;
    v_organization_id UUID;
    v_email VARCHAR(255);
    v_role_code VARCHAR(50);
    v_expires_at TIMESTAMPTZ;
    v_status VARCHAR(20);
    v_organization_active BOOLEAN;
    v_user_id UUID;
    v_existing_user_id UUID;
    v_actor_id UUID;
    v_member_id UUID;
    v_role_id UUID;
    v_role_definition_id UUID;
    v_role_name VARCHAR(50);
    v_permissions JSONB;
    v_created_user BOOLEAN := FALSE;
BEGIN
    SELECT i.id,
           i.organization_id,
           i.email,
           i.role_code,
           i.expires_at,
           i.status,
           o.is_active
    INTO v_invitation_id,
         v_organization_id,
         v_email,
         v_role_code,
         v_expires_at,
         v_status,
         v_organization_active
    FROM public.organization_invitations i
    JOIN public.organizations o ON o.id = i.organization_id
    WHERE i.token_hash = p_token_hash
    FOR UPDATE OF i;

    IF NOT FOUND OR v_organization_active IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'La invitación no existe o ya no está disponible' USING ERRCODE = 'P0001';
    END IF;
    IF v_status <> 'pending' THEN
        RAISE EXCEPTION 'La invitación ya fue utilizada o revocada' USING ERRCODE = 'P0001';
    END IF;
    IF v_expires_at <= CURRENT_TIMESTAMP THEN
        UPDATE public.organization_invitations
        SET status = 'expired', updated_at = CURRENT_TIMESTAMP
        WHERE id = v_invitation_id;
        RAISE EXCEPTION 'La invitación expiró' USING ERRCODE = 'P0001';
    END IF;

    v_actor_id := NULLIF(current_setting('app.current_user_id', true), '')::UUID;
    SELECT u.id
    INTO v_existing_user_id
    FROM public.users u
    WHERE LOWER(u.email) = v_email
    FOR UPDATE;

    IF v_existing_user_id IS NOT NULL THEN
        IF v_actor_id IS NULL OR v_actor_id <> v_existing_user_id THEN
            RAISE EXCEPTION 'Debe iniciar sesión con el usuario de la invitación' USING ERRCODE = '42501';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.users u
            WHERE u.id = v_existing_user_id AND u.is_active = TRUE
        ) THEN
            RAISE EXCEPTION 'La cuenta está desactivada' USING ERRCODE = '42501';
        END IF;
        v_user_id := v_existing_user_id;
    ELSE
        IF NULLIF(BTRIM(p_password_hash), '') IS NULL OR NULLIF(BTRIM(p_full_name), '') IS NULL THEN
            RAISE EXCEPTION 'La contraseña y el nombre son obligatorios para crear la cuenta' USING ERRCODE = '22023';
        END IF;
        INSERT INTO public.users (email, password_hash, full_name)
        VALUES (v_email, p_password_hash, BTRIM(p_full_name))
        RETURNING id INTO v_user_id;
        v_created_user := TRUE;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.organization_users ou
        WHERE ou.organization_id = v_organization_id
          AND ou.user_id = v_user_id
    ) THEN
        RAISE EXCEPTION 'El usuario ya pertenece a la organización' USING ERRCODE = '23505';
    END IF;

    SELECT rd.id, rd.name, rd.system_permissions
    INTO STRICT v_role_definition_id, v_role_name, v_permissions
    FROM public.role_definitions rd
    WHERE rd.code = v_role_code
      AND rd.code <> 'owner';

    INSERT INTO public.roles (organization_id, role_definition_id, name, permissions)
    VALUES (v_organization_id, v_role_definition_id, v_role_name, v_permissions)
    ON CONFLICT ON CONSTRAINT uq_role_name_org DO UPDATE
        SET role_definition_id = EXCLUDED.role_definition_id,
            permissions = EXCLUDED.permissions
    RETURNING id INTO v_role_id;

    INSERT INTO public.organization_users (organization_id, user_id, is_active)
    VALUES (v_organization_id, v_user_id, TRUE)
    RETURNING id INTO v_member_id;

    INSERT INTO public.organization_user_roles (organization_id, organization_user_id, role_id)
    VALUES (v_organization_id, v_member_id, v_role_id);

    UPDATE public.organization_invitations
    SET status = 'accepted',
        accepted_by_user_id = v_user_id,
        accepted_at = CURRENT_TIMESTAMP,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = v_invitation_id;

    INSERT INTO public.administrative_audit_logs
        (organization_id, entity_type, entity_id, action, payload, performed_by_member_id)
    VALUES (
        v_organization_id,
        'organization_invitations',
        v_invitation_id,
        'ACCEPT_INVITATION',
        jsonb_build_object('user_id', v_user_id, 'role_code', v_role_code),
        v_member_id
    );

    RETURN QUERY SELECT v_user_id, v_organization_id, v_member_id, v_role_code, v_created_user;
END;
$$;

REVOKE ALL ON FUNCTION public.get_organization_invitation_by_token(CHAR(64)) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.accept_organization_invitation(CHAR(64), VARCHAR(255), VARCHAR(100)) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_organization_invitation_by_token(CHAR(64)) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.accept_organization_invitation(CHAR(64), VARCHAR(255), VARCHAR(100)) TO bracket_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.organization_invitations TO bracket_app;

COMMIT;
