BEGIN;

CREATE OR REPLACE FUNCTION public.platform_list_memberships(
    p_organization_id UUID,
    p_limit INTEGER DEFAULT 50,
    p_offset INTEGER DEFAULT 0
)
RETURNS TABLE (
    organization_user_id UUID,
    user_id UUID,
    email VARCHAR,
    full_name VARCHAR,
    is_active BOOLEAN,
    role_codes TEXT[]
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF public.fn_platform_actor_role() IS NULL THEN
        RAISE EXCEPTION 'Permiso de plataforma requerido' USING ERRCODE = '42501';
    END IF;

    RETURN QUERY
    SELECT ou.id,
           u.id,
           u.email,
           u.full_name,
           ou.is_active,
           COALESCE(ARRAY_AGG(DISTINCT rd.code ORDER BY rd.code) FILTER (WHERE rd.code IS NOT NULL), ARRAY[]::TEXT[])::TEXT[]
    FROM public.organization_users ou
    JOIN public.users u ON u.id = ou.user_id
    LEFT JOIN public.organization_user_roles our
      ON our.organization_user_id = ou.id
     AND our.organization_id = ou.organization_id
    LEFT JOIN public.roles r
      ON r.id = our.role_id
     AND r.organization_id = our.organization_id
    LEFT JOIN public.role_definitions rd ON rd.id = r.role_definition_id
    WHERE ou.organization_id = p_organization_id
    GROUP BY ou.id, u.id
    ORDER BY u.full_name, u.id
    LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 50), 100))
    OFFSET GREATEST(COALESCE(p_offset, 0), 0);
END;
$$;

COMMIT;
