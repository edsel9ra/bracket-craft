BEGIN;

CREATE TABLE public.match_report_rectification_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    match_id UUID NOT NULL,
    base_version_number INT NOT NULL CHECK (base_version_number >= 1),
    proposed_report JSONB NOT NULL CHECK (jsonb_typeof(proposed_report) = 'object'),
    reason TEXT NOT NULL CHECK (btrim(reason) <> ''),
    evidence TEXT,
    requested_by_user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    requested_by_member_id UUID NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'rejected', 'withdrawn', 'published')),
    withdrawn_at TIMESTAMPTZ,
    resulting_version_id UUID,
    UNIQUE (id, organization_id),
    UNIQUE (id, match_id, organization_id),
    FOREIGN KEY (match_id, organization_id)
        REFERENCES public.matches(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (requested_by_member_id, organization_id)
        REFERENCES public.organization_users(id, organization_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX uq_match_report_pending_request
    ON public.match_report_rectification_requests (match_id)
    WHERE status = 'pending';

CREATE TABLE public.match_report_platform_authorizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    request_id UUID NOT NULL,
    granted_by_member_id UUID NOT NULL,
    platform_admin_user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    reason TEXT NOT NULL CHECK (btrim(reason) <> ''),
    granted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMPTZ,
    consumed_at TIMESTAMPTZ,
    UNIQUE (id, organization_id),
    UNIQUE (id, request_id, organization_id),
    FOREIGN KEY (request_id, organization_id)
        REFERENCES public.match_report_rectification_requests(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (granted_by_member_id, organization_id)
        REFERENCES public.organization_users(id, organization_id) ON DELETE RESTRICT
);

CREATE TABLE public.match_report_rectification_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    request_id UUID NOT NULL UNIQUE,
    decision VARCHAR(10) NOT NULL CHECK (decision IN ('approve', 'reject')),
    reason TEXT NOT NULL CHECK (btrim(reason) <> ''),
    decided_by_user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    decided_by_member_id UUID,
    decided_as VARCHAR(20) NOT NULL CHECK (decided_as IN ('member', 'platform_admin')),
    authorization_id UUID,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, organization_id),
    FOREIGN KEY (request_id, organization_id)
        REFERENCES public.match_report_rectification_requests(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (decided_by_member_id, organization_id)
        REFERENCES public.organization_users(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (authorization_id, request_id, organization_id)
        REFERENCES public.match_report_platform_authorizations(id, request_id, organization_id) ON DELETE RESTRICT
);

CREATE TABLE public.match_report_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    match_id UUID NOT NULL,
    version_number INT NOT NULL CHECK (version_number >= 2),
    supersedes_version_number INT NOT NULL CHECK (
        supersedes_version_number = version_number - 1
    ),
    resolution_type VARCHAR(30) NOT NULL CHECK (
        resolution_type IN ('regular', 'extra_time', 'penalties', 'walkover', 'administrative')
    ),
    resolution_reason TEXT,
    home_score_regular INT CHECK (home_score_regular >= 0),
    away_score_regular INT CHECK (away_score_regular >= 0),
    home_score INT NOT NULL CHECK (home_score >= 0),
    away_score INT NOT NULL CHECK (away_score >= 0),
    home_penalties INT CHECK (home_penalties >= 0),
    away_penalties INT CHECK (away_penalties >= 0),
    winner_team_id UUID,
    request_id UUID NOT NULL UNIQUE,
    published_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_by_user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    UNIQUE (id, organization_id),
    UNIQUE (id, match_id, organization_id),
    UNIQUE (match_id, version_number),
    FOREIGN KEY (match_id, organization_id)
        REFERENCES public.matches(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (request_id, match_id, organization_id)
        REFERENCES public.match_report_rectification_requests(id, match_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (winner_team_id, organization_id)
        REFERENCES public.teams(id, organization_id) ON DELETE RESTRICT
);

ALTER TABLE public.match_report_rectification_requests
    ADD CONSTRAINT fk_rectification_resulting_version
    FOREIGN KEY (resulting_version_id, match_id, organization_id)
    REFERENCES public.match_report_versions(id, match_id, organization_id) ON DELETE RESTRICT;

CREATE TABLE public.match_report_version_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    version_id UUID NOT NULL,
    match_id UUID NOT NULL,
    segment_id UUID NOT NULL,
    team_id UUID NOT NULL,
    beneficiary_team_id UUID,
    player_id UUID NOT NULL,
    event_type VARCHAR(30) NOT NULL CHECK (
        event_type IN ('goal', 'own_goal', 'penalty_goal', 'yellow_card', 'red_card', 'substitution', 'foul')
    ),
    minute INT NOT NULL CHECK (minute BETWEEN 0 AND 180),
    added_minute INT NOT NULL DEFAULT 0 CHECK (added_minute BETWEEN 0 AND 30),
    client_event_id VARCHAR(100) NOT NULL,
    assist_player_id UUID,
    player_out_id UUID,
    player_in_id UUID,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_voided BOOLEAN NOT NULL DEFAULT FALSE,
    voided_at TIMESTAMPTZ,
    voided_by_member_id UUID,
    void_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, organization_id),
    UNIQUE (version_id, client_event_id),
    FOREIGN KEY (version_id, match_id, organization_id)
        REFERENCES public.match_report_versions(id, match_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (segment_id, match_id, organization_id)
        REFERENCES public.match_segments(id, match_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (team_id, organization_id)
        REFERENCES public.teams(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (beneficiary_team_id, organization_id)
        REFERENCES public.teams(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (player_id, organization_id)
        REFERENCES public.players(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (assist_player_id, organization_id)
        REFERENCES public.players(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (player_out_id, organization_id)
        REFERENCES public.players(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (player_in_id, organization_id)
        REFERENCES public.players(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (voided_by_member_id, organization_id)
        REFERENCES public.organization_users(id, organization_id) ON DELETE RESTRICT
);

CREATE TABLE public.match_report_rectification_effects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    version_id UUID NOT NULL,
    effect_type VARCHAR(40) NOT NULL CHECK (effect_type IN (
        'standings', 'sanction_created', 'sanction_annulled', 'advancement',
        'tiebreak_draw_invalidated', 'impact_opened', 'outbox'
    )),
    entity_type VARCHAR(100) NOT NULL,
    entity_id UUID NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, organization_id),
    FOREIGN KEY (version_id, organization_id)
        REFERENCES public.match_report_versions(id, organization_id) ON DELETE RESTRICT
);

CREATE TABLE public.match_report_rectification_notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    request_id UUID,
    version_id UUID,
    channel VARCHAR(20) NOT NULL CHECK (channel IN ('realtime', 'email')),
    notification_type VARCHAR(100) NOT NULL,
    recipient_user_id UUID REFERENCES public.users(id) ON DELETE RESTRICT,
    outbox_event_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (request_id IS NOT NULL OR version_id IS NOT NULL),
    CHECK (channel <> 'realtime' OR recipient_user_id IS NULL),
    UNIQUE (id, organization_id),
    FOREIGN KEY (request_id, organization_id)
        REFERENCES public.match_report_rectification_requests(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (version_id, organization_id)
        REFERENCES public.match_report_versions(id, organization_id) ON DELETE RESTRICT
);

CREATE TABLE public.competitive_impact_procedures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    version_id UUID NOT NULL,
    match_id UUID NOT NULL,
    affected_items JSONB NOT NULL CHECK (jsonb_typeof(affected_items) = 'array'),
    status VARCHAR(10) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    resolution VARCHAR(20) CHECK (resolution = 'keep_as_played'),
    reason TEXT,
    closed_by_user_id UUID REFERENCES public.users(id) ON DELETE RESTRICT,
    closed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, organization_id),
    FOREIGN KEY (version_id, match_id, organization_id)
        REFERENCES public.match_report_versions(id, match_id, organization_id) ON DELETE RESTRICT
);

CREATE TABLE public.player_suspension_annulments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    suspension_id UUID NOT NULL,
    version_id UUID NOT NULL,
    reason TEXT NOT NULL CHECK (btrim(reason) <> ''),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, organization_id),
    UNIQUE (suspension_id),
    FOREIGN KEY (suspension_id, organization_id)
        REFERENCES public.player_suspensions(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (version_id, organization_id)
        REFERENCES public.match_report_versions(id, organization_id) ON DELETE RESTRICT
);

CREATE TABLE public.match_slot_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    tournament_id UUID NOT NULL,
    match_id UUID NOT NULL,
    side VARCHAR(4) NOT NULL CHECK (side IN ('home', 'away')),
    team_id UUID NOT NULL,
    origin VARCHAR(20) NOT NULL CHECK (origin IN ('advancement_link', 'manual', 'rectification')),
    advancement_link_id UUID,
    match_report_version_id UUID,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, organization_id),
    CHECK (origin <> 'advancement_link' OR advancement_link_id IS NOT NULL),
    CHECK (origin <> 'rectification' OR match_report_version_id IS NOT NULL),
    FOREIGN KEY (tournament_id, organization_id)
        REFERENCES public.tournaments(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (team_id, organization_id)
        REFERENCES public.teams(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (match_report_version_id, organization_id)
        REFERENCES public.match_report_versions(id, organization_id) ON DELETE RESTRICT
);

CREATE INDEX idx_match_slot_assignments_slot
    ON public.match_slot_assignments (organization_id, match_id, side, assigned_at, id);

-- Draft schedule regeneration deletes matches and links, not their assignment history.
CREATE FUNCTION public.validate_match_slot_assignment_context()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.matches m
        WHERE m.id = NEW.match_id AND m.organization_id = NEW.organization_id
          AND m.tournament_id = NEW.tournament_id
    ) OR (
        NEW.advancement_link_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.advancement_links al
            WHERE al.id = NEW.advancement_link_id AND al.organization_id = NEW.organization_id
              AND al.target_match_id = NEW.match_id AND al.target_side = NEW.side
        )
    ) THEN
        RAISE EXCEPTION 'Invalid match slot assignment context' USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_validate_match_slot_assignment_context
BEFORE INSERT ON public.match_slot_assignments
FOR EACH ROW EXECUTE FUNCTION public.validate_match_slot_assignment_context();

INSERT INTO public.match_slot_assignments
    (organization_id, tournament_id, match_id, side, team_id, origin, advancement_link_id)
SELECT m.organization_id, m.tournament_id, m.id, slot.side, slot.team_id,
       CASE WHEN provenance.link_count = 1 AND provenance.link_id IS NOT NULL
            THEN 'advancement_link' ELSE 'manual' END,
       CASE WHEN provenance.link_count = 1 THEN provenance.link_id END
FROM public.matches m
CROSS JOIN LATERAL (
    VALUES ('home', m.home_team_id), ('away', m.away_team_id)
) slot(side, team_id)
LEFT JOIN LATERAL (
    SELECT count(*) AS link_count,
           (array_agg(al.id) FILTER (
               WHERE source.result_confirmed
                 AND source.winner_team_id IN (source.home_team_id, source.away_team_id)
                 AND slot.team_id = CASE
                     WHEN al.outcome = 'winner' THEN source.winner_team_id
                     WHEN source.winner_team_id = source.home_team_id THEN source.away_team_id
                     WHEN source.winner_team_id = source.away_team_id THEN source.home_team_id
                 END
           ))[1] AS link_id
    FROM public.advancement_links al
    JOIN public.matches source
      ON source.id = al.source_match_id AND source.organization_id = al.organization_id
    WHERE al.organization_id = m.organization_id
      AND al.target_match_id = m.id AND al.target_side = slot.side
) provenance ON TRUE
WHERE slot.team_id IS NOT NULL;


CREATE FUNCTION public.prevent_match_report_history_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'Match report history is append-only' USING ERRCODE = '23514';
END;
$$;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'match_report_rectification_requests', 'match_report_rectification_decisions',
        'match_report_platform_authorizations', 'match_report_versions',
        'match_report_version_events', 'match_report_rectification_effects',
        'match_report_rectification_notifications', 'competitive_impact_procedures',
        'player_suspension_annulments', 'match_slot_assignments'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format(
            'CREATE POLICY tenant_isolation_policy ON public.%I FOR ALL
             USING (
                 organization_id = NULLIF(current_setting(''app.current_organization_id'', true), '''')::UUID
                 AND public.fn_verify_user_org_membership(organization_id)
             )
             WITH CHECK (
                 organization_id = NULLIF(current_setting(''app.current_organization_id'', true), '''')::UUID
                 AND public.fn_verify_user_org_membership(organization_id)
             )', table_name);
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC', table_name);
        EXECUTE format('GRANT SELECT, INSERT ON public.%I TO bracket_app', table_name);
    END LOOP;

    FOREACH table_name IN ARRAY ARRAY[
        'match_report_rectification_decisions', 'match_report_versions',
        'match_report_version_events', 'match_report_rectification_effects',
        'match_report_rectification_notifications', 'player_suspension_annulments',
        'match_slot_assignments'
    ] LOOP
        EXECUTE format(
            'CREATE TRIGGER trg_append_only BEFORE UPDATE OR DELETE ON public.%I
             FOR EACH ROW EXECUTE FUNCTION public.prevent_match_report_history_mutation()',
            table_name);
    END LOOP;
END;
$$;

GRANT UPDATE (status, withdrawn_at, resulting_version_id)
    ON public.match_report_rectification_requests TO bracket_app;
GRANT UPDATE (revoked_at, consumed_at)
    ON public.match_report_platform_authorizations TO bracket_app;
GRANT UPDATE (status, resolution, reason, closed_by_user_id, closed_at)
    ON public.competitive_impact_procedures TO bracket_app;


CREATE FUNCTION public.reject_match_report_self_decision()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.match_report_rectification_requests r
        WHERE r.id = NEW.request_id
          AND r.organization_id = NEW.organization_id
          AND r.requested_by_user_id = NEW.decided_by_user_id
    ) THEN
        RAISE EXCEPTION 'RECTIFICATION_SELF_APPROVAL' USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_reject_match_report_self_decision
BEFORE INSERT ON public.match_report_rectification_decisions
FOR EACH ROW EXECUTE FUNCTION public.reject_match_report_self_decision();

CREATE FUNCTION public.validate_match_report_request_transition()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.status <> 'pending'
       OR NEW.status NOT IN ('rejected', 'withdrawn', 'published')
       OR (to_jsonb(NEW) - ARRAY['status', 'withdrawn_at', 'resulting_version_id'])
          IS DISTINCT FROM
          (to_jsonb(OLD) - ARRAY['status', 'withdrawn_at', 'resulting_version_id'])
    THEN
        RAISE EXCEPTION 'RECTIFICATION_INVALID_TRANSITION' USING ERRCODE = '23514';
    END IF;

    IF NEW.status = 'withdrawn' THEN
        IF OLD.withdrawn_at IS NOT NULL OR NEW.withdrawn_at IS NULL
           OR NEW.resulting_version_id IS DISTINCT FROM OLD.resulting_version_id
        THEN
            RAISE EXCEPTION 'RECTIFICATION_INVALID_TRANSITION' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.status = 'published' THEN
        IF OLD.resulting_version_id IS NOT NULL OR NEW.resulting_version_id IS NULL
           OR NEW.withdrawn_at IS DISTINCT FROM OLD.withdrawn_at
        THEN
            RAISE EXCEPTION 'RECTIFICATION_INVALID_TRANSITION' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.withdrawn_at IS DISTINCT FROM OLD.withdrawn_at
          OR NEW.resulting_version_id IS DISTINCT FROM OLD.resulting_version_id
    THEN
        RAISE EXCEPTION 'RECTIFICATION_INVALID_TRANSITION' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_validate_match_report_request_transition
BEFORE UPDATE ON public.match_report_rectification_requests
FOR EACH ROW EXECUTE FUNCTION public.validate_match_report_request_transition();

CREATE FUNCTION public.validate_match_report_authorization_transition()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.revoked_at IS NOT NULL OR OLD.consumed_at IS NOT NULL
       OR (NEW.revoked_at IS NULL) = (NEW.consumed_at IS NULL)
       OR (to_jsonb(NEW) - ARRAY['revoked_at', 'consumed_at'])
          IS DISTINCT FROM
          (to_jsonb(OLD) - ARRAY['revoked_at', 'consumed_at'])
    THEN
        RAISE EXCEPTION 'RECTIFICATION_INVALID_TRANSITION' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_validate_match_report_authorization_transition
BEFORE UPDATE ON public.match_report_platform_authorizations
FOR EACH ROW EXECUTE FUNCTION public.validate_match_report_authorization_transition();

CREATE FUNCTION public.validate_competitive_impact_transition()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.status <> 'open' OR NEW.status <> 'closed'
       OR NEW.resolution IS DISTINCT FROM 'keep_as_played'
       OR NEW.reason IS NULL OR btrim(NEW.reason) = ''
       OR NEW.closed_by_user_id IS NULL OR NEW.closed_at IS NULL
       OR (to_jsonb(NEW) - ARRAY['status', 'resolution', 'reason', 'closed_by_user_id', 'closed_at'])
          IS DISTINCT FROM
          (to_jsonb(OLD) - ARRAY['status', 'resolution', 'reason', 'closed_by_user_id', 'closed_at'])
    THEN
        RAISE EXCEPTION 'RECTIFICATION_INVALID_TRANSITION' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_validate_competitive_impact_transition
BEFORE UPDATE ON public.competitive_impact_procedures
FOR EACH ROW EXECUTE FUNCTION public.validate_competitive_impact_transition();

DO $rectification_permissions$
DECLARE
    permission TEXT;
BEGIN
    FOREACH permission IN ARRAY ARRAY[
        'REQUEST_MATCH_REPORT_RECTIFICATION', 'APPROVE_MATCH_REPORT_RECTIFICATION'
    ] LOOP
        UPDATE public.role_definitions
        SET system_permissions = system_permissions || jsonb_build_array(permission)
        WHERE code IN ('owner', 'administrator')
          AND NOT system_permissions @> jsonb_build_array(permission);

        UPDATE public.roles r
        SET permissions = r.permissions || jsonb_build_array(permission)
        FROM public.role_definitions rd
        WHERE rd.id = r.role_definition_id
          AND rd.code IN ('owner', 'administrator')
          AND NOT r.permissions @> jsonb_build_array(permission);
    END LOOP;
END;
$rectification_permissions$;

CREATE VIEW public.v_match_current_report
WITH (security_barrier = true, security_invoker = true) AS
SELECT m.id AS match_id, m.organization_id, m.tournament_id,
    COALESCE(v.version_number, 1) AS version_number,
    CASE WHEN v.id IS NULL THEN m.resolution_type ELSE v.resolution_type END AS resolution_type,
    CASE WHEN v.id IS NULL THEN m.resolution_reason ELSE v.resolution_reason END AS resolution_reason,
    CASE WHEN v.id IS NULL THEN m.home_score_regular ELSE v.home_score_regular END AS home_score_regular,
    CASE WHEN v.id IS NULL THEN m.away_score_regular ELSE v.away_score_regular END AS away_score_regular,
    CASE WHEN v.id IS NULL THEN m.home_score ELSE v.home_score END AS home_score,
    CASE WHEN v.id IS NULL THEN m.away_score ELSE v.away_score END AS away_score,
    CASE WHEN v.id IS NULL THEN m.home_penalties ELSE v.home_penalties END AS home_penalties,
    CASE WHEN v.id IS NULL THEN m.away_penalties ELSE v.away_penalties END AS away_penalties,
    CASE WHEN v.id IS NULL THEN m.winner_team_id ELSE v.winner_team_id END AS winner_team_id,
    v.published_at AS rectified_at
FROM public.matches m
LEFT JOIN LATERAL (
    SELECT version.*
    FROM public.match_report_versions version
    WHERE version.match_id = m.id AND version.organization_id = m.organization_id
    ORDER BY version.version_number DESC
    LIMIT 1
) v ON TRUE;

CREATE VIEW public.v_match_current_events
WITH (security_barrier = true, security_invoker = true) AS
SELECT me.id, me.organization_id, me.match_id, me.segment_id, me.team_id,
    me.beneficiary_team_id, me.player_id, me.event_type, me.minute, me.added_minute,
    me.client_event_id, me.metadata, me.is_voided, me.voided_at, me.voided_by_member_id,
    me.void_reason, me.created_at, me.player_out_id, me.player_in_id, me.assist_player_id
FROM public.match_events me
WHERE NOT me.is_voided AND NOT EXISTS (
        SELECT 1 FROM public.match_report_versions v
        WHERE v.match_id = me.match_id AND v.organization_id = me.organization_id
    )
UNION ALL
SELECT me.id, me.organization_id, me.match_id, me.segment_id, me.team_id,
    me.beneficiary_team_id, me.player_id, me.event_type, me.minute, me.added_minute,
    me.client_event_id, me.metadata, FALSE AS is_voided, me.voided_at, me.voided_by_member_id,
    me.void_reason, me.created_at, me.player_out_id, me.player_in_id, me.assist_player_id
FROM public.match_report_version_events me
WHERE NOT me.is_voided AND EXISTS (
        SELECT 1 FROM public.match_report_versions v
        WHERE v.id = me.version_id
          AND v.organization_id = me.organization_id AND v.match_id = me.match_id
          AND NOT EXISTS (
              SELECT 1 FROM public.match_report_versions newer
              WHERE newer.match_id = v.match_id AND newer.organization_id = v.organization_id
                AND newer.version_number > v.version_number
          )
    );

REVOKE ALL ON public.v_match_current_report, public.v_match_current_events FROM PUBLIC;
GRANT SELECT ON public.v_match_current_report, public.v_match_current_events TO bracket_app;

CREATE OR REPLACE VIEW public.v_public_matches
WITH (security_barrier = true) AS
SELECT
    m.id, m.tournament_id, m.stage_id, st.name AS stage_name, st.stage_order,
    m.group_id, g.name AS group_name, m.matchday, m.match_date,
    m.home_team_id, home_team.name AS home_team_name, home_team.short_code AS home_team_short_code,
    m.away_team_id, away_team.name AS away_team_name, away_team.short_code AS away_team_short_code,
    CASE WHEN v.id IS NULL THEN m.home_score_regular ELSE v.home_score_regular END AS home_score_regular,
    CASE WHEN v.id IS NULL THEN m.away_score_regular ELSE v.away_score_regular END AS away_score_regular,
    CASE WHEN v.id IS NULL THEN m.home_score ELSE v.home_score END AS home_score,
    CASE WHEN v.id IS NULL THEN m.away_score ELSE v.away_score END AS away_score,
    CASE WHEN v.id IS NULL THEN m.home_penalties ELSE v.home_penalties END AS home_penalties,
    CASE WHEN v.id IS NULL THEN m.away_penalties ELSE v.away_penalties END AS away_penalties,
    CASE WHEN v.id IS NULL THEN m.winner_team_id ELSE v.winner_team_id END AS winner_team_id,
    m.status, CASE WHEN v.id IS NULL THEN m.resolution_type ELSE v.resolution_type END AS resolution_type,
    m.bracket_code,
    v.published_at AS rectified_at
FROM public.matches m
LEFT JOIN LATERAL (
    SELECT version.*
    FROM public.match_report_versions version
    WHERE version.match_id = m.id AND version.organization_id = m.organization_id
    ORDER BY version.version_number DESC
    LIMIT 1
) v ON TRUE
JOIN public.tournaments tr
  ON tr.id = m.tournament_id
 AND tr.organization_id = m.organization_id
JOIN public.organizations org
  ON org.id = tr.organization_id
 AND org.is_active = TRUE
JOIN public.stages st
  ON st.id = m.stage_id
 AND st.tournament_id = m.tournament_id
 AND st.organization_id = m.organization_id
 AND st.tournament_version_id = tr.published_version_id
LEFT JOIN public.groups g
  ON g.id = m.group_id
 AND g.stage_id = m.stage_id
 AND g.organization_id = m.organization_id
LEFT JOIN public.teams home_team
  ON home_team.id = m.home_team_id
 AND home_team.organization_id = m.organization_id
LEFT JOIN public.teams away_team
  ON away_team.id = m.away_team_id
 AND away_team.organization_id = m.organization_id
WHERE tr.status IN ('published', 'live', 'finished')
  AND m.tournament_version_id = tr.published_version_id
  AND m.status IN ('scheduled', 'live', 'finished', 'administrative_resolution');

CREATE OR REPLACE VIEW public.v_public_match_events
WITH (security_barrier = true) AS
WITH current_events AS (
SELECT me.organization_id, me.id, me.match_id, me.team_id, me.player_id, me.event_type,
    me.minute, me.added_minute, me.player_out_id, me.player_in_id,
    me.beneficiary_team_id, me.metadata, me.is_voided
FROM public.match_events me
WHERE NOT EXISTS (
        SELECT 1 FROM public.match_report_versions v
        WHERE v.match_id = me.match_id AND v.organization_id = me.organization_id
    )
UNION ALL
SELECT me.organization_id, me.id, me.match_id, me.team_id, me.player_id, me.event_type,
    me.minute, me.added_minute, me.player_out_id, me.player_in_id,
    me.beneficiary_team_id, me.metadata, FALSE AS is_voided
FROM public.match_report_version_events me
WHERE NOT me.is_voided AND EXISTS (
        SELECT 1 FROM public.match_report_versions v
        WHERE v.id = me.version_id
          AND v.organization_id = me.organization_id AND v.match_id = me.match_id
          AND NOT EXISTS (
              SELECT 1 FROM public.match_report_versions newer
              WHERE newer.match_id = v.match_id AND newer.organization_id = v.organization_id
                AND newer.version_number > v.version_number
          )
    )
)
SELECT
    me.id, me.match_id, m.tournament_id, me.team_id, me.player_id,
    me.event_type, me.minute, me.added_minute, me.player_out_id, me.player_in_id,
    me.beneficiary_team_id, me.metadata, me.is_voided
FROM current_events me
JOIN public.matches m
  ON m.id = me.match_id
 AND m.organization_id = me.organization_id
JOIN public.tournaments tr
  ON tr.id = m.tournament_id
 AND tr.organization_id = m.organization_id
JOIN public.organizations org
  ON org.id = tr.organization_id
 AND org.is_active = TRUE
WHERE tr.status IN ('published', 'live', 'finished')
  AND m.tournament_version_id = tr.published_version_id
  AND m.status IN ('scheduled', 'live', 'finished', 'administrative_resolution');

COMMIT;
