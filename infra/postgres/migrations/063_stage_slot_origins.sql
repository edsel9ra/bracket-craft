BEGIN;

-- ============================================================================
-- Spec 040 (F2, T1): orígenes de plaza por clasificación y resolución
-- confirmada de la llave.
--
-- 1. `phase_slots.source_type` vuelve a admitir `stage_rank` (la 019 lo había
--    estrechado) con una referencia de forma cerrada (RF-002).
-- 2. `stage_slot_resolutions`: una resolución append-only por llave, con
--    gestor, huella de la clasificación y asignaciones (RF-007, RNF-002).
-- 3. `match_slot_assignments` admite `origin = 'stage_rank'` ligado a su
--    resolución.
-- 4. Excepción acotada de inmutabilidad: en una versión publicada solo se
--    permite INSERT en `stage_teams`, sin grupo, de un equipo que figure en la
--    resolución indicada por `app.stage_slot_resolution_id` para esa fase
--    (RF-003). Ninguna otra tabla ni operación cambia. Todo SECURITY INVOKER.
-- 5. Vista interna `v_public_match_slot_origins` para la etiqueta pública de
--    las plazas sin resolver (§8 del plan).
-- ============================================================================

-- 1. CHECK de source_type, descubierto por catálogo como en la 019.
DO $$
DECLARE
    v_matches INT;
    v_constraint TEXT;
BEGIN
    SELECT count(*), min(con.conname)
    INTO v_matches, v_constraint
    FROM pg_constraint con
    WHERE con.conrelid = 'public.phase_slots'::regclass
      AND con.contype = 'c'
      AND pg_get_constraintdef(con.oid) ~ '\msource_type\M'
      AND pg_get_constraintdef(con.oid) !~ '\msource_reference\M';

    IF v_matches <> 1 THEN
        RAISE EXCEPTION
            'MIGRACION 063: se esperaba exactamente una constraint CHECK sobre phase_slots.source_type y se encontraron %. Corrija el esquema y reintente.',
            v_matches;
    END IF;

    EXECUTE format('ALTER TABLE public.phase_slots DROP CONSTRAINT %I', v_constraint);
END;
$$;

ALTER TABLE public.phase_slots
    ADD CONSTRAINT phase_slots_source_type_check
    CHECK (source_type IN ('direct_team', 'match_result', 'stage_rank'));

ALTER TABLE public.phase_slots DROP CONSTRAINT IF EXISTS chk_phase_slot_stage_rank_reference;
ALTER TABLE public.phase_slots
    ADD CONSTRAINT chk_phase_slot_stage_rank_reference CHECK (
        source_type <> 'stage_rank'
        OR COALESCE((
            jsonb_typeof(source_reference) = 'object'
            AND COALESCE(source_reference->>'source_stage_id', '')
                ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            AND jsonb_typeof(source_reference->'position') = 'number'
            AND (source_reference->>'position') ~ '^[1-9][0-9]{0,2}$'
            AND (
                (
                    source_reference->>'kind' = 'group_position'
                    AND NOT source_reference ? 'ordinal'
                    AND (
                        jsonb_typeof(source_reference->'group_id') IS NULL
                        OR jsonb_typeof(source_reference->'group_id') = 'null'
                        OR (source_reference->>'group_id')
                            ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                    )
                )
                OR (
                    source_reference->>'kind' = 'best_of_position'
                    AND NOT source_reference ? 'group_id'
                    AND jsonb_typeof(source_reference->'ordinal') = 'number'
                    AND (source_reference->>'ordinal') ~ '^[1-9][0-9]{0,2}$'
                )
            )
        ), FALSE)
    );

