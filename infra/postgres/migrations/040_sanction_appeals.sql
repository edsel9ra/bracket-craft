BEGIN;

CREATE FUNCTION public.sanction_member_has_permission(target_org UUID, permission TEXT)
RETURNS BOOLEAN LANGUAGE SQL STABLE SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
    SELECT target_org = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND EXISTS (
            SELECT 1 FROM public.organization_users ou
            JOIN public.users u ON u.id = ou.user_id AND u.is_active
            JOIN public.organizations o ON o.id = ou.organization_id AND o.is_active
            JOIN public.organization_user_roles our ON our.organization_user_id = ou.id
                AND our.organization_id = ou.organization_id
            JOIN public.roles r ON r.id = our.role_id AND r.organization_id = ou.organization_id
            WHERE ou.organization_id = target_org AND ou.is_active
              AND ou.user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
              AND r.permissions @> jsonb_build_array(permission)
        );
$$;
REVOKE ALL ON FUNCTION public.sanction_member_has_permission(UUID, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sanction_member_has_permission(UUID, TEXT) TO bracket_app;

CREATE TABLE public.sanction_cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    suspension_id UUID NOT NULL,
    case_type TEXT NOT NULL CHECK (case_type IN ('appeal', 'administrative_proposal')),
    submitted_by_user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    submitted_by_member_id UUID NOT NULL,
    represented_player_id UUID,
    represented_team_id UUID,
    reason TEXT NOT NULL CHECK (btrim(reason) <> ''),
    evidence_text TEXT,
    evidence_links JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(evidence_links) = 'array'),
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    base_fingerprint JSONB NOT NULL CHECK (jsonb_typeof(base_fingerprint) = 'object'),
    base_duration INTEGER NOT NULL CHECK (base_duration > 0),
    proposed_action TEXT CHECK (proposed_action IN ('annul', 'reduce')),
    proposed_duration INTEGER CHECK (proposed_duration >= 0),
    prior_case_id UUID,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'resolved', 'withdrawn', 'closed_by_rectification')),
    UNIQUE (id, organization_id),
    FOREIGN KEY (suspension_id, organization_id)
        REFERENCES public.player_suspensions(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (submitted_by_member_id, organization_id)
        REFERENCES public.organization_users(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (represented_player_id, organization_id)
        REFERENCES public.players(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (represented_team_id, organization_id)
        REFERENCES public.teams(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (prior_case_id, organization_id)
        REFERENCES public.sanction_cases(id, organization_id) ON DELETE RESTRICT,
    CHECK (prior_case_id IS DISTINCT FROM id),
    CHECK ((case_type = 'appeal' AND proposed_action IS NULL AND proposed_duration IS NULL
                AND num_nonnulls(represented_player_id, represented_team_id) = 1)
        OR (case_type = 'administrative_proposal' AND proposed_action IS NOT NULL
            AND ((proposed_action = 'annul' AND proposed_duration IS NULL)
                OR (proposed_action = 'reduce' AND proposed_duration < base_duration))))
);

CREATE UNIQUE INDEX uq_sanction_pending_case ON public.sanction_cases (organization_id, suspension_id)
    WHERE status = 'pending';

CREATE TABLE public.sanction_case_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    case_id UUID NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN
        ('submitted', 'withdrawn', 'closed_by_rectification', 'affected_by_rectification')),
    actor_user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    reason TEXT NOT NULL CHECK (btrim(reason) <> ''),
    evidence_text TEXT,
    evidence_links JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(evidence_links) = 'array'),
    rectification_version_id UUID,
    successor_suspension_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, organization_id),
    UNIQUE (case_id, event_type, rectification_version_id),
    FOREIGN KEY (case_id, organization_id)
        REFERENCES public.sanction_cases(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (rectification_version_id, organization_id)
        REFERENCES public.match_report_versions(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (successor_suspension_id, organization_id)
        REFERENCES public.player_suspensions(id, organization_id) ON DELETE RESTRICT,
    CHECK ((event_type IN ('closed_by_rectification', 'affected_by_rectification'))
        = (rectification_version_id IS NOT NULL))
);

CREATE FUNCTION public.protect_sanction_history()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    RAISE EXCEPTION 'SANCTION_HISTORY_IMMUTABLE' USING ERRCODE = '23514';
END;
$$;

CREATE FUNCTION public.protect_sanction_case_transition()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'SANCTION_HISTORY_IMMUTABLE' USING ERRCODE = '23514';
    END IF;
    IF (to_jsonb(NEW) - 'status') IS DISTINCT FROM (to_jsonb(OLD) - 'status')
        OR OLD.status <> 'pending' OR NEW.status NOT IN ('resolved', 'withdrawn', 'closed_by_rectification') THEN
        RAISE EXCEPTION 'SANCTION_INVALID_TRANSITION' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_sanction_case_transition BEFORE UPDATE OR DELETE ON public.sanction_cases
    FOR EACH ROW EXECUTE FUNCTION public.protect_sanction_case_transition();
CREATE TRIGGER trg_sanction_case_events_immutable BEFORE UPDATE OR DELETE ON public.sanction_case_events
    FOR EACH ROW EXECUTE FUNCTION public.protect_sanction_history();

ALTER TABLE public.sanction_cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sanction_cases FORCE ROW LEVEL SECURITY;
CREATE POLICY sanction_cases_read ON public.sanction_cases FOR SELECT TO bracket_app
    USING (public.sanction_member_has_permission(organization_id, 'VIEW_SANCTION_CASES'));
CREATE POLICY sanction_cases_insert ON public.sanction_cases FOR INSERT TO bracket_app WITH CHECK (
    submitted_by_user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
    AND status = 'pending'
    AND public.sanction_member_has_permission(organization_id,
        CASE WHEN case_type = 'appeal' THEN 'SUBMIT_SANCTION_APPEALS' ELSE 'RESOLVE_SANCTION_CASES' END)
);
ALTER TABLE public.sanction_case_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sanction_case_events FORCE ROW LEVEL SECURITY;
CREATE POLICY sanction_case_events_read ON public.sanction_case_events FOR SELECT TO bracket_app
    USING (public.sanction_member_has_permission(organization_id, 'VIEW_SANCTION_CASES'));
GRANT SELECT, INSERT ON public.sanction_cases TO bracket_app;
GRANT SELECT ON public.sanction_case_events TO bracket_app;

ALTER TABLE public.sanction_cases ADD UNIQUE (id, suspension_id, organization_id);

CREATE TABLE public.sanction_case_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    case_id UUID NOT NULL,
    decided_by_user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    decided_by_member_id UUID,
    decided_as TEXT NOT NULL CHECK (decided_as IN ('member', 'platform_admin')),
    authorization_id UUID,
    decision TEXT NOT NULL CHECK (decision IN ('maintain', 'annul', 'reduce', 'approve', 'reject')),
    reason TEXT NOT NULL CHECK (btrim(reason) <> ''),
    evidence_text TEXT,
    evidence_links JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(evidence_links) = 'array'),
    before_duration INTEGER NOT NULL CHECK (before_duration > 0),
    after_duration INTEGER CHECK (after_duration >= 0 AND after_duration < before_duration),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, organization_id),
    UNIQUE (id, case_id, organization_id),
    UNIQUE (case_id),
    FOREIGN KEY (case_id, organization_id)
        REFERENCES public.sanction_cases(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (decided_by_member_id, organization_id)
        REFERENCES public.organization_users(id, organization_id) ON DELETE RESTRICT,
    CHECK ((decision = 'reduce' AND after_duration IS NOT NULL)
        OR (decision IN ('maintain', 'annul', 'reject') AND after_duration IS NULL)
        OR decision = 'approve')
);

