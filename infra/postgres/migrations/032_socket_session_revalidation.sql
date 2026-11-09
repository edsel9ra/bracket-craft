BEGIN;

CREATE FUNCTION public.revalidate_socket_sessions(sockets JSONB)
RETURNS TABLE (sid TEXT, is_valid BOOLEAN)
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $$
DECLARE
    socket JSONB;
    v_organization_id UUID;
    v_user_id UUID;
    previous_org TEXT := current_setting('app.current_organization_id', true);
    previous_user TEXT := current_setting('app.current_user_id', true);
    fingerprint TEXT;
    valid BOOLEAN;
BEGIN
    FOR socket IN SELECT value FROM jsonb_array_elements(sockets)
    LOOP
        BEGIN
            sid := socket->>'sid';
            IF socket->>'scope' = 'public' THEN
                PERFORM set_config('app.current_organization_id', '', true);
                PERFORM set_config('app.current_user_id', '', true);
                SELECT EXISTS (
                    SELECT 1 FROM public.v_public_tournaments t
                    WHERE t.id = (socket->>'tournament_id')::UUID
                ) INTO valid;
            ELSE
                v_organization_id := (socket->>'organization_id')::UUID;
                v_user_id := (socket->>'user_id')::UUID;
                PERFORM set_config('app.current_organization_id', v_organization_id::TEXT, true);
                PERFORM set_config('app.current_user_id', v_user_id::TEXT, true);
                SELECT EXISTS (
                    SELECT 1 FROM public.users u
                    JOIN public.user_sessions s ON s.user_id = u.id
                    WHERE u.id = v_user_id AND u.is_active = TRUE
                      AND s.id = (socket->>'session_id')::UUID
                      AND s.revoked_at IS NULL
                      AND s.expires_at > CURRENT_TIMESTAMP
                      AND public.fn_verify_user_org_membership(v_organization_id)
                ) INTO valid;
                IF valid THEN
                    SELECT md5(string_agg(
                        'organization:' || r.id::TEXT || ':' || COALESCE(rd.code, '')
                        || ':' || r.permissions::TEXT
                        || ':' || COALESCE(rd.system_permissions::TEXT, '[]'),
                        ',' ORDER BY r.id::TEXT
                    )) INTO fingerprint
                    FROM public.organization_users ou
                    JOIN public.organization_user_roles our
                      ON our.organization_user_id = ou.id
                     AND our.organization_id = ou.organization_id
                    JOIN public.roles r
                      ON r.id = our.role_id AND r.organization_id = our.organization_id
                    LEFT JOIN public.role_definitions rd ON rd.id = r.role_definition_id
                    WHERE ou.organization_id = v_organization_id
                      AND ou.user_id = v_user_id AND ou.is_active = TRUE;
                    valid := fingerprint IS NOT DISTINCT FROM (socket->>'role_fingerprint');
                END IF;
            END IF;
            is_valid := valid;
            RETURN NEXT;
        EXCEPTION WHEN OTHERS THEN
            -- Un error de una sesión no desconecta sus sockets ni impide validar las demás.
            CONTINUE;
        END;
    END LOOP;
    PERFORM set_config('app.current_organization_id', COALESCE(previous_org, ''), true);
    PERFORM set_config('app.current_user_id', COALESCE(previous_user, ''), true);
END;
$$;

REVOKE ALL ON FUNCTION public.revalidate_socket_sessions(JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.revalidate_socket_sessions(JSONB) TO bracket_app;

COMMIT;
