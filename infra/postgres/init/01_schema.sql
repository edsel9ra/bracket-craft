BEGIN;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- Global catalogs and tenant membership
-- ============================================================================

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255),
    full_name VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX uq_users_email_ci ON users (LOWER(email));

CREATE TABLE auth_identities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider VARCHAR(50) NOT NULL,
    provider_subject VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_auth_provider_subject UNIQUE (provider, provider_subject)
);

CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX uq_organizations_slug_ci ON organizations (LOWER(slug));

CREATE TABLE organization_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_org_user UNIQUE (organization_id, user_id),
    CONSTRAINT uq_org_user_context UNIQUE (id, organization_id),
    CONSTRAINT uq_org_user_identity UNIQUE (id, user_id, organization_id)
);

CREATE INDEX idx_organization_users_user_active
    ON organization_users (user_id, organization_id)
    WHERE is_active = TRUE;

CREATE TABLE role_definitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(50) NOT NULL,
    description TEXT,
    system_permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    role_definition_id UUID REFERENCES role_definitions(id) ON DELETE RESTRICT,
    name VARCHAR(50) NOT NULL,
    permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_role_context UNIQUE (id, organization_id),
    CONSTRAINT uq_role_name_org UNIQUE (organization_id, name)
);

CREATE TABLE organization_user_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    organization_user_id UUID NOT NULL,
    role_id UUID NOT NULL,
    FOREIGN KEY (organization_user_id, organization_id)
        REFERENCES organization_users(id, organization_id) ON DELETE CASCADE,
    FOREIGN KEY (role_id, organization_id)
        REFERENCES roles(id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_org_user_role UNIQUE (organization_user_id, role_id)
);

INSERT INTO role_definitions (code, name, description, system_permissions)
VALUES
    ('owner', 'Owner', 'Control total de la organización', '["MANAGE_ORGANIZATION", "MANAGE_TOURNAMENTS", "CLOSE_MATCH_REPORT", "RESOLVE_MATCH_ADMINISTRATIVELY"]'),
    ('administrator', 'Administrator', 'Administración de torneos', '["MANAGE_TOURNAMENTS", "CLOSE_MATCH_REPORT", "RESOLVE_MATCH_ADMINISTRATIVELY"]'),
    ('operator', 'Operator', 'Carga de resultados y actas', '["CLOSE_MATCH_REPORT"]'),
    ('referee', 'Referee', 'Cierre de partidos asignados', '["CLOSE_MATCH_REPORT"]'),
    ('viewer', 'Viewer', 'Consulta interna', '[]'::jsonb)
ON CONFLICT (code) DO NOTHING;

-- ============================================================================
-- Tournaments, versions and phase graph
-- ============================================================================

CREATE TABLE venues (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    name VARCHAR(100) NOT NULL,
    address TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_venue_context UNIQUE (id, organization_id)
);

CREATE TABLE tournaments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    name VARCHAR(100) NOT NULL,
    season VARCHAR(20) NOT NULL,
    start_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'published', 'live', 'finished', 'archived')),
    current_draft_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    published_version_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_tournament_context UNIQUE (id, organization_id)
);