CREATE TABLE public.sanction_resolutions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    case_id UUID NOT NULL,
    decision_id UUID NOT NULL UNIQUE,
    suspension_id UUID NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('annul', 'reduce')),
    original_duration INTEGER NOT NULL CHECK (original_duration > 0),
    before_duration INTEGER NOT NULL CHECK (before_duration > 0),
    new_duration INTEGER CHECK (new_duration >= 0 AND new_duration < before_duration),
    served_count INTEGER NOT NULL CHECK (served_count >= 0),
    is_declarative BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, organization_id),
    UNIQUE (id, suspension_id, organization_id),
    FOREIGN KEY (case_id, suspension_id, organization_id)
        REFERENCES public.sanction_cases(id, suspension_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (decision_id, case_id, organization_id)
        REFERENCES public.sanction_case_decisions(id, case_id, organization_id) ON DELETE RESTRICT,
    CHECK ((action = 'annul' AND new_duration IS NULL)
        OR (action = 'reduce' AND new_duration IS NOT NULL))
);

DO $history$
DECLARE target TEXT;
BEGIN
    FOREACH target IN ARRAY ARRAY['sanction_case_decisions', 'sanction_resolutions'] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', target);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', target);
        EXECUTE format('CREATE POLICY f9_read ON public.%I FOR SELECT TO bracket_app
            USING (public.sanction_member_has_permission(organization_id, ''VIEW_SANCTION_CASES''))', target);
        EXECUTE format('CREATE TRIGGER trg_f9_immutable BEFORE UPDATE OR DELETE ON public.%I
            FOR EACH ROW EXECUTE FUNCTION public.protect_sanction_history()', target);
        EXECUTE format('GRANT SELECT ON public.%I TO bracket_app', target);
    END LOOP;
END;
$history$;

COMMIT;
