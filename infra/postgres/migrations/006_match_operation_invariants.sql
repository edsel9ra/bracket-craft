BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM match_officials
        GROUP BY match_id, organization_user_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'No se puede imponer exclusividad de oficiales: existen asignaciones duplicadas';
    END IF;
END;
$$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM match_segments
        WHERE status = 'active'
        GROUP BY match_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'No se puede imponer un segmento activo por partido: existen múltiples segmentos activos';
    END IF;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_match_official_person
    ON match_officials (match_id, organization_user_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_active_match_segment
    ON match_segments (match_id)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS match_segment_interruptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    match_id UUID NOT NULL,
    segment_id UUID NOT NULL,
    reason VARCHAR(30) NOT NULL CHECK (
        reason IN ('lighting_failure', 'weather', 'pitch_invasion', 'other')
    ),
    minute INT NOT NULL CHECK (minute >= 0),
    notes VARCHAR(1000),
    created_by_member_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (match_id, organization_id)
        REFERENCES matches(id, organization_id) ON DELETE CASCADE,
    FOREIGN KEY (segment_id, match_id, organization_id)
        REFERENCES match_segments(id, match_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (created_by_member_id, organization_id)
        REFERENCES organization_users(id, organization_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_match_segment_interruptions_match
    ON match_segment_interruptions (organization_id, match_id, minute, created_at);

ALTER TABLE match_segment_interruptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE match_segment_interruptions FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'match_segment_interruptions'
          AND policyname = 'tenant_isolation_policy'
    ) THEN
        CREATE POLICY tenant_isolation_policy ON match_segment_interruptions
            FOR ALL
            USING (
                organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
                AND fn_verify_user_org_membership(organization_id)
            )
            WITH CHECK (
                organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
                AND fn_verify_user_org_membership(organization_id)
            );
    END IF;
END
$$;

GRANT SELECT, INSERT, UPDATE, DELETE ON match_segment_interruptions TO bracket_app;

COMMIT;
