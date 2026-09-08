BEGIN;

-- Keep existing volumes aligned with the RLS posture of a fresh database.
ALTER TABLE public.organization_users FORCE ROW LEVEL SECURITY;
ALTER TABLE public.roles FORCE ROW LEVEL SECURITY;
ALTER TABLE public.organization_user_roles FORCE ROW LEVEL SECURITY;
ALTER TABLE public.tournament_user_roles FORCE ROW LEVEL SECURITY;
ALTER TABLE public.venues FORCE ROW LEVEL SECURITY;
ALTER TABLE public.tournaments FORCE ROW LEVEL SECURITY;
ALTER TABLE public.tournament_versions FORCE ROW LEVEL SECURITY;
ALTER TABLE public.stages FORCE ROW LEVEL SECURITY;
ALTER TABLE public.stage_edges FORCE ROW LEVEL SECURITY;
ALTER TABLE public.groups FORCE ROW LEVEL SECURITY;
ALTER TABLE public.phase_slots FORCE ROW LEVEL SECURITY;
ALTER TABLE public.teams FORCE ROW LEVEL SECURITY;
ALTER TABLE public.tournament_teams FORCE ROW LEVEL SECURITY;
ALTER TABLE public.rosters FORCE ROW LEVEL SECURITY;
ALTER TABLE public.stage_teams FORCE ROW LEVEL SECURITY;
ALTER TABLE public.matches FORCE ROW LEVEL SECURITY;
ALTER TABLE public.match_officials FORCE ROW LEVEL SECURITY;
ALTER TABLE public.match_segments FORCE ROW LEVEL SECURITY;
ALTER TABLE public.match_rosters FORCE ROW LEVEL SECURITY;
ALTER TABLE public.match_lineup_snapshots FORCE ROW LEVEL SECURITY;
ALTER TABLE public.match_segment_team_state FORCE ROW LEVEL SECURITY;
ALTER TABLE public.match_events FORCE ROW LEVEL SECURITY;
ALTER TABLE public.player_suspensions FORCE ROW LEVEL SECURITY;
ALTER TABLE public.player_suspension_serves FORCE ROW LEVEL SECURITY;
ALTER TABLE public.standings FORCE ROW LEVEL SECURITY;
ALTER TABLE public.advancement_links FORCE ROW LEVEL SECURITY;
ALTER TABLE public.ranking_draw_resolutions FORCE ROW LEVEL SECURITY;
ALTER TABLE public.administrative_audit_logs FORCE ROW LEVEL SECURITY;
ALTER TABLE public.outbox_events FORCE ROW LEVEL SECURITY;

-- Team codes are identifiers within an organization and must be case-insensitive.
CREATE UNIQUE INDEX IF NOT EXISTS uq_teams_organization_short_code_ci
    ON public.teams (organization_id, LOWER(short_code));

COMMIT;