-- 2. Resoluciones confirmadas.
CREATE TABLE IF NOT EXISTS public.stage_slot_resolutions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    tournament_id UUID NOT NULL,
    tournament_version_id UUID NOT NULL,
    stage_id UUID NOT NULL,
    resolved_by_member_id UUID NOT NULL,
    standings_fingerprint CHAR(64) NOT NULL CHECK (standings_fingerprint ~ '^[0-9a-f]{64}$'),
    assignments JSONB NOT NULL
        CHECK (jsonb_typeof(assignments) = 'array' AND jsonb_array_length(assignments) >= 2),
    resolved_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_stage_slot_resolution_stage UNIQUE (stage_id),
    CONSTRAINT uq_stage_slot_resolution_context UNIQUE (id, organization_id),
    FOREIGN KEY (stage_id, tournament_version_id, tournament_id, organization_id)
        REFERENCES public.stages(id, tournament_version_id, tournament_id, organization_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (resolved_by_member_id, organization_id)
        REFERENCES public.organization_users(id, organization_id) ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION public.validate_stage_slot_resolution()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.stages s
        JOIN public.tournament_versions tv
          ON tv.id = s.tournament_version_id
         AND tv.organization_id = s.organization_id
        WHERE s.id = NEW.stage_id
          AND s.organization_id = NEW.organization_id
          AND s.stage_type IN ('single_elimination', 'double_elimination')
          AND tv.status = 'published'
    ) THEN
        RAISE EXCEPTION 'Solo se resuelven llaves de una versión publicada'
            USING ERRCODE = 'ZZ409';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_stage_slot_resolution ON public.stage_slot_resolutions;
CREATE TRIGGER trg_validate_stage_slot_resolution
BEFORE INSERT ON public.stage_slot_resolutions
FOR EACH ROW EXECUTE FUNCTION public.validate_stage_slot_resolution();

ALTER TABLE public.stage_slot_resolutions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stage_slot_resolutions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy ON public.stage_slot_resolutions;
CREATE POLICY tenant_isolation_policy ON public.stage_slot_resolutions FOR ALL
    USING (
        organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND public.fn_verify_user_org_membership(organization_id)
    )
    WITH CHECK (
        organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND public.fn_verify_user_org_membership(organization_id)
    );
REVOKE ALL ON public.stage_slot_resolutions FROM PUBLIC;
REVOKE ALL ON public.stage_slot_resolutions FROM bracket_app;
GRANT SELECT, INSERT ON public.stage_slot_resolutions TO bracket_app;

-- 3. Asignaciones de plaza derivadas de una resolución.
ALTER TABLE public.match_slot_assignments
    ADD COLUMN IF NOT EXISTS stage_slot_resolution_id UUID;

DO $$
DECLARE
    v_matches INT;
    v_constraint TEXT;
BEGIN
    SELECT count(*), min(con.conname)
    INTO v_matches, v_constraint
    FROM pg_constraint con
    WHERE con.conrelid = 'public.match_slot_assignments'::regclass
      AND con.contype = 'c'
      AND pg_get_constraintdef(con.oid) ~ '\morigin\M'
      AND pg_get_constraintdef(con.oid) ~ 'manual';

    IF v_matches <> 1 THEN
        RAISE EXCEPTION
            'MIGRACION 063: se esperaba exactamente una constraint CHECK con la lista de match_slot_assignments.origin y se encontraron %. Corrija el esquema y reintente.',
            v_matches;
    END IF;

    EXECUTE format('ALTER TABLE public.match_slot_assignments DROP CONSTRAINT %I', v_constraint);
END;
$$;

ALTER TABLE public.match_slot_assignments
    ADD CONSTRAINT match_slot_assignments_origin_check
    CHECK (origin IN ('advancement_link', 'manual', 'rectification', 'stage_rank'));

ALTER TABLE public.match_slot_assignments
    DROP CONSTRAINT IF EXISTS chk_match_slot_assignment_stage_rank;
ALTER TABLE public.match_slot_assignments
    ADD CONSTRAINT chk_match_slot_assignment_stage_rank
    CHECK ((origin = 'stage_rank') = (stage_slot_resolution_id IS NOT NULL));

ALTER TABLE public.match_slot_assignments
    DROP CONSTRAINT IF EXISTS fk_match_slot_assignment_stage_slot_resolution;
