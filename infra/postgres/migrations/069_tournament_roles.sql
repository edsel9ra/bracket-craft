BEGIN;

-- ============================================================================
-- Spec 049 (F7, T1): operador del torneo.
--
-- Tabla tenant con RLS forzado que asigna a un miembro el único rol por torneo,
-- tournament_operator. Es aditivo: tournament_operator_allows concede en los
-- partidos de ese torneo solo VIEW_MATCH_LIVE_DRAFT, OPERATE_MATCH_LIVE y
-- CLOSE_MATCH_REPORT, y se suma a match_live_has_permission (056) y a
-- sanction_can_operate_match (040). No sustituye a la tabla retirada
-- tournament_user_roles (019). Idempotente: reaplicarla no cambia nada.
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.tournament_member_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    tournament_id UUID NOT NULL,
    organization_user_id UUID NOT NULL,
    role_code TEXT NOT NULL,
    created_by_member_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_tournament_member_role_code CHECK (role_code IN ('tournament_operator')),
    CONSTRAINT uq_tournament_member_role UNIQUE (tournament_id, organization_user_id, role_code),
    CONSTRAINT fk_tournament_member_role_tournament FOREIGN KEY (tournament_id, organization_id)
        REFERENCES public.tournaments(id, organization_id) ON DELETE CASCADE,
    CONSTRAINT fk_tournament_member_role_member FOREIGN KEY (organization_user_id, organization_id)
        REFERENCES public.organization_users(id, organization_id) ON DELETE CASCADE,
    CONSTRAINT fk_tournament_member_role_creator FOREIGN KEY (created_by_member_id, organization_id)
        REFERENCES public.organization_users(id, organization_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_tournament_member_roles_member
    ON public.tournament_member_roles (organization_id, organization_user_id, tournament_id);

ALTER TABLE public.tournament_member_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tournament_member_roles FORCE ROW LEVEL SECURITY;

REVOKE ALL ON public.tournament_member_roles FROM PUBLIC;
REVOKE ALL ON public.tournament_member_roles FROM bracket_app;
GRANT SELECT, INSERT, DELETE ON public.tournament_member_roles TO bracket_app;

DROP POLICY IF EXISTS tournament_member_roles_tenant ON public.tournament_member_roles;
CREATE POLICY tournament_member_roles_tenant ON public.tournament_member_roles FOR ALL TO bracket_app
    USING (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID)
    WITH CHECK (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID);

CREATE OR REPLACE FUNCTION public.tournament_operator_allows(p_organization_id UUID, p_match_id UUID, p_permission TEXT)
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY INVOKER SET search_path = pg_catalog, public AS $$
    SELECT COALESCE(
        p_permission IN ('VIEW_MATCH_LIVE_DRAFT', 'OPERATE_MATCH_LIVE', 'CLOSE_MATCH_REPORT')
        AND p_organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND public.fn_verify_user_org_membership(p_organization_id)
        AND EXISTS (
            SELECT 1 FROM public.matches m
            JOIN public.tournament_member_roles t
              ON t.tournament_id = m.tournament_id AND t.organization_id = m.organization_id
            JOIN public.organization_users ou
              ON ou.id = t.organization_user_id AND ou.organization_id = t.organization_id AND ou.is_active
            WHERE m.id = p_match_id AND m.organization_id = p_organization_id
                AND t.role_code = 'tournament_operator'
                AND ou.user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
        ), FALSE)
$$;
REVOKE ALL ON FUNCTION public.tournament_operator_allows(UUID, UUID, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.tournament_operator_allows(UUID, UUID, TEXT) TO bracket_app;

CREATE OR REPLACE FUNCTION public.match_live_has_permission(p_organization_id UUID, p_match_id UUID, p_permission TEXT)
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY INVOKER SET search_path = pg_catalog, public AS $$
    SELECT public.fn_verify_user_org_membership(p_organization_id) AND (EXISTS (
        SELECT 1 FROM public.organization_users ou
        JOIN public.organization_user_roles our ON our.organization_user_id = ou.id AND our.organization_id = ou.organization_id
        JOIN public.roles r ON r.id = our.role_id AND r.organization_id = our.organization_id
        LEFT JOIN public.role_definitions rd ON rd.id = r.role_definition_id
        WHERE ou.organization_id = p_organization_id AND ou.is_active
            AND ou.user_id = NULLIF(current_setting('app.current_user_id',true),'')::UUID
            AND r.permissions @> jsonb_build_array(p_permission)
            AND (rd.code IN ('owner','administrator','operator') OR EXISTS (
                SELECT 1 FROM public.match_officials mo WHERE mo.organization_id = ou.organization_id
                    AND mo.match_id = p_match_id AND mo.organization_user_id = ou.id)))
        OR public.tournament_operator_allows(p_organization_id, p_match_id, p_permission))
$$;
REVOKE ALL ON FUNCTION public.match_live_has_permission(UUID, UUID, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.match_live_has_permission(UUID, UUID, TEXT) TO bracket_app;

CREATE OR REPLACE FUNCTION public.sanction_can_operate_match(target_org UUID, target_match UUID)
RETURNS BOOLEAN LANGUAGE SQL STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT COALESCE(target_org = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND (EXISTS (
            SELECT 1 FROM public.matches m
            JOIN public.organizations o ON o.id = m.organization_id AND o.is_active
            JOIN public.organization_users ou ON ou.organization_id = m.organization_id AND ou.is_active
            JOIN public.users u ON u.id = ou.user_id AND u.is_active
            JOIN public.organization_user_roles our ON our.organization_user_id = ou.id AND our.organization_id = ou.organization_id
            JOIN public.roles r ON r.id = our.role_id AND r.organization_id = ou.organization_id
            JOIN public.role_definitions rd ON rd.id = r.role_definition_id
            WHERE m.id = target_match AND m.organization_id = target_org
                AND ou.user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
                AND r.permissions @> '["CLOSE_MATCH_REPORT"]'::JSONB
                AND (rd.code IN ('owner', 'administrator', 'operator') OR EXISTS (
                    SELECT 1 FROM public.match_officials mo WHERE mo.match_id = m.id
                        AND mo.organization_id = target_org AND mo.organization_user_id = ou.id))
        ) OR public.tournament_operator_allows(target_org, target_match, 'CLOSE_MATCH_REPORT')), FALSE);
$$;
REVOKE ALL ON FUNCTION public.sanction_can_operate_match(UUID, UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sanction_can_operate_match(UUID, UUID) TO bracket_app;

COMMIT;