CREATE TABLE tournament_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    tournament_id UUID NOT NULL,
    version_number INT NOT NULL CHECK (version_number > 0),
    rules_config JSONB NOT NULL,
    phase_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(20) NOT NULL CHECK (status IN ('draft', 'published', 'archived')),
    created_by_member_id UUID NOT NULL,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tournament_id, organization_id)
        REFERENCES tournaments(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (created_by_member_id, organization_id)
        REFERENCES organization_users(id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_tournament_version_num UNIQUE (tournament_id, version_number),
    CONSTRAINT uq_version_context UNIQUE (id, organization_id),
    CONSTRAINT uq_version_full_context UNIQUE (id, tournament_id, organization_id)
);

ALTER TABLE tournaments
    ADD CONSTRAINT fk_tournament_published_version
    FOREIGN KEY (published_version_id, organization_id)
    REFERENCES tournament_versions(id, organization_id) ON DELETE RESTRICT;

CREATE UNIQUE INDEX uq_published_tournament_version
    ON tournament_versions (tournament_id)
    WHERE status = 'published';

CREATE TABLE tournament_user_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    organization_user_id UUID NOT NULL,
    tournament_id UUID NOT NULL,
    role_id UUID NOT NULL,
    FOREIGN KEY (organization_user_id, organization_id)
        REFERENCES organization_users(id, organization_id) ON DELETE CASCADE,
    FOREIGN KEY (tournament_id, organization_id)
        REFERENCES tournaments(id, organization_id) ON DELETE CASCADE,
    FOREIGN KEY (role_id, organization_id)
        REFERENCES roles(id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_tournament_user_role UNIQUE (organization_user_id, tournament_id, role_id)
);

CREATE TABLE stages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    tournament_id UUID NOT NULL,
    tournament_version_id UUID NOT NULL,
    name VARCHAR(50) NOT NULL,
    stage_type VARCHAR(30) NOT NULL
        CHECK (stage_type IN ('round_robin', 'single_elimination', 'custom_group', 'swiss', 'double_elimination')),
    stage_order INT NOT NULL CHECK (stage_order > 0),
    FOREIGN KEY (tournament_version_id, tournament_id, organization_id)
        REFERENCES tournament_versions(id, tournament_id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_stage_context UNIQUE (id, tournament_version_id, tournament_id, organization_id),
    CONSTRAINT uq_stage_tournament_context UNIQUE (id, tournament_id, organization_id)
);

CREATE TABLE stage_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    tournament_id UUID NOT NULL,
    tournament_version_id UUID NOT NULL,
    source_stage_id UUID NOT NULL,
    target_stage_id UUID NOT NULL,
    selector_type VARCHAR(30) NOT NULL
        CHECK (selector_type IN ('top_n', 'match_winner', 'match_loser', 'best_ranked', 'manual')),
    selector_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    FOREIGN KEY (source_stage_id, tournament_version_id, tournament_id, organization_id)
        REFERENCES stages(id, tournament_version_id, tournament_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (target_stage_id, tournament_version_id, tournament_id, organization_id)
        REFERENCES stages(id, tournament_version_id, tournament_id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT chk_stage_edge_different CHECK (source_stage_id <> target_stage_id)
);

CREATE TABLE groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    tournament_id UUID NOT NULL,
    tournament_version_id UUID NOT NULL,
    stage_id UUID NOT NULL,
    name VARCHAR(50) NOT NULL,
    FOREIGN KEY (stage_id, tournament_version_id, tournament_id, organization_id)
        REFERENCES stages(id, tournament_version_id, tournament_id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_group_context UNIQUE (id, stage_id, organization_id),
    CONSTRAINT uq_group_name UNIQUE (stage_id, name)
);

CREATE TABLE phase_slots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    tournament_id UUID NOT NULL,
    tournament_version_id UUID NOT NULL,
    stage_id UUID NOT NULL,
    slot_code VARCHAR(20) NOT NULL,
    source_type VARCHAR(30) NOT NULL
        CHECK (source_type IN ('direct_team', 'stage_rank', 'match_result', 'manual')),
    source_reference JSONB NOT NULL DEFAULT '{}'::jsonb,
    FOREIGN KEY (stage_id, tournament_version_id, tournament_id, organization_id)
        REFERENCES stages(id, tournament_version_id, tournament_id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_phase_slot_code UNIQUE (stage_id, slot_code),
    CONSTRAINT uq_phase_slot_context UNIQUE (id, stage_id, organization_id)
);

-- Global player catalog, teams and rosters
-- ============================================================================

CREATE TABLE players (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    document_type VARCHAR(10) NOT NULL,
    national_id_encrypted BYTEA NOT NULL,
    national_id_hmac VARCHAR(64) NOT NULL,
    issuing_country VARCHAR(3) NOT NULL,
    birth_date DATE NOT NULL,
    photo_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_player_document UNIQUE (document_type, issuing_country, national_id_hmac)
);

CREATE TABLE teams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    name VARCHAR(100) NOT NULL,
    short_code VARCHAR(10) NOT NULL,
    logo_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_team_context UNIQUE (id, organization_id),
    CONSTRAINT uq_team_short_code UNIQUE (organization_id, short_code)
);

CREATE TABLE tournament_teams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    tournament_id UUID NOT NULL,
    team_id UUID NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'registered'
        CHECK (status IN ('pending', 'registered', 'disqualified', 'withdrawn')),
    registered_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tournament_id, organization_id)
        REFERENCES tournaments(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (team_id, organization_id)
        REFERENCES teams(id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_tournament_team UNIQUE (tournament_id, team_id),
    CONSTRAINT uq_tournament_team_context UNIQUE (tournament_id, team_id, organization_id)
);

CREATE TABLE rosters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    tournament_id UUID NOT NULL,
    team_id UUID NOT NULL,
    player_id UUID NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
    dorsal_number INT NOT NULL CHECK (dorsal_number > 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    photo_consent BOOLEAN NOT NULL DEFAULT FALSE,
    photo_object_key TEXT,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,
    eligible_from TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (tournament_id, team_id, organization_id)
        REFERENCES tournament_teams(tournament_id, team_id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_roster_context UNIQUE (id, player_id, team_id, tournament_id, organization_id),
    CONSTRAINT chk_roster_dates CHECK (
        valid_to IS NULL OR valid_to >= valid_from
    ),
    CONSTRAINT chk_roster_eligibility CHECK (eligible_from >= valid_from)
);

CREATE UNIQUE INDEX uq_active_player_tournament
    ON rosters (tournament_id, player_id)
    WHERE is_active = TRUE;

CREATE UNIQUE INDEX uq_active_roster_dorsal
    ON rosters (tournament_id, team_id, dorsal_number)
    WHERE is_active = TRUE;

CREATE TABLE stage_teams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    tournament_id UUID NOT NULL,
    tournament_version_id UUID NOT NULL,
    stage_id UUID NOT NULL,
    group_id UUID,
    team_id UUID NOT NULL,
    FOREIGN KEY (stage_id, tournament_version_id, tournament_id, organization_id)
        REFERENCES stages(id, tournament_version_id, tournament_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (group_id, stage_id, organization_id)
        REFERENCES groups(id, stage_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (tournament_id, team_id, organization_id)
        REFERENCES tournament_teams(tournament_id, team_id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_stage_team UNIQUE (stage_id, group_id, team_id)
);

-- ============================================================================
-- Matches, officials, segments, lineups and events
-- ============================================================================

CREATE TABLE matches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    tournament_id UUID NOT NULL,
    tournament_version_id UUID NOT NULL,
    stage_id UUID NOT NULL,
    group_id UUID,
    venue_id UUID,
    replacement_match_id UUID,
    matchday INT CHECK (matchday IS NULL OR matchday > 0),
    bracket_code VARCHAR(20),
    home_slot_id UUID,
    away_slot_id UUID,
    home_team_id UUID,
    away_team_id UUID,
    home_score_regular INT CHECK (home_score_regular IS NULL OR home_score_regular >= 0),
    away_score_regular INT CHECK (away_score_regular IS NULL OR away_score_regular >= 0),
    home_score INT CHECK (home_score IS NULL OR home_score >= 0),
    away_score INT CHECK (away_score IS NULL OR away_score >= 0),
    home_penalties INT CHECK (home_penalties IS NULL OR home_penalties >= 0),
    away_penalties INT CHECK (away_penalties IS NULL OR away_penalties >= 0),
    winner_team_id UUID,
    status VARCHAR(30) NOT NULL DEFAULT 'scheduled'
        CHECK (status IN ('scheduled', 'live', 'finished', 'suspended', 'cancelled', 'administrative_resolution')),
    resolution_type VARCHAR(30)
        CHECK (resolution_type IS NULL OR resolution_type IN ('regular', 'extra_time', 'penalties', 'walkover', 'administrative')),
    resolution_reason TEXT,
    result_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    match_date TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tournament_version_id, tournament_id, organization_id)
        REFERENCES tournament_versions(id, tournament_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (stage_id, tournament_version_id, tournament_id, organization_id)
        REFERENCES stages(id, tournament_version_id, tournament_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (group_id, stage_id, organization_id)
        REFERENCES groups(id, stage_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (venue_id, organization_id)
        REFERENCES venues(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (replacement_match_id, organization_id)
        REFERENCES matches(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (home_slot_id, stage_id, organization_id)
        REFERENCES phase_slots(id, stage_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (away_slot_id, stage_id, organization_id)
        REFERENCES phase_slots(id, stage_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (tournament_id, home_team_id, organization_id)
        REFERENCES tournament_teams(tournament_id, team_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (tournament_id, away_team_id, organization_id)
        REFERENCES tournament_teams(tournament_id, team_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (tournament_id, winner_team_id, organization_id)
        REFERENCES tournament_teams(tournament_id, team_id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_match_context UNIQUE (id, tournament_id, organization_id),
    CONSTRAINT uq_match_org UNIQUE (id, organization_id),
    CONSTRAINT chk_different_teams CHECK (
        home_team_id IS NULL OR away_team_id IS NULL OR home_team_id <> away_team_id
    ),
    CONSTRAINT chk_winner_is_participant CHECK (
        winner_team_id IS NULL
        OR (home_team_id IS NOT NULL AND winner_team_id = home_team_id)
        OR (away_team_id IS NOT NULL AND winner_team_id = away_team_id)
    ),
    CONSTRAINT chk_final_score_ge_regular CHECK (
        (home_score IS NULL OR home_score_regular IS NULL OR home_score >= home_score_regular)
        AND (away_score IS NULL OR away_score_regular IS NULL OR away_score >= away_score_regular)
    ),
    CONSTRAINT chk_penalties_consistency CHECK (
        CASE
            WHEN resolution_type = 'penalties' THEN
                home_penalties IS NOT NULL
                AND away_penalties IS NOT NULL
                AND home_penalties <> away_penalties
                AND home_score IS NOT NULL
                AND away_score IS NOT NULL
                AND home_score = away_score
            ELSE
                home_penalties IS NULL AND away_penalties IS NULL
        END
    ),
    CONSTRAINT chk_terminal_result CHECK (
        status NOT IN ('finished', 'administrative_resolution')
        OR (
            result_confirmed = TRUE
            AND resolution_type IS NOT NULL
            AND home_score_regular IS NOT NULL
            AND away_score_regular IS NOT NULL
            AND home_score IS NOT NULL
            AND away_score IS NOT NULL
        )
    ),
    CONSTRAINT chk_terminal_winner CHECK (
        status NOT IN ('finished', 'administrative_resolution')
        OR resolution_type = 'regular'
        OR winner_team_id IS NOT NULL
    ),
    CONSTRAINT chk_administrative_resolution_reason CHECK (
        (
            resolution_type = 'administrative'
            AND resolution_reason IS NOT NULL
            AND LENGTH(BTRIM(resolution_reason)) BETWEEN 1 AND 1000
        )
        OR (
            resolution_type IS DISTINCT FROM 'administrative'
            AND resolution_reason IS NULL
        )
    )
);

CREATE INDEX idx_matches_tournament_schedule
    ON matches (organization_id, tournament_id, tournament_version_id, stage_id, match_date, matchday, id);

CREATE OR REPLACE FUNCTION validate_match_stage_teams()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    version_status VARCHAR(20);
BEGIN
    SELECT tv.status
    INTO version_status
    FROM tournament_versions tv
    WHERE tv.id = NEW.tournament_version_id
      AND tv.organization_id = NEW.organization_id;

    IF version_status = 'draft' THEN
        IF NEW.home_team_id IS NOT NULL AND NOT EXISTS (
            SELECT 1
            FROM stage_teams st
            WHERE st.organization_id = NEW.organization_id
              AND st.tournament_id = NEW.tournament_id
              AND st.tournament_version_id = NEW.tournament_version_id
              AND st.stage_id = NEW.stage_id
              AND st.team_id = NEW.home_team_id
              AND st.group_id IS NOT DISTINCT FROM NEW.group_id
        ) THEN
            RAISE EXCEPTION 'El equipo local no está asignado a la fase y grupo del partido';
        END IF;
        IF NEW.away_team_id IS NOT NULL AND NOT EXISTS (
            SELECT 1
            FROM stage_teams st
            WHERE st.organization_id = NEW.organization_id
              AND st.tournament_id = NEW.tournament_id
              AND st.tournament_version_id = NEW.tournament_version_id
              AND st.stage_id = NEW.stage_id
              AND st.team_id = NEW.away_team_id
              AND st.group_id IS NOT DISTINCT FROM NEW.group_id
        ) THEN
            RAISE EXCEPTION 'El equipo visitante no está asignado a la fase y grupo del partido';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_validate_match_stage_teams
BEFORE INSERT OR UPDATE ON matches
FOR EACH ROW EXECUTE FUNCTION validate_match_stage_teams();

CREATE TABLE match_officials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    match_id UUID NOT NULL,
    organization_user_id UUID NOT NULL,
    official_role VARCHAR(30) NOT NULL CHECK (
        official_role IN ('main_referee', 'assistant_referee_1', 'assistant_referee_2', 'fourth_official', 'match_commissioner')
    ),
    FOREIGN KEY (match_id, organization_id)
        REFERENCES matches(id, organization_id) ON DELETE CASCADE,
    FOREIGN KEY (organization_user_id, organization_id)
        REFERENCES organization_users(id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_match_official UNIQUE (match_id, organization_user_id, official_role)
);

CREATE TABLE match_segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    match_id UUID NOT NULL,
    segment_number INT NOT NULL CHECK (segment_number > 0),
    minute_start INT NOT NULL CHECK (minute_start >= 0),
    minute_end INT,
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'completed', 'interrupted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (match_id, organization_id)
        REFERENCES matches(id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_segment_match_number UNIQUE (match_id, segment_number),
    CONSTRAINT uq_segment_context UNIQUE (id, match_id, organization_id),
    CONSTRAINT chk_segment_minutes CHECK (minute_end IS NULL OR minute_end >= minute_start)
);

CREATE TABLE match_rosters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    match_id UUID NOT NULL,
    roster_id UUID NOT NULL,
    player_id UUID NOT NULL,
    team_id UUID NOT NULL,
    tournament_id UUID NOT NULL,
    matchday INT,
    role VARCHAR(20) NOT NULL CHECK (role IN ('starter', 'substitute')),
    is_valid BOOLEAN NOT NULL DEFAULT TRUE,
    entered_minute INT CHECK (entered_minute IS NULL OR entered_minute >= 0),
    left_minute INT CHECK (left_minute IS NULL OR left_minute >= 0),
    was_ejected BOOLEAN NOT NULL DEFAULT FALSE,
    FOREIGN KEY (match_id, tournament_id, organization_id)
        REFERENCES matches(id, tournament_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (roster_id, player_id, team_id, tournament_id, organization_id)
        REFERENCES rosters(id, player_id, team_id, tournament_id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_match_player UNIQUE (match_id, player_id),
    CONSTRAINT uq_match_roster_context UNIQUE (id, organization_id)
);

CREATE TABLE match_lineup_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    match_id UUID NOT NULL,
    segment_id UUID NOT NULL,
    team_id UUID NOT NULL,
    player_id UUID NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
    is_starter BOOLEAN NOT NULL,
    was_ejected BOOLEAN NOT NULL DEFAULT FALSE,
    FOREIGN KEY (segment_id, match_id, organization_id)
        REFERENCES match_segments(id, match_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (team_id, organization_id)
        REFERENCES teams(id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_lineup_snapshot_player UNIQUE (segment_id, team_id, player_id)
);

CREATE TABLE match_segment_team_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    match_id UUID NOT NULL,
    segment_id UUID NOT NULL,
    team_id UUID NOT NULL,
    substitutions_remaining INT NOT NULL CHECK (substitutions_remaining >= 0),
    substitution_windows_remaining INT NOT NULL CHECK (substitution_windows_remaining >= 0),
    FOREIGN KEY (segment_id, match_id, organization_id)
        REFERENCES match_segments(id, match_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (team_id, organization_id)
        REFERENCES teams(id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_segment_team_state UNIQUE (segment_id, team_id)
);

CREATE TABLE match_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    match_id UUID NOT NULL,
    segment_id UUID NOT NULL,
    team_id UUID NOT NULL,
    beneficiary_team_id UUID,
    player_id UUID NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
    event_type VARCHAR(30) NOT NULL CHECK (
        event_type IN ('goal', 'own_goal', 'penalty_goal', 'yellow_card', 'red_card', 'substitution', 'foul')
    ),
    minute INT NOT NULL CHECK (minute >= 0),
    added_minute INT NOT NULL DEFAULT 0 CHECK (added_minute >= 0),
    client_event_id VARCHAR(100) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_voided BOOLEAN NOT NULL DEFAULT FALSE,
    voided_at TIMESTAMPTZ,
    voided_by_member_id UUID,
    void_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (segment_id, match_id, organization_id)
        REFERENCES match_segments(id, match_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (team_id, organization_id)
        REFERENCES teams(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (beneficiary_team_id, organization_id)
        REFERENCES teams(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (voided_by_member_id, organization_id)
        REFERENCES organization_users(id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_event_client_id UNIQUE (organization_id, match_id, client_event_id),
    CONSTRAINT uq_event_context UNIQUE (id, match_id, player_id, organization_id),
    CONSTRAINT chk_own_goal_beneficiary CHECK (
        (event_type = 'own_goal' AND beneficiary_team_id IS NOT NULL AND beneficiary_team_id <> team_id)
        OR (event_type <> 'own_goal' AND (beneficiary_team_id IS NULL OR beneficiary_team_id = team_id))
    )
);

-- Keep denormalized context in sync and reject client-supplied mismatches.
CREATE OR REPLACE FUNCTION sync_match_roster_context()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_tournament_id UUID;
    v_matchday INT;
BEGIN
    SELECT m.tournament_id, m.matchday
    INTO STRICT v_tournament_id, v_matchday
    FROM matches m
    WHERE m.id = NEW.match_id
      AND m.organization_id = NEW.organization_id;

    NEW.tournament_id := v_tournament_id;
    NEW.matchday := v_matchday;
    RETURN NEW;
EXCEPTION
    WHEN NO_DATA_FOUND THEN
        RAISE EXCEPTION 'El partido no existe en la organización actual';
END;
$$;

CREATE TRIGGER trg_sync_match_roster_context
BEFORE INSERT OR UPDATE ON match_rosters
FOR EACH ROW
EXECUTE FUNCTION sync_match_roster_context();

CREATE OR REPLACE FUNCTION prevent_matchday_change_with_rosters()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF (
        NEW.matchday IS DISTINCT FROM OLD.matchday
        OR NEW.tournament_id IS DISTINCT FROM OLD.tournament_id
    )
    AND EXISTS (
        SELECT 1
        FROM match_rosters mr
        WHERE mr.match_id = OLD.id
          AND mr.is_valid = TRUE
    ) THEN
        RAISE EXCEPTION 'No se puede cambiar torneo o jornada después de registrar la planilla';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_prevent_matchday_change
BEFORE UPDATE OF matchday, tournament_id ON matches
FOR EACH ROW
EXECUTE FUNCTION prevent_matchday_change_with_rosters();

CREATE UNIQUE INDEX uq_matchday_player_unique
    ON match_rosters (organization_id, tournament_id, player_id, matchday)
    WHERE is_valid = TRUE AND matchday IS NOT NULL;

CREATE TABLE player_suspensions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    source_tournament_id UUID NOT NULL,
    player_id UUID NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
    origin_match_id UUID,
    source_event_id UUID,
    source_type VARCHAR(30) NOT NULL CHECK (
        source_type IN ('match_event', 'administrative_resolution', 'competition_rule')
    ),
    dedupe_key VARCHAR(180) NOT NULL UNIQUE,
    scope_type VARCHAR(20) NOT NULL CHECK (scope_type IN ('tournament', 'organization')),
    matches_suspended INT NOT NULL CHECK (matches_suspended > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'served', 'appealed', 'cancelled')),
    reason VARCHAR(150) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_tournament_id, organization_id)
        REFERENCES tournaments(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (origin_match_id, organization_id)
        REFERENCES matches(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (source_event_id, origin_match_id, player_id, organization_id)
        REFERENCES match_events(id, match_id, player_id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_suspension_context UNIQUE (id, organization_id),
    CONSTRAINT chk_suspension_source CHECK (
        (
            source_type = 'match_event'
            AND source_event_id IS NOT NULL
            AND origin_match_id IS NOT NULL
        )
        OR (
            source_type IN ('administrative_resolution', 'competition_rule')
            AND source_event_id IS NULL
        )
    )
);

CREATE TABLE player_suspension_serves (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    suspension_id UUID NOT NULL,
    match_id UUID NOT NULL,
    served_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_voided BOOLEAN NOT NULL DEFAULT FALSE,
    voided_at TIMESTAMPTZ,
    voided_by_member_id UUID,
    void_reason TEXT,
    FOREIGN KEY (suspension_id, organization_id)
        REFERENCES player_suspensions(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (match_id, organization_id)
        REFERENCES matches(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (voided_by_member_id, organization_id)
        REFERENCES organization_users(id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_suspension_match UNIQUE (suspension_id, match_id)
);

CREATE TABLE standings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    tournament_id UUID NOT NULL,
    stage_id UUID NOT NULL,
    group_id UUID,
    team_id UUID NOT NULL,
    played INT NOT NULL DEFAULT 0 CHECK (played >= 0),
    won INT NOT NULL DEFAULT 0 CHECK (won >= 0),
    drawn INT NOT NULL DEFAULT 0 CHECK (drawn >= 0),
    lost INT NOT NULL DEFAULT 0 CHECK (lost >= 0),
    goals_for INT NOT NULL DEFAULT 0 CHECK (goals_for >= 0),
    goals_against INT NOT NULL DEFAULT 0 CHECK (goals_against >= 0),
    goal_difference INT NOT NULL DEFAULT 0,
    points INT NOT NULL DEFAULT 0,
    fair_play_points INT NOT NULL DEFAULT 0,
    rank INT NOT NULL DEFAULT 0 CHECK (rank >= 0),
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (stage_id, tournament_id, organization_id)
        REFERENCES stages(id, tournament_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (group_id, stage_id, organization_id)
        REFERENCES groups(id, stage_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (tournament_id, team_id, organization_id)
        REFERENCES tournament_teams(tournament_id, team_id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_standing_team_group UNIQUE (stage_id, group_id, team_id)
);

CREATE INDEX idx_standings_tournament_rank
    ON standings (organization_id, tournament_id, stage_id, group_id, rank, team_id);

CREATE TABLE advancement_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    source_match_id UUID NOT NULL,
    target_match_id UUID NOT NULL,
    outcome VARCHAR(10) NOT NULL CHECK (outcome IN ('winner', 'loser')),
    target_side VARCHAR(10) NOT NULL CHECK (target_side IN ('home', 'away')),
    FOREIGN KEY (source_match_id, organization_id)
        REFERENCES matches(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (target_match_id, organization_id)
        REFERENCES matches(id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_advancement_link UNIQUE (source_match_id, target_match_id, outcome, target_side)
);

CREATE TABLE ranking_draw_resolutions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    tournament_id UUID NOT NULL,
    tournament_version_id UUID NOT NULL,
    stage_id UUID NOT NULL,
    tie_group_hash VARCHAR(128) NOT NULL,
    seed BIGINT NOT NULL,
    final_order JSONB NOT NULL,
    resolved_by_member_id UUID NOT NULL,
    resolved_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tournament_version_id, tournament_id, organization_id)
        REFERENCES tournament_versions(id, tournament_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (stage_id, tournament_version_id, tournament_id, organization_id)
        REFERENCES stages(id, tournament_version_id, tournament_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (resolved_by_member_id, organization_id)
        REFERENCES organization_users(id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_ranking_draw UNIQUE (tournament_version_id, stage_id, tie_group_hash)
);

CREATE TABLE administrative_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    entity_type VARCHAR(50) NOT NULL,
    entity_id UUID NOT NULL,
    action VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    performed_by_member_id UUID NOT NULL,
    performed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (performed_by_member_id, organization_id)
        REFERENCES organization_users(id, organization_id) ON DELETE RESTRICT
);

CREATE TABLE outbox_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    event_type VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'processed', 'failed')),
    attempts INT NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    available_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_error TEXT,
    locked_at TIMESTAMPTZ,
    processed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_outbox_pending_available
    ON outbox_events (available_at, created_at)
    WHERE status = 'pending';

CREATE INDEX idx_outbox_processing_locked
    ON outbox_events (locked_at, created_at)
    WHERE status = 'processing';

CREATE OR REPLACE FUNCTION claim_outbox_events(p_limit INT DEFAULT 20)
RETURNS TABLE (
    id UUID,
    organization_id UUID,
    event_type VARCHAR,
    payload JSONB
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    RETURN QUERY
    WITH candidates AS (
        SELECT oe.id
        FROM public.outbox_events oe
        WHERE (
                oe.status = 'pending'
                AND oe.available_at <= CURRENT_TIMESTAMP
              )
           OR (
                oe.status = 'processing'
                AND oe.locked_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes'
              )
        ORDER BY oe.created_at
        FOR UPDATE SKIP LOCKED
        LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 20), 100))
    )
    UPDATE public.outbox_events oe
    SET status = 'processing',
        locked_at = CURRENT_TIMESTAMP,
        attempts = oe.attempts + 1
    FROM candidates
    WHERE oe.id = candidates.id
    RETURNING oe.id, oe.organization_id, oe.event_type, oe.payload;
END;
$$;

CREATE OR REPLACE FUNCTION complete_outbox_event(p_event_id UUID)
RETURNS BOOLEAN
LANGUAGE SQL
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    UPDATE public.outbox_events
    SET status = 'processed',
        processed_at = CURRENT_TIMESTAMP,
        locked_at = NULL
    WHERE id = p_event_id AND status = 'processing'
    RETURNING TRUE;
$$;

CREATE OR REPLACE FUNCTION fail_outbox_event(p_event_id UUID, p_error TEXT)
RETURNS BOOLEAN
LANGUAGE SQL
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    UPDATE public.outbox_events
    SET status = CASE WHEN attempts >= 5 THEN 'failed' ELSE 'pending' END,
        available_at = CASE
            WHEN attempts >= 5 THEN available_at
            ELSE CURRENT_TIMESTAMP + INTERVAL '5 seconds'
        END,
        last_error = LEFT(COALESCE(p_error, 'Error de procesamiento'), 2000),
        locked_at = NULL
    WHERE id = p_event_id AND status = 'processing'
    RETURNING TRUE;
$$;

-- ============================================================================
-- Structural immutability after publication
-- ============================================================================

CREATE OR REPLACE FUNCTION prevent_published_structure_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_version_id UUID;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        v_version_id := OLD.tournament_version_id;
        IF EXISTS (
            SELECT 1
            FROM tournament_versions tv
            WHERE tv.id = v_version_id
              AND tv.status IN ('published', 'archived')
        ) THEN
            RAISE EXCEPTION 'La versión publicada o archivada no puede modificarse';
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
            RAISE EXCEPTION 'No se pueden insertar estructuras en una versión publicada';
        END IF;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_protect_stages
BEFORE INSERT OR UPDATE OR DELETE ON stages
FOR EACH ROW EXECUTE FUNCTION prevent_published_structure_mutation();

CREATE TRIGGER trg_protect_stage_edges
BEFORE INSERT OR UPDATE OR DELETE ON stage_edges
FOR EACH ROW EXECUTE FUNCTION prevent_published_structure_mutation();

CREATE TRIGGER trg_protect_groups
BEFORE INSERT OR UPDATE OR DELETE ON groups
FOR EACH ROW EXECUTE FUNCTION prevent_published_structure_mutation();

CREATE TRIGGER trg_protect_phase_slots
BEFORE INSERT OR UPDATE OR DELETE ON phase_slots
FOR EACH ROW EXECUTE FUNCTION prevent_published_structure_mutation();

CREATE TRIGGER trg_protect_stage_teams
BEFORE INSERT OR UPDATE OR DELETE ON stage_teams
FOR EACH ROW EXECUTE FUNCTION prevent_published_structure_mutation();

CREATE OR REPLACE FUNCTION prevent_published_version_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' AND OLD.status IN ('published', 'archived') THEN
        RAISE EXCEPTION 'No se puede eliminar una versión publicada o archivada';
    END IF;

    IF TG_OP = 'UPDATE' AND OLD.status IN ('published', 'archived') THEN
        IF NEW.rules_config IS DISTINCT FROM OLD.rules_config
           OR NEW.phase_config IS DISTINCT FROM OLD.phase_config
           OR NEW.tournament_id IS DISTINCT FROM OLD.tournament_id
           OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
        THEN
            RAISE EXCEPTION 'La configuración de una versión publicada o archivada es inmutable';
        END IF;
        IF OLD.status = 'archived' AND NEW.status IS DISTINCT FROM OLD.status THEN
            RAISE EXCEPTION 'Una versión archivada no puede cambiar de estado';
        END IF;
        IF OLD.status = 'published' AND NEW.status NOT IN ('published', 'archived') THEN
            RAISE EXCEPTION 'Una versión publicada solo puede archivarse';
        END IF;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_protect_tournament_versions
BEFORE UPDATE OR DELETE ON tournament_versions
FOR EACH ROW EXECUTE FUNCTION prevent_published_version_mutation();

-- ============================================================================
-- Public projections and secure bootstrap functions
-- ============================================================================

CREATE VIEW v_public_tournaments
WITH (security_barrier = true) AS
SELECT id, name, season, start_date, status
FROM tournaments
WHERE status IN ('published', 'live', 'finished');

CREATE VIEW v_public_tournament_players
WITH (security_barrier = true) AS
SELECT
    r.tournament_id,
    p.id AS player_id,
    p.first_name,
    p.last_name,
    r.dorsal_number,
    r.team_id,
    (
        EXTRACT(YEAR FROM t.start_date)
        - EXTRACT(YEAR FROM p.birth_date)
    )::INT AS public_age,
    CASE WHEN r.photo_consent THEN r.photo_object_key ELSE NULL END AS photo_url
FROM rosters r
JOIN players p ON p.id = r.player_id
JOIN tournaments t ON t.id = r.tournament_id
WHERE r.is_active = TRUE
  AND t.status IN ('published', 'live', 'finished');

CREATE OR REPLACE FUNCTION fn_verify_user_org_membership(target_org_id UUID)
RETURNS BOOLEAN
LANGUAGE SQL
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.organization_users ou
        WHERE ou.organization_id = target_org_id
          AND ou.user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
          AND ou.is_active = TRUE
    );
$$;

CREATE OR REPLACE FUNCTION create_organization_with_owner(
    p_org_name TEXT,
    p_org_slug TEXT,
    p_owner_id UUID
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_org_id UUID;
    v_member_id UUID;
    v_role_id UUID;
    v_definition_id UUID;
    v_role_name TEXT;
    v_permissions JSONB;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.users WHERE id = p_owner_id) THEN
        RAISE EXCEPTION 'El usuario propietario no existe';
    END IF;

    INSERT INTO public.organizations (name, slug)
    VALUES (p_org_name, p_org_slug)
    RETURNING id INTO v_org_id;

    INSERT INTO public.organization_users (organization_id, user_id, is_active)
    VALUES (v_org_id, p_owner_id, TRUE)
    RETURNING id INTO v_member_id;

    SELECT id, name, system_permissions
    INTO STRICT v_definition_id, v_role_name, v_permissions
    FROM public.role_definitions
    WHERE code = 'owner';

    INSERT INTO public.roles (organization_id, role_definition_id, name, permissions)
    VALUES (v_org_id, v_definition_id, v_role_name, v_permissions)
    RETURNING id INTO v_role_id;

    INSERT INTO public.organization_user_roles (organization_id, organization_user_id, role_id)
    VALUES (v_org_id, v_member_id, v_role_id);

    RETURN v_org_id;
END;
$$;

CREATE OR REPLACE FUNCTION list_user_organizations()
RETURNS TABLE (
    id UUID,
    name VARCHAR,
    slug VARCHAR,
    organization_user_id UUID
)
LANGUAGE SQL
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT o.id, o.name, o.slug, ou.id
    FROM public.organizations o
    JOIN public.organization_users ou ON ou.organization_id = o.id
    WHERE ou.user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
      AND ou.is_active = TRUE
    ORDER BY o.name;
$$;

CREATE OR REPLACE FUNCTION get_current_organization()
RETURNS TABLE (
    id UUID,
    name VARCHAR,
    slug VARCHAR
)
LANGUAGE SQL
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT o.id, o.name, o.slug
    FROM public.organizations o
    WHERE o.id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
      AND EXISTS (
          SELECT 1
          FROM public.organization_users ou
          WHERE ou.organization_id = o.id
            AND ou.user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
            AND ou.is_active = TRUE
      );
$$;

REVOKE ALL ON FUNCTION fn_verify_user_org_membership(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION create_organization_with_owner(TEXT, TEXT, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION list_user_organizations() FROM PUBLIC;
REVOKE ALL ON FUNCTION get_current_organization() FROM PUBLIC;
REVOKE ALL ON FUNCTION claim_outbox_events(INT) FROM PUBLIC;
REVOKE ALL ON FUNCTION complete_outbox_event(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION fail_outbox_event(UUID, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fn_verify_user_org_membership(UUID) TO bracket_app;
GRANT EXECUTE ON FUNCTION create_organization_with_owner(TEXT, TEXT, UUID) TO bracket_app;
GRANT EXECUTE ON FUNCTION list_user_organizations() TO bracket_app;
GRANT EXECUTE ON FUNCTION get_current_organization() TO bracket_app;
GRANT EXECUTE ON FUNCTION claim_outbox_events(INT) TO bracket_app;
GRANT EXECUTE ON FUNCTION complete_outbox_event(UUID) TO bracket_app;
GRANT EXECUTE ON FUNCTION fail_outbox_event(UUID, TEXT) TO bracket_app;

-- ============================================================================
-- Row-level security for tenant-owned data
-- ============================================================================

ALTER TABLE organization_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE organization_user_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE tournament_user_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE venues ENABLE ROW LEVEL SECURITY;
ALTER TABLE tournaments ENABLE ROW LEVEL SECURITY;
ALTER TABLE tournament_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE stages ENABLE ROW LEVEL SECURITY;
ALTER TABLE stage_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE phase_slots ENABLE ROW LEVEL SECURITY;
ALTER TABLE teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE tournament_teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE rosters ENABLE ROW LEVEL SECURITY;
ALTER TABLE stage_teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE match_officials ENABLE ROW LEVEL SECURITY;
ALTER TABLE match_segments ENABLE ROW LEVEL SECURITY;
ALTER TABLE match_rosters ENABLE ROW LEVEL SECURITY;
ALTER TABLE match_lineup_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE match_segment_team_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE match_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE player_suspensions ENABLE ROW LEVEL SECURITY;
ALTER TABLE player_suspension_serves ENABLE ROW LEVEL SECURITY;
ALTER TABLE standings ENABLE ROW LEVEL SECURITY;
ALTER TABLE advancement_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE ranking_draw_resolutions ENABLE ROW LEVEL SECURITY;
ALTER TABLE administrative_audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbox_events ENABLE ROW LEVEL SECURITY;

ALTER TABLE organization_users FORCE ROW LEVEL SECURITY;
ALTER TABLE roles FORCE ROW LEVEL SECURITY;
ALTER TABLE organization_user_roles FORCE ROW LEVEL SECURITY;
ALTER TABLE tournament_user_roles FORCE ROW LEVEL SECURITY;
ALTER TABLE venues FORCE ROW LEVEL SECURITY;
ALTER TABLE tournaments FORCE ROW LEVEL SECURITY;
ALTER TABLE tournament_versions FORCE ROW LEVEL SECURITY;
ALTER TABLE stages FORCE ROW LEVEL SECURITY;
ALTER TABLE stage_edges FORCE ROW LEVEL SECURITY;
ALTER TABLE groups FORCE ROW LEVEL SECURITY;
ALTER TABLE phase_slots FORCE ROW LEVEL SECURITY;
ALTER TABLE teams FORCE ROW LEVEL SECURITY;
ALTER TABLE tournament_teams FORCE ROW LEVEL SECURITY;
ALTER TABLE rosters FORCE ROW LEVEL SECURITY;
ALTER TABLE stage_teams FORCE ROW LEVEL SECURITY;
ALTER TABLE matches FORCE ROW LEVEL SECURITY;
ALTER TABLE match_officials FORCE ROW LEVEL SECURITY;
ALTER TABLE match_segments FORCE ROW LEVEL SECURITY;
ALTER TABLE match_rosters FORCE ROW LEVEL SECURITY;
ALTER TABLE match_lineup_snapshots FORCE ROW LEVEL SECURITY;
ALTER TABLE match_segment_team_state FORCE ROW LEVEL SECURITY;
ALTER TABLE match_events FORCE ROW LEVEL SECURITY;
ALTER TABLE player_suspensions FORCE ROW LEVEL SECURITY;
ALTER TABLE player_suspension_serves FORCE ROW LEVEL SECURITY;
ALTER TABLE standings FORCE ROW LEVEL SECURITY;
ALTER TABLE advancement_links FORCE ROW LEVEL SECURITY;
ALTER TABLE ranking_draw_resolutions FORCE ROW LEVEL SECURITY;
ALTER TABLE administrative_audit_logs FORCE ROW LEVEL SECURITY;
ALTER TABLE outbox_events FORCE ROW LEVEL SECURITY;

DO $$
DECLARE
    table_name TEXT;
    tenant_tables TEXT[] := ARRAY[
        'organization_users', 'roles', 'organization_user_roles', 'tournament_user_roles',
        'venues', 'tournaments', 'tournament_versions', 'stages', 'stage_edges',
        'groups', 'phase_slots', 'teams', 'tournament_teams', 'rosters', 'stage_teams',
        'matches', 'match_officials', 'match_segments', 'match_rosters',
        'match_lineup_snapshots', 'match_segment_team_state', 'match_events',
        'player_suspensions', 'player_suspension_serves', 'standings',
        'advancement_links', 'ranking_draw_resolutions', 'administrative_audit_logs',
        'outbox_events'
    ];
BEGIN
    FOREACH table_name IN ARRAY tenant_tables LOOP
        EXECUTE format('CREATE POLICY tenant_isolation_policy ON %I
            FOR ALL
            USING (
                organization_id = NULLIF(current_setting(''app.current_organization_id'', true), '''')::UUID
                AND fn_verify_user_org_membership(organization_id)
            )
            WITH CHECK (
                organization_id = NULLIF(current_setting(''app.current_organization_id'', true), '''')::UUID
                AND fn_verify_user_org_membership(organization_id)
            )', table_name);
    END LOOP;
END
$$;

GRANT SELECT, INSERT, UPDATE, DELETE ON
    organization_users, roles, organization_user_roles, tournament_user_roles,
    venues, tournaments, tournament_versions, stages, stage_edges, groups, phase_slots,
    teams, tournament_teams, stage_teams, matches, match_officials,
    match_segments, match_rosters, match_lineup_snapshots, match_segment_team_state,
    match_events, player_suspensions, player_suspension_serves, standings,
    advancement_links, ranking_draw_resolutions, administrative_audit_logs, outbox_events
TO bracket_app;

GRANT SELECT ON rosters TO bracket_app;
GRANT INSERT (
    organization_id, tournament_id, team_id, player_id, dorsal_number, photo_consent,
    valid_from, valid_to, eligible_from
) ON rosters TO bracket_app;
GRANT UPDATE (dorsal_number, is_active, valid_from, valid_to, eligible_from)
    ON rosters TO bracket_app;

REVOKE ALL ON users, auth_identities FROM bracket_app;
GRANT SELECT (id, email, password_hash, full_name) ON users TO bracket_app;
GRANT INSERT (email, password_hash, full_name) ON users TO bracket_app;
GRANT SELECT (user_id, provider, provider_subject) ON auth_identities TO bracket_app;
GRANT INSERT (user_id, provider, provider_subject) ON auth_identities TO bracket_app;
REVOKE ALL ON organizations FROM bracket_app;
GRANT SELECT ON role_definitions TO bracket_app;
GRANT SELECT ON v_public_tournaments, v_public_tournament_players TO bracket_app;
REVOKE SELECT ON players FROM bracket_app;
REVOKE SELECT ON players, auth_identities FROM PUBLIC;

COMMIT;