ALTER TABLE public.match_slot_assignments
    ADD CONSTRAINT fk_match_slot_assignment_stage_slot_resolution
    FOREIGN KEY (stage_slot_resolution_id, organization_id)
    REFERENCES public.stage_slot_resolutions(id, organization_id) ON DELETE RESTRICT;

-- 4. Inmutabilidad con la excepción acotada de la resolución.
CREATE OR REPLACE FUNCTION public.prevent_published_structure_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_version_id UUID;
    v_resolution_id UUID;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        v_version_id := OLD.tournament_version_id;
        IF EXISTS (
            SELECT 1
            FROM tournament_versions tv
            WHERE tv.id = v_version_id
              AND tv.status IN ('published', 'archived')
        ) THEN
            RAISE EXCEPTION 'La versión publicada o archivada no puede modificarse'
                USING ERRCODE = 'ZZ409';
        END IF;
    END IF;

    IF TG_OP <> 'DELETE' THEN
        v_version_id := NEW.tournament_version_id;
        IF EXISTS (
            SELECT 1
            FROM tournament_versions tv
            WHERE tv.id = v_version_id
              AND tv.status IN ('published', 'archived')
        ) THEN
            v_resolution_id := NULLIF(current_setting('app.stage_slot_resolution_id', true), '')::UUID;
            IF TG_TABLE_NAME = 'stage_teams'
               AND TG_OP = 'INSERT'
               AND NEW.group_id IS NULL
               AND v_resolution_id IS NOT NULL
               AND EXISTS (
                   SELECT 1
                   FROM public.stage_slot_resolutions r
                   JOIN public.tournament_versions tv
                     ON tv.id = r.tournament_version_id
                    AND tv.organization_id = r.organization_id
                    AND tv.status = 'published'
                   WHERE r.id = v_resolution_id
                     AND r.organization_id = NEW.organization_id
                     AND r.tournament_version_id = NEW.tournament_version_id
                     AND r.stage_id = NEW.stage_id
                     AND r.assignments @> jsonb_build_array(
                         jsonb_build_object('team_id', NEW.team_id::text)
                     )
               )
               AND NOT EXISTS (
                   SELECT 1
                   FROM public.stage_teams st
                   WHERE st.stage_id = NEW.stage_id
                     AND st.organization_id = NEW.organization_id
                     AND st.team_id = NEW.team_id
               )
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'No se pueden insertar estructuras en una versión publicada'
                USING ERRCODE = 'ZZ409';
        END IF;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

-- 5. Etiqueta pública de las plazas sin resolver.
CREATE OR REPLACE VIEW public.v_public_match_slot_origins
WITH (security_barrier = true) AS
SELECT
    m.organization_id,
    m.tournament_id,
    m.id AS match_id,
    side.side,
    ps.source_reference->>'kind' AS origin_kind,
    (ps.source_reference->>'source_stage_id')::UUID AS source_stage_id,
    g.name AS group_name,
    (ps.source_reference->>'position')::INT AS position,
    (ps.source_reference->>'ordinal')::INT AS ordinal
FROM public.matches m
JOIN public.tournaments tr
  ON tr.id = m.tournament_id
 AND tr.organization_id = m.organization_id
 AND tr.published_version_id = m.tournament_version_id
JOIN public.v_public_tournaments vt
  ON vt.id = tr.id
 AND vt.organization_id = tr.organization_id
CROSS JOIN LATERAL (
    VALUES ('home', m.home_slot_id, m.home_team_id),
           ('away', m.away_slot_id, m.away_team_id)
) AS side(side, slot_id, team_id)
JOIN public.phase_slots ps
  ON ps.id = side.slot_id
 AND ps.stage_id = m.stage_id
 AND ps.organization_id = m.organization_id
 AND ps.source_type = 'stage_rank'
LEFT JOIN public.groups g
  ON g.id = (ps.source_reference->>'group_id')::UUID
 AND g.organization_id = ps.organization_id
WHERE side.team_id IS NULL;

REVOKE ALL ON public.v_public_match_slot_origins FROM PUBLIC;
GRANT SELECT ON public.v_public_match_slot_origins TO bracket_app;

COMMIT;
