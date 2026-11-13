BEGIN;

CREATE FUNCTION public.sanction_member_has_permission(target_org UUID, permission TEXT)
RETURNS BOOLEAN LANGUAGE SQL STABLE SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
    SELECT COALESCE(target_org = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
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
        ), FALSE);
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

CREATE TABLE public.sanction_effect_applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    resolution_id UUID NOT NULL UNIQUE,
    suspension_id UUID NOT NULL,
    match_id UUID NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL,
    before_status TEXT NOT NULL CHECK (before_status IN ('active', 'served', 'cancelled', 'appealed')),
    after_status TEXT NOT NULL CHECK (after_status IN ('active', 'served', 'cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, organization_id),
    FOREIGN KEY (resolution_id, suspension_id, organization_id)
        REFERENCES public.sanction_resolutions(id, suspension_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (match_id, organization_id)
        REFERENCES public.matches(id, organization_id) ON DELETE RESTRICT
);

CREATE TABLE public.sanction_match_eligibility (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    suspension_id UUID NOT NULL,
    match_id UUID NOT NULL,
    effective_duration INTEGER NOT NULL CHECK (effective_duration >= 0),
    applicable_status TEXT NOT NULL CHECK (applicable_status IN ('active', 'served', 'cancelled', 'appealed')),
    resolution_id UUID,
    started_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, organization_id),
    UNIQUE (suspension_id, match_id),
    FOREIGN KEY (suspension_id, organization_id)
        REFERENCES public.player_suspensions(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (resolution_id, suspension_id, organization_id)
        REFERENCES public.sanction_resolutions(id, suspension_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (match_id, organization_id)
        REFERENCES public.matches(id, organization_id) ON DELETE RESTRICT
);

CREATE INDEX idx_sanction_applications_match ON public.sanction_effect_applications (organization_id, match_id);

DO $history$
DECLARE target TEXT;
BEGIN
    FOREACH target IN ARRAY ARRAY['sanction_case_decisions', 'sanction_resolutions',
        'sanction_effect_applications', 'sanction_match_eligibility'] LOOP
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

CREATE TABLE public.sanction_prejudice_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    case_id UUID NOT NULL,
    match_id UUID,
    recorded_by_user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    reason TEXT NOT NULL CHECK (btrim(reason) <> ''),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (case_id, organization_id)
        REFERENCES public.sanction_cases(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (match_id, organization_id)
        REFERENCES public.matches(id, organization_id) ON DELETE RESTRICT
);

CREATE TABLE public.sanction_platform_authorizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    case_id UUID NOT NULL,
    granted_by_member_id UUID NOT NULL,
    platform_admin_user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    reason TEXT NOT NULL CHECK (btrim(reason) <> ''),
    granted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMPTZ,
    consumed_at TIMESTAMPTZ,
    UNIQUE (id, organization_id),
    UNIQUE (id, case_id, organization_id),
    FOREIGN KEY (case_id, organization_id)
        REFERENCES public.sanction_cases(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (granted_by_member_id, organization_id)
        REFERENCES public.organization_users(id, organization_id) ON DELETE RESTRICT,
    CHECK (num_nonnulls(revoked_at, consumed_at) <= 1)
);

ALTER TABLE public.sanction_case_decisions ADD FOREIGN KEY (authorization_id, case_id, organization_id)
    REFERENCES public.sanction_platform_authorizations(id, case_id, organization_id) ON DELETE RESTRICT;

CREATE FUNCTION public.protect_sanction_authorization()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'SANCTION_HISTORY_IMMUTABLE' USING ERRCODE = '23514';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['revoked_at', 'consumed_at']) IS DISTINCT FROM
            (to_jsonb(OLD) - ARRAY['revoked_at', 'consumed_at'])
        OR OLD.revoked_at IS NOT NULL OR OLD.consumed_at IS NOT NULL
        OR num_nonnulls(NEW.revoked_at, NEW.consumed_at) <> 1 THEN
        RAISE EXCEPTION 'SANCTION_INVALID_AUTHORIZATION_TRANSITION' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_sanction_authorization BEFORE UPDATE OR DELETE ON public.sanction_platform_authorizations
    FOR EACH ROW EXECUTE FUNCTION public.protect_sanction_authorization();

CREATE TABLE public.sanction_notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    case_id UUID NOT NULL,
    recipient_user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    channel TEXT NOT NULL CHECK (channel IN ('internal', 'email')),
    notification_type TEXT NOT NULL CHECK (notification_type IN ('decision', 'withdrawn', 'closed_by_rectification')),
    reason TEXT NOT NULL CHECK (btrim(reason) <> ''),
    outbox_event_id UUID NOT NULL UNIQUE REFERENCES public.outbox_events(id) ON DELETE RESTRICT,
    decision_id UUID,
    case_event_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, organization_id),
    UNIQUE (case_id, notification_type, recipient_user_id, channel),
    FOREIGN KEY (case_id, organization_id)
        REFERENCES public.sanction_cases(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (decision_id, case_id, organization_id)
        REFERENCES public.sanction_case_decisions(id, case_id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (case_event_id, organization_id)
        REFERENCES public.sanction_case_events(id, organization_id) ON DELETE RESTRICT
);

DO $auxiliary$
DECLARE target TEXT;
BEGIN
    FOREACH target IN ARRAY ARRAY['sanction_prejudice_records', 'sanction_platform_authorizations', 'sanction_notifications'] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', target);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', target);
        EXECUTE format('CREATE POLICY f9_read ON public.%I FOR SELECT TO bracket_app
            USING (public.sanction_member_has_permission(organization_id, ''VIEW_SANCTION_CASES''))', target);
        EXECUTE format('GRANT SELECT ON public.%I TO bracket_app', target);
        IF target <> 'sanction_platform_authorizations' THEN
            EXECUTE format('CREATE TRIGGER trg_f9_immutable BEFORE UPDATE OR DELETE ON public.%I
                FOR EACH ROW EXECUTE FUNCTION public.protect_sanction_history()', target);
        END IF;
    END LOOP;
END;
$auxiliary$;

CREATE FUNCTION public.sanction_platform_scope(target_case UUID)
RETURNS BOOLEAN LANGUAGE SQL STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT FALSE;
$$;
REVOKE ALL ON FUNCTION public.sanction_platform_scope(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sanction_platform_scope(UUID) TO bracket_app;

CREATE FUNCTION public.sanction_validate_case()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE source public.player_suspensions; previous public.sanction_cases;
BEGIN
    IF NEW.submitted_by_user_id IS DISTINCT FROM NULLIF(current_setting('app.current_user_id', true), '')::UUID
        OR NOT public.sanction_member_has_permission(NEW.organization_id,
            CASE WHEN NEW.case_type = 'appeal' THEN 'SUBMIT_SANCTION_APPEALS' ELSE 'RESOLVE_SANCTION_CASES' END)
        OR NOT EXISTS (SELECT 1 FROM public.organization_users WHERE id = NEW.submitted_by_member_id
            AND organization_id = NEW.organization_id AND user_id = NEW.submitted_by_user_id AND is_active) THEN
        RAISE EXCEPTION 'SANCTION_MEMBER_REQUIRED' USING ERRCODE = '42501';
    END IF;
    SELECT * INTO source FROM public.player_suspensions
        WHERE id = NEW.suspension_id AND organization_id = NEW.organization_id;
    IF source.id IS NULL THEN RETURN NEW; END IF;
    IF source.status = 'cancelled' OR NEW.status <> 'pending' OR NEW.base_duration <> source.matches_suspended
        OR NEW.submitted_at <> CURRENT_TIMESTAMP THEN
        RAISE EXCEPTION 'SANCTION_INVALID_BASE' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (SELECT 1 FROM public.sanction_cases WHERE suspension_id = NEW.suspension_id AND status = 'resolved') THEN
        RAISE EXCEPTION 'SANCTION_FINAL_CASE' USING ERRCODE = '23514';
    END IF;
    IF NEW.prior_case_id IS NOT NULL THEN
        SELECT * INTO previous FROM public.sanction_cases WHERE id = NEW.prior_case_id AND organization_id = NEW.organization_id;
        IF previous.id IS NULL OR previous.status <> 'closed_by_rectification' THEN
            RAISE EXCEPTION 'SANCTION_INVALID_ANTECEDENT' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.proposed_action = 'reduce' AND (NEW.proposed_duration IS NULL OR NEW.proposed_duration >= NEW.base_duration) THEN
        RAISE EXCEPTION 'SANCTION_DECISION_CATALOG' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_sanction_validate_case BEFORE INSERT ON public.sanction_cases
    FOR EACH ROW EXECUTE FUNCTION public.sanction_validate_case();

CREATE FUNCTION public.sanction_event_allowed(target_org UUID, target_case UUID, kind TEXT)
RETURNS BOOLEAN LANGUAGE SQL STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT COALESCE(target_org = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND kind IN ('submitted', 'withdrawn') AND EXISTS (
            SELECT 1 FROM public.sanction_cases c
            JOIN public.organization_users ou ON ou.id = c.submitted_by_member_id
                AND ou.organization_id = c.organization_id AND ou.user_id = c.submitted_by_user_id AND ou.is_active
            JOIN public.users u ON u.id = ou.user_id AND u.is_active
            JOIN public.organizations o ON o.id = ou.organization_id AND o.is_active
            WHERE c.id = target_case AND c.organization_id = target_org AND c.status = 'pending'
                AND c.submitted_by_user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
        ), FALSE);
$$;
REVOKE ALL ON FUNCTION public.sanction_event_allowed(UUID, UUID, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sanction_event_allowed(UUID, UUID, TEXT) TO bracket_app;

CREATE UNIQUE INDEX uq_sanction_single_case_event ON public.sanction_case_events(case_id, event_type)
    WHERE event_type IN ('submitted', 'withdrawn', 'closed_by_rectification');

CREATE FUNCTION public.sanction_validate_event()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE target public.sanction_cases;
BEGIN
    SELECT * INTO target FROM public.sanction_cases WHERE id = NEW.case_id AND organization_id = NEW.organization_id FOR UPDATE;
    IF NEW.actor_user_id IS DISTINCT FROM NULLIF(current_setting('app.current_user_id', true), '')::UUID
        OR NEW.created_at <> CURRENT_TIMESTAMP THEN
        RAISE EXCEPTION 'SANCTION_ACTOR_MISMATCH' USING ERRCODE = '42501';
    END IF;
    IF NEW.event_type IN ('submitted', 'withdrawn') THEN
        IF NOT public.sanction_event_allowed(NEW.organization_id, NEW.case_id, NEW.event_type) THEN
            RAISE EXCEPTION 'SANCTION_EVENT_DENIED' USING ERRCODE = '42501';
        END IF;
    ELSIF target.id IS NULL THEN
        RAISE EXCEPTION 'SANCTION_EVENT_DENIED' USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_sanction_validate_event BEFORE INSERT ON public.sanction_case_events
    FOR EACH ROW EXECUTE FUNCTION public.sanction_validate_event();

CREATE FUNCTION public.sanction_validate_decision()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE target public.sanction_cases;
BEGIN
    SELECT * INTO target FROM public.sanction_cases WHERE id = NEW.case_id AND organization_id = NEW.organization_id FOR UPDATE;
    IF target.submitted_by_user_id = NEW.decided_by_user_id THEN
        RAISE EXCEPTION 'SANCTION_SELF_DECISION' USING ERRCODE = '23514';
    END IF;
    IF target.id IS NULL OR target.status <> 'pending' THEN
        RAISE EXCEPTION 'SANCTION_CASE_NOT_PENDING' USING ERRCODE = '23514';
    END IF;
    IF NEW.decided_by_user_id IS DISTINCT FROM NULLIF(current_setting('app.current_user_id', true), '')::UUID
        OR NOT ((NEW.decided_as = 'member' AND NEW.authorization_id IS NULL
                AND public.sanction_member_has_permission(NEW.organization_id, 'RESOLVE_SANCTION_CASES')
                AND EXISTS (SELECT 1 FROM public.organization_users WHERE id = NEW.decided_by_member_id
                    AND organization_id = NEW.organization_id AND user_id = NEW.decided_by_user_id AND is_active))
            OR (NEW.decided_as = 'platform_admin' AND NEW.decided_by_member_id IS NULL
                AND NEW.authorization_id = NULLIF(current_setting('app.sanction_authorization_id', true), '')::UUID
                AND public.sanction_platform_scope(NEW.case_id))) THEN
        RAISE EXCEPTION 'SANCTION_DECISION_DENIED' USING ERRCODE = '42501';
    END IF;
    IF NEW.created_at <> CURRENT_TIMESTAMP OR NEW.before_duration <> target.base_duration
        OR (target.case_type = 'appeal' AND NEW.decision NOT IN ('maintain', 'annul', 'reduce'))
        OR (target.case_type = 'administrative_proposal' AND (NEW.decision NOT IN ('approve', 'reject')
            OR (NEW.decision = 'approve' AND NEW.after_duration IS DISTINCT FROM target.proposed_duration))) THEN
        RAISE EXCEPTION 'SANCTION_DECISION_CATALOG' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (SELECT 1 FROM public.player_suspensions WHERE id = target.suspension_id
        AND status = 'cancelled') THEN
        RAISE EXCEPTION 'SANCTION_CHANGED_BASE' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_sanction_validate_decision BEFORE INSERT ON public.sanction_case_decisions
    FOR EACH ROW EXECUTE FUNCTION public.sanction_validate_decision();

CREATE FUNCTION public.sanction_validate_resolution()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE target public.sanction_cases; decided public.sanction_case_decisions;
    source public.player_suspensions; served INTEGER; expected_action TEXT;
BEGIN
    SELECT * INTO target FROM public.sanction_cases WHERE id = NEW.case_id AND organization_id = NEW.organization_id;
    SELECT * INTO decided FROM public.sanction_case_decisions WHERE id = NEW.decision_id AND case_id = target.id;
    SELECT * INTO source FROM public.player_suspensions WHERE id = NEW.suspension_id AND organization_id = NEW.organization_id;
    SELECT count(*) INTO served FROM public.player_suspension_serves WHERE suspension_id = source.id;
    expected_action := CASE WHEN decided.decision = 'approve' THEN target.proposed_action ELSE decided.decision END;
    IF NEW.created_at <> CURRENT_TIMESTAMP OR decided.id IS NULL OR source.id IS NULL OR source.id <> target.suspension_id
        OR expected_action NOT IN ('annul', 'reduce') OR NEW.action <> expected_action
        OR NEW.new_duration IS DISTINCT FROM decided.after_duration
        OR NEW.original_duration <> source.matches_suspended OR NEW.before_duration <> target.base_duration
        OR NEW.served_count <> served OR NEW.is_declarative IS DISTINCT FROM
            (source.status = 'served' OR served >= target.base_duration)
        OR decided.decided_by_user_id IS DISTINCT FROM NULLIF(current_setting('app.current_user_id', true), '')::UUID THEN
        RAISE EXCEPTION 'SANCTION_INVALID_RESOLUTION' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_sanction_validate_resolution BEFORE INSERT ON public.sanction_resolutions
    FOR EACH ROW EXECUTE FUNCTION public.sanction_validate_resolution();

CREATE OR REPLACE FUNCTION public.protect_sanction_case_transition()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'SANCTION_HISTORY_IMMUTABLE' USING ERRCODE = '23514';
    END IF;
    IF (to_jsonb(NEW) - 'status') IS DISTINCT FROM (to_jsonb(OLD) - 'status')
        OR OLD.status <> 'pending' OR NEW.status NOT IN ('resolved', 'withdrawn', 'closed_by_rectification') THEN
        RAISE EXCEPTION 'SANCTION_INVALID_TRANSITION' USING ERRCODE = '23514';
    END IF;
    IF (NEW.status = 'resolved' AND NOT EXISTS (SELECT 1 FROM public.sanction_case_decisions WHERE case_id = NEW.id))
        OR (NEW.status IN ('withdrawn', 'closed_by_rectification') AND NOT EXISTS (
            SELECT 1 FROM public.sanction_case_events WHERE case_id = NEW.id AND event_type = NEW.status)) THEN
        RAISE EXCEPTION 'SANCTION_MISSING_ACT' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.sanction_apply_case_act()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_TABLE_NAME = 'sanction_case_decisions' THEN
        UPDATE public.sanction_cases SET status = 'resolved' WHERE id = NEW.case_id;
    ELSIF NEW.event_type IN ('withdrawn', 'closed_by_rectification') THEN
        UPDATE public.sanction_cases SET status = NEW.event_type WHERE id = NEW.case_id;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_sanction_decision_act AFTER INSERT ON public.sanction_case_decisions
    FOR EACH ROW EXECUTE FUNCTION public.sanction_apply_case_act();
CREATE TRIGGER trg_sanction_event_act AFTER INSERT ON public.sanction_case_events
    FOR EACH ROW EXECUTE FUNCTION public.sanction_apply_case_act();

CREATE FUNCTION public.sanction_assert_complete()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE target_id UUID; target public.sanction_cases; decided public.sanction_case_decisions;
BEGIN
    IF TG_TABLE_NAME = 'sanction_cases' THEN target_id := NEW.id; ELSE target_id := NEW.case_id; END IF;
    SELECT * INTO target FROM public.sanction_cases WHERE id = target_id;
    SELECT * INTO decided FROM public.sanction_case_decisions WHERE case_id = target_id;
    IF NOT EXISTS (SELECT 1 FROM public.sanction_case_events WHERE case_id = target_id AND event_type = 'submitted')
        OR (target.status = 'resolved') IS DISTINCT FROM (decided.id IS NOT NULL)
        OR (target.status IN ('withdrawn', 'closed_by_rectification') AND NOT EXISTS (
            SELECT 1 FROM public.sanction_case_events WHERE case_id = target_id AND event_type = target.status)) THEN
        RAISE EXCEPTION 'SANCTION_MISSING_ACT' USING ERRCODE = '23514';
    END IF;
    IF decided.id IS NOT NULL AND (decided.decision IN ('annul', 'reduce', 'approve')) IS DISTINCT FROM
        (EXISTS (SELECT 1 FROM public.sanction_resolutions WHERE decision_id = decided.id)) THEN
        RAISE EXCEPTION 'SANCTION_MISSING_RESOLUTION' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER trg_sanction_case_complete AFTER INSERT OR UPDATE ON public.sanction_cases
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.sanction_assert_complete();
CREATE CONSTRAINT TRIGGER trg_sanction_decision_complete AFTER INSERT ON public.sanction_case_decisions
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.sanction_assert_complete();

CREATE POLICY f9_event_insert ON public.sanction_case_events FOR INSERT TO bracket_app WITH CHECK (
    actor_user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
    AND public.sanction_event_allowed(organization_id, case_id, event_type));
CREATE POLICY f9_decision_insert ON public.sanction_case_decisions FOR INSERT TO bracket_app WITH CHECK (
    public.sanction_member_has_permission(organization_id, 'RESOLVE_SANCTION_CASES') OR public.sanction_platform_scope(case_id));
CREATE POLICY f9_resolution_insert ON public.sanction_resolutions FOR INSERT TO bracket_app WITH CHECK (
    public.sanction_member_has_permission(organization_id, 'RESOLVE_SANCTION_CASES') OR public.sanction_platform_scope(case_id));
GRANT INSERT ON public.sanction_case_events, public.sanction_case_decisions, public.sanction_resolutions TO bracket_app;

COMMIT;
