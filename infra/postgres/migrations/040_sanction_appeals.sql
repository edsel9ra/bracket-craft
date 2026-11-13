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
    outbox_event_id UUID NOT NULL UNIQUE,
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
    IF NEW.decided_as = 'platform_admin' THEN
        PERFORM public.sanction_lock_platform_authorization(NEW.case_id);
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
    SELECT count(*) INTO served FROM public.player_suspension_serves WHERE suspension_id = source.id AND NOT is_voided;
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

CREATE FUNCTION public.sanction_finalize_case(target_case UUID)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE target public.sanction_cases; decided public.sanction_case_decisions; event public.sanction_case_events;
BEGIN
    SELECT * INTO target FROM public.sanction_cases WHERE id = target_case
        AND organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID FOR UPDATE;
    SELECT * INTO decided FROM public.sanction_case_decisions WHERE case_id = target.id;
    SELECT * INTO event FROM public.sanction_case_events WHERE case_id = target.id
        AND event_type IN ('withdrawn', 'closed_by_rectification');
    IF target.id IS NULL OR target.status <> 'pending' THEN
        RAISE EXCEPTION 'SANCTION_CASE_NOT_PENDING' USING ERRCODE = '23514';
    END IF;
    IF decided.id IS NOT NULL AND decided.decided_by_user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
        AND (public.sanction_member_has_permission(target.organization_id, 'RESOLVE_SANCTION_CASES')
            OR public.sanction_platform_scope(target.id)) THEN
        IF decided.decided_as = 'platform_admin' THEN
            PERFORM public.record_sanction_platform_audit(decided.id);
        END IF;
        UPDATE public.sanction_cases SET status = 'resolved' WHERE id = target.id;
    ELSIF event.id IS NOT NULL AND event.actor_user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID THEN
        UPDATE public.sanction_cases SET status = event.event_type WHERE id = target.id;
    ELSE
        RAISE EXCEPTION 'SANCTION_MISSING_ACT' USING ERRCODE = '23514';
    END IF;
END;
$$;
REVOKE ALL ON FUNCTION public.sanction_finalize_case(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sanction_finalize_case(UUID) TO bracket_app;

CREATE FUNCTION public.sanction_assert_complete()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE target_id UUID; target public.sanction_cases; decided public.sanction_case_decisions;
BEGIN
    IF TG_TABLE_NAME = 'sanction_cases' THEN target_id := NEW.id; ELSE target_id := NEW.case_id; END IF;
    SELECT * INTO target FROM public.sanction_cases WHERE id = target_id;
    SELECT * INTO decided FROM public.sanction_case_decisions WHERE case_id = target_id;
    IF NOT EXISTS (SELECT 1 FROM public.sanction_case_events WHERE case_id = target_id AND event_type = 'submitted')
        OR (target.status = 'pending' AND EXISTS (SELECT 1 FROM public.sanction_case_events WHERE case_id = target_id
            AND event_type IN ('withdrawn', 'closed_by_rectification')))
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
CREATE CONSTRAINT TRIGGER trg_sanction_event_complete AFTER INSERT ON public.sanction_case_events
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.sanction_assert_complete();

CREATE POLICY f9_event_insert ON public.sanction_case_events FOR INSERT TO bracket_app WITH CHECK (
    actor_user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
    AND public.sanction_event_allowed(organization_id, case_id, event_type));
CREATE POLICY f9_decision_insert ON public.sanction_case_decisions FOR INSERT TO bracket_app WITH CHECK (
    public.sanction_member_has_permission(organization_id, 'RESOLVE_SANCTION_CASES') OR public.sanction_platform_scope(case_id));
CREATE POLICY f9_resolution_insert ON public.sanction_resolutions FOR INSERT TO bracket_app WITH CHECK (
    public.sanction_member_has_permission(organization_id, 'RESOLVE_SANCTION_CASES') OR public.sanction_platform_scope(case_id));
GRANT INSERT ON public.sanction_case_events, public.sanction_case_decisions, public.sanction_resolutions TO bracket_app;

DO $defaults$
DECLARE permission TEXT;
BEGIN
    FOREACH permission IN ARRAY ARRAY['VIEW_SANCTION_CASES', 'SUBMIT_SANCTION_APPEALS', 'RESOLVE_SANCTION_CASES'] LOOP
        UPDATE public.role_definitions SET system_permissions = system_permissions || jsonb_build_array(permission)
            WHERE code IN ('owner', 'administrator') AND NOT system_permissions @> jsonb_build_array(permission);
        UPDATE public.roles r SET permissions = r.permissions || jsonb_build_array(permission)
            FROM public.role_definitions rd WHERE r.role_definition_id = rd.id AND rd.code IN ('owner', 'administrator')
                AND NOT r.permissions @> jsonb_build_array(permission);
    END LOOP;
END;
$defaults$;

ALTER TABLE public.sanction_match_eligibility ADD COLUMN served_count INTEGER NOT NULL DEFAULT 0 CHECK (served_count >= 0);

CREATE FUNCTION public.sanction_can_operate_match(target_org UUID, target_match UUID)
RETURNS BOOLEAN LANGUAGE SQL STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT COALESCE(target_org = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND EXISTS (
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
        ), FALSE);
$$;
REVOKE ALL ON FUNCTION public.sanction_can_operate_match(UUID, UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sanction_can_operate_match(UUID, UUID) TO bracket_app;

CREATE FUNCTION public.sanction_operational_facts(target_match UUID)
RETURNS TABLE (suspension_id UUID, player_id UUID, source_tournament_id UUID, scope_type TEXT,
    original_duration INTEGER, status TEXT, created_at TIMESTAMPTZ, origin_match_id UUID,
    serves JSONB, resolutions JSONB, applications JSONB, snapshot JSONB)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE org UUID := NULLIF(current_setting('app.current_organization_id', true), '')::UUID;
BEGIN
    IF NOT public.sanction_can_operate_match(org, target_match) THEN
        RAISE EXCEPTION 'SANCTION_OPERATION_DENIED' USING ERRCODE = '42501';
    END IF;
    RETURN QUERY SELECT ps.id, ps.player_id, ps.source_tournament_id, ps.scope_type::TEXT,
        ps.matches_suspended, ps.status::TEXT, ps.created_at, ps.origin_match_id,
        COALESCE((SELECT jsonb_agg(jsonb_build_object('match_id', s.match_id, 'served_at', s.served_at) ORDER BY s.served_at, s.match_id)
            FROM public.player_suspension_serves s WHERE s.suspension_id = ps.id AND NOT s.is_voided), '[]'::JSONB),
        COALESCE((SELECT jsonb_agg(jsonb_build_object('id', r.id, 'action', r.action,
            'new_duration', r.new_duration, 'is_declarative', r.is_declarative, 'created_at', r.created_at,
            'excluded', EXISTS (SELECT 1 FROM public.sanction_case_events e WHERE e.case_id = r.case_id
                AND e.event_type = 'affected_by_rectification')) ORDER BY r.created_at, r.id)
            FROM public.sanction_resolutions r WHERE r.suspension_id = ps.id), '[]'::JSONB),
        COALESCE((SELECT jsonb_agg(jsonb_build_object('resolution_id', a.resolution_id,
            'match_id', a.match_id, 'effective_at', a.effective_at, 'after_status', a.after_status) ORDER BY a.effective_at, a.id)
            FROM public.sanction_effect_applications a WHERE a.suspension_id = ps.id), '[]'::JSONB),
        (SELECT jsonb_build_object('effective_duration', s.effective_duration, 'applicable_status', s.applicable_status,
            'resolution_id', s.resolution_id, 'started_at', s.started_at, 'served_count', s.served_count)
            FROM public.sanction_match_eligibility s WHERE s.suspension_id = ps.id AND s.match_id = target_match)
    FROM public.player_suspensions ps
    JOIN public.matches m ON m.id = target_match AND m.organization_id = ps.organization_id
    WHERE ps.organization_id = org AND (ps.scope_type = 'organization' OR ps.source_tournament_id = m.tournament_id)
        AND (EXISTS (SELECT 1 FROM public.rosters r WHERE r.organization_id = org
                AND r.tournament_id = m.tournament_id AND r.team_id IN (m.home_team_id, m.away_team_id) AND r.player_id = ps.player_id)
            OR EXISTS (SELECT 1 FROM public.match_rosters mr WHERE mr.organization_id = org
                AND mr.match_id = target_match AND mr.player_id = ps.player_id))
    ORDER BY ps.id;
END;
$$;
REVOKE ALL ON FUNCTION public.sanction_operational_facts(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sanction_operational_facts(UUID) TO bracket_app;

CREATE FUNCTION public.sanction_owner(target_org UUID)
RETURNS UUID LANGUAGE SQL STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT ou.id FROM public.organization_users ou
    JOIN public.users u ON u.id = ou.user_id AND u.is_active
    JOIN public.organizations o ON o.id = ou.organization_id AND o.is_active
    WHERE ou.organization_id = target_org AND ou.is_active
        AND target_org = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND ou.user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
        AND EXISTS (SELECT 1 FROM public.organization_user_roles our
            JOIN public.roles r ON r.id = our.role_id AND r.organization_id = our.organization_id
            JOIN public.role_definitions rd ON rd.id = r.role_definition_id AND rd.code = 'owner'
            WHERE our.organization_id = target_org AND our.organization_user_id = ou.id);
$$;

CREATE FUNCTION public.sanction_platform_candidate(target_email TEXT)
RETURNS UUID LANGUAGE SQL STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT u.id FROM public.users u JOIN public.platform_admins pa ON pa.user_id = u.id
    WHERE lower(u.email) = lower(btrim(target_email)) AND u.is_active AND pa.is_active AND pa.role_code = 'platform_admin'
        AND public.sanction_owner(NULLIF(current_setting('app.current_organization_id', true), '')::UUID) IS NOT NULL;
$$;

CREATE FUNCTION public.sanction_valid_platform_authorizations()
RETURNS TABLE (id UUID, organization_id UUID, case_id UUID, granted_by_member_id UUID)
LANGUAGE SQL STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT a.id, a.organization_id, a.case_id, a.granted_by_member_id
    FROM public.sanction_platform_authorizations a
    JOIN public.sanction_cases c ON c.id = a.case_id AND c.organization_id = a.organization_id
    JOIN public.platform_admins pa ON pa.user_id = a.platform_admin_user_id AND pa.is_active AND pa.role_code = 'platform_admin'
    JOIN public.users actor ON actor.id = pa.user_id AND actor.is_active
    JOIN public.organizations o ON o.id = a.organization_id AND o.is_active
    JOIN public.organization_users owner ON owner.id = a.granted_by_member_id AND owner.organization_id = a.organization_id AND owner.is_active
    JOIN public.users owner_user ON owner_user.id = owner.user_id AND owner_user.is_active
    WHERE a.platform_admin_user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
        AND c.submitted_by_user_id <> a.platform_admin_user_id AND a.revoked_at IS NULL AND a.consumed_at IS NULL
        AND EXISTS (SELECT 1 FROM public.organization_user_roles our
            JOIN public.roles r ON r.id = our.role_id AND r.organization_id = our.organization_id
            JOIN public.role_definitions rd ON rd.id = r.role_definition_id AND rd.code = 'owner'
            WHERE our.organization_id = owner.organization_id AND our.organization_user_id = owner.id);
$$;

CREATE FUNCTION public.sanction_platform_scopes()
RETURNS TABLE (id UUID, organization_id UUID, case_id UUID, granted_by_member_id UUID)
LANGUAGE SQL STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT a.* FROM public.sanction_valid_platform_authorizations() a
    JOIN public.sanction_cases c ON c.id = a.case_id AND c.status = 'pending';
$$;

CREATE OR REPLACE FUNCTION public.sanction_platform_scope(target_case UUID)
RETURNS BOOLEAN LANGUAGE SQL STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT EXISTS (SELECT 1 FROM public.sanction_platform_scopes() a WHERE a.case_id = target_case
        AND a.id = NULLIF(current_setting('app.sanction_authorization_id', true), '')::UUID
        AND a.organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID);
$$;

CREATE FUNCTION public.sanction_lock_platform_authorization(target_case UUID)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE grant_record public.sanction_platform_authorizations;
BEGIN
    IF NOT public.sanction_platform_scope(target_case) THEN
        RAISE EXCEPTION 'SANCTION_AUTHORIZATION_REQUIRED' USING ERRCODE = '42501';
    END IF;
    SELECT * INTO grant_record FROM public.sanction_platform_authorizations
        WHERE id = NULLIF(current_setting('app.sanction_authorization_id', true), '')::UUID AND case_id = target_case FOR UPDATE;
    PERFORM 1 FROM public.organization_users ou JOIN public.users u ON u.id = ou.user_id
        JOIN public.organizations o ON o.id = ou.organization_id
        WHERE ou.id = grant_record.granted_by_member_id FOR SHARE OF ou, u, o;
    PERFORM 1 FROM public.organization_user_roles our
        JOIN public.roles r ON r.id = our.role_id AND r.organization_id = our.organization_id
        JOIN public.role_definitions rd ON rd.id = r.role_definition_id
        WHERE our.organization_user_id = grant_record.granted_by_member_id AND our.organization_id = grant_record.organization_id
        ORDER BY our.id FOR SHARE OF our, r, rd;
    PERFORM 1 FROM public.platform_admins pa JOIN public.users u ON u.id = pa.user_id
        WHERE pa.user_id = grant_record.platform_admin_user_id FOR SHARE OF pa, u;
    IF NOT public.sanction_platform_scope(target_case) THEN
        RAISE EXCEPTION 'SANCTION_AUTHORIZATION_REQUIRED' USING ERRCODE = '42501';
    END IF;
END;
$$;

CREATE FUNCTION public.sanction_platform_source(target_case UUID)
RETURNS JSONB LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE result JSONB;
BEGIN
    IF NOT public.sanction_platform_scope(target_case) THEN
        RAISE EXCEPTION 'SANCTION_AUTHORIZATION_REQUIRED' USING ERRCODE = '42501';
    END IF;
    SELECT jsonb_build_object('id', ps.id, 'player_id', ps.player_id, 'source_tournament_id', ps.source_tournament_id,
        'scope_type', ps.scope_type, 'matches_suspended', ps.matches_suspended, 'status', ps.status,
        'origin_match_id', ps.origin_match_id, 'source_event_id', ps.source_event_id,
        'source_version_event_id', ps.source_version_event_id, 'created_at', ps.created_at,
        'stage_id', m.stage_id, 'tournament_version_id', m.tournament_version_id)
        INTO result FROM public.sanction_cases c JOIN public.player_suspensions ps
            ON ps.id = c.suspension_id AND ps.organization_id = c.organization_id
        LEFT JOIN public.matches m ON m.id = ps.origin_match_id AND m.organization_id = ps.organization_id
        WHERE c.id = target_case;
    RETURN result;
END;
$$;

CREATE FUNCTION public.sanction_validate_authorization()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    IF NEW.granted_by_member_id IS DISTINCT FROM public.sanction_owner(NEW.organization_id)
        OR public.sanction_owner(NEW.organization_id) IS NULL
        OR NEW.revoked_at IS NOT NULL OR NEW.consumed_at IS NOT NULL OR NEW.granted_at <> CURRENT_TIMESTAMP
        OR NOT EXISTS (SELECT 1 FROM public.sanction_cases WHERE id = NEW.case_id
            AND organization_id = NEW.organization_id AND status = 'pending')
        OR NOT EXISTS (SELECT 1 FROM public.platform_admins pa JOIN public.users u ON u.id = pa.user_id AND u.is_active
            WHERE pa.user_id = NEW.platform_admin_user_id AND pa.is_active AND pa.role_code = 'platform_admin') THEN
        RAISE EXCEPTION 'SANCTION_OWNER_AUTHORIZATION_REQUIRED' USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_sanction_validate_authorization BEFORE INSERT ON public.sanction_platform_authorizations
    FOR EACH ROW EXECUTE FUNCTION public.sanction_validate_authorization();

CREATE OR REPLACE FUNCTION public.protect_sanction_authorization()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
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
    IF NEW.revoked_at IS NOT NULL THEN
        IF public.sanction_owner(OLD.organization_id) IS NULL OR NEW.revoked_at <> CURRENT_TIMESTAMP THEN
            RAISE EXCEPTION 'SANCTION_OWNER_AUTHORIZATION_REQUIRED' USING ERRCODE = '42501';
        END IF;
    ELSE
        IF NEW.consumed_at <> CURRENT_TIMESTAMP OR NOT EXISTS (
            SELECT 1 FROM public.sanction_valid_platform_authorizations() a
            JOIN public.sanction_case_decisions d ON d.authorization_id = a.id AND d.case_id = a.case_id
            JOIN public.sanction_cases c ON c.id = a.case_id AND c.status = 'resolved'
            WHERE a.id = OLD.id AND a.id = NULLIF(current_setting('app.sanction_authorization_id', true), '')::UUID
                AND a.organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
                AND d.decided_as = 'platform_admin' AND d.decided_by_user_id = OLD.platform_admin_user_id
                AND EXISTS (SELECT 1 FROM public.platform_audit_logs l WHERE l.action = 'DECIDE_SANCTION_CASE'
                    AND l.target_id = c.id AND l.payload->>'decision_id' = d.id::TEXT)
                AND EXISTS (SELECT 1 FROM public.administrative_audit_logs l WHERE l.action = 'DECIDE_SANCTION_CASE'
                    AND l.entity_id = c.id AND l.payload->>'decision_id' = d.id::TEXT)) THEN
            RAISE EXCEPTION 'SANCTION_AUTHORIZATION_REQUIRED' USING ERRCODE = '42501';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.sanction_revoke_authorization(target_authorization UUID)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    IF public.sanction_owner(NULLIF(current_setting('app.current_organization_id', true), '')::UUID) IS NULL THEN
        RAISE EXCEPTION 'SANCTION_OWNER_AUTHORIZATION_REQUIRED' USING ERRCODE = '42501';
    END IF;
    UPDATE public.sanction_platform_authorizations SET revoked_at = CURRENT_TIMESTAMP
        WHERE id = target_authorization AND organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
            AND revoked_at IS NULL AND consumed_at IS NULL;
    IF NOT FOUND THEN RAISE EXCEPTION 'SANCTION_AUTHORIZATION_REQUIRED' USING ERRCODE = '42501'; END IF;
END;
$$;

CREATE FUNCTION public.record_sanction_platform_audit(target_decision UUID)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE decided public.sanction_case_decisions; details JSONB;
BEGIN
    SELECT * INTO decided FROM public.sanction_case_decisions WHERE id = target_decision
        AND decided_as = 'platform_admin' AND decided_by_user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID;
    IF decided.id IS NULL THEN RAISE EXCEPTION 'SANCTION_AUTHORIZATION_REQUIRED' USING ERRCODE = '42501'; END IF;
    PERFORM public.sanction_lock_platform_authorization(decided.case_id);
    IF decided.authorization_id IS DISTINCT FROM NULLIF(current_setting('app.sanction_authorization_id', true), '')::UUID THEN
        RAISE EXCEPTION 'SANCTION_AUTHORIZATION_REQUIRED' USING ERRCODE = '42501';
    END IF;
    details := jsonb_build_object('decision_id', decided.id, 'authorization_id', decided.authorization_id, 'decision', decided.decision);
    IF NOT EXISTS (SELECT 1 FROM public.platform_audit_logs WHERE action = 'DECIDE_SANCTION_CASE'
        AND target_id = decided.case_id AND payload->>'decision_id' = decided.id::TEXT) THEN
        INSERT INTO public.platform_audit_logs(actor_user_id, action, target_type, target_id, organization_id, payload)
            VALUES (decided.decided_by_user_id, 'DECIDE_SANCTION_CASE', 'sanction_cases', decided.case_id, decided.organization_id, details);
        INSERT INTO public.administrative_audit_logs(organization_id, entity_type, entity_id, action, payload, performed_by_user_id)
            VALUES (decided.organization_id, 'sanction_cases', decided.case_id, 'DECIDE_SANCTION_CASE', details, decided.decided_by_user_id);
    END IF;
END;
$$;

CREATE FUNCTION public.sanction_consume_authorization()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    IF NEW.status = 'resolved' THEN
        UPDATE public.sanction_platform_authorizations a SET consumed_at = CURRENT_TIMESTAMP
            FROM public.sanction_case_decisions d WHERE d.case_id = NEW.id AND d.decided_as = 'platform_admin'
                AND a.id = d.authorization_id AND a.case_id = NEW.id AND a.organization_id = NEW.organization_id;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_sanction_consume_authorization AFTER UPDATE ON public.sanction_cases
    FOR EACH ROW EXECUTE FUNCTION public.sanction_consume_authorization();

CREATE POLICY f9_platform_read ON public.sanction_cases FOR SELECT TO bracket_app USING (public.sanction_platform_scope(id));
DO $platform_read$
DECLARE target TEXT;
BEGIN
    FOREACH target IN ARRAY ARRAY['sanction_case_events', 'sanction_case_decisions', 'sanction_resolutions', 'sanction_prejudice_records'] LOOP
        EXECUTE format('CREATE POLICY f9_platform_read ON public.%I FOR SELECT TO bracket_app
            USING (public.sanction_platform_scope(case_id))', target);
    END LOOP;
END;
$platform_read$;
CREATE POLICY f9_authorization_insert ON public.sanction_platform_authorizations FOR INSERT TO bracket_app
    WITH CHECK (granted_by_member_id = public.sanction_owner(organization_id));
CREATE POLICY f9_authorization_scope_read ON public.sanction_platform_authorizations FOR SELECT TO bracket_app
    USING (public.sanction_owner(organization_id) IS NOT NULL OR
        (id = NULLIF(current_setting('app.sanction_authorization_id', true), '')::UUID AND public.sanction_platform_scope(case_id)));
GRANT INSERT ON public.sanction_platform_authorizations TO bracket_app;

REVOKE ALL ON FUNCTION public.sanction_owner(UUID), public.sanction_platform_candidate(TEXT),
    public.sanction_valid_platform_authorizations(), public.sanction_platform_scopes(),
    public.sanction_lock_platform_authorization(UUID), public.sanction_platform_source(UUID),
    public.sanction_revoke_authorization(UUID), public.record_sanction_platform_audit(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sanction_owner(UUID), public.sanction_platform_candidate(TEXT),
    public.sanction_platform_scopes(), public.sanction_lock_platform_authorization(UUID),
    public.sanction_platform_source(UUID), public.sanction_revoke_authorization(UUID),
    public.record_sanction_platform_audit(UUID) TO bracket_app;

CREATE FUNCTION public.close_sanction_cases_for_rectification(target_version UUID)
RETURNS INTEGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE version public.match_report_versions; target public.sanction_cases; changed INTEGER := 0;
    actor UUID := NULLIF(current_setting('app.current_user_id', true), '')::UUID;
BEGIN
    SELECT v.* INTO version FROM public.match_report_versions v
        JOIN public.match_report_rectification_requests q ON q.id = v.request_id AND q.organization_id = v.organization_id
        WHERE v.id = target_version AND v.organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
            AND v.published_by_user_id = actor AND q.requested_by_user_id <> actor
            AND v.xmin = pg_current_xact_id()::xid AND v.published_at >= CURRENT_TIMESTAMP;
    IF version.id IS NULL OR NOT (public.sanction_member_has_permission(version.organization_id, 'APPROVE_MATCH_REPORT_RECTIFICATION')
        OR EXISTS (SELECT 1 FROM public.rectification_platform_scopes() a WHERE a.request_id = version.request_id
            AND a.organization_id = version.organization_id
            AND a.id = NULLIF(current_setting('app.rectification_authorization_id', true), '')::UUID)) THEN
        RAISE EXCEPTION 'SANCTION_RECTIFICATION_PUBLICATION_REQUIRED' USING ERRCODE = '42501';
    END IF;
    FOR target IN SELECT c.* FROM public.sanction_cases c
        JOIN public.player_suspensions ps ON ps.id = c.suspension_id AND ps.organization_id = c.organization_id
        JOIN public.player_suspension_annulments a ON a.suspension_id = ps.id AND a.organization_id = ps.organization_id
        WHERE a.version_id = version.id AND ps.origin_match_id = version.match_id AND ps.source_type = 'match_event'
            AND ps.status = 'cancelled' AND c.status IN ('pending', 'resolved') ORDER BY c.id FOR UPDATE OF c
    LOOP
        INSERT INTO public.sanction_case_events(organization_id, case_id, event_type, actor_user_id, reason, rectification_version_id)
            VALUES (target.organization_id, target.id,
                CASE WHEN target.status = 'pending' THEN 'closed_by_rectification' ELSE 'affected_by_rectification' END,
                actor, 'Source sanction changed by published rectification', version.id) ON CONFLICT DO NOTHING;
        IF FOUND THEN
            changed := changed + 1;
            IF target.status = 'pending' THEN PERFORM public.sanction_finalize_case(target.id); END IF;
        END IF;
    END LOOP;
    RETURN changed;
END;
$$;
REVOKE ALL ON FUNCTION public.close_sanction_cases_for_rectification(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.close_sanction_cases_for_rectification(UUID) TO bracket_app;

CREATE FUNCTION public.sanction_recipient_allowed(target_case UUID, recipient UUID)
RETURNS BOOLEAN LANGUAGE SQL STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT EXISTS (SELECT 1 FROM public.sanction_cases c
        JOIN public.users u ON u.id = recipient AND u.is_active
        JOIN public.organizations o ON o.id = c.organization_id AND o.is_active
        JOIN public.organization_users ou ON ou.user_id = u.id AND ou.organization_id = c.organization_id AND ou.is_active
        JOIN public.organization_user_roles our ON our.organization_user_id = ou.id AND our.organization_id = ou.organization_id
        JOIN public.roles r ON r.id = our.role_id AND r.organization_id = ou.organization_id
        WHERE c.id = target_case AND (r.permissions @> '["RESOLVE_SANCTION_CASES"]'::JSONB
            OR (c.submitted_by_user_id = u.id AND r.permissions @> jsonb_build_array(
                CASE WHEN c.case_type = 'appeal' THEN 'SUBMIT_SANCTION_APPEALS' ELSE 'RESOLVE_SANCTION_CASES' END))));
$$;

CREATE FUNCTION public.sanction_notice_recipient_authorized(target_notice UUID)
RETURNS BOOLEAN LANGUAGE SQL STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT EXISTS (SELECT 1 FROM public.sanction_notifications n WHERE n.id = target_notice
        AND public.sanction_recipient_allowed(n.case_id, n.recipient_user_id));
$$;

CREATE FUNCTION public.sanction_notice_visible(target_notice UUID)
RETURNS BOOLEAN LANGUAGE SQL STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT EXISTS (SELECT 1 FROM public.sanction_notifications n WHERE n.id = target_notice
        AND n.organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND n.recipient_user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
        AND public.sanction_notice_recipient_authorized(n.id));
$$;

CREATE FUNCTION public.sanction_notice_writer(target_case UUID)
RETURNS BOOLEAN LANGUAGE SQL STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT EXISTS (SELECT 1 FROM public.sanction_cases c WHERE c.id = target_case
        AND c.organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND (EXISTS (SELECT 1 FROM public.sanction_case_decisions d WHERE d.case_id = c.id
            AND d.decided_by_user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
            AND d.xmin = pg_current_xact_id()::xid)
        OR EXISTS (SELECT 1 FROM public.sanction_case_events e WHERE e.case_id = c.id
            AND e.event_type IN ('withdrawn', 'closed_by_rectification')
            AND e.actor_user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
            AND e.xmin = pg_current_xact_id()::xid)));
$$;

CREATE FUNCTION public.sanction_validate_notice()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE expected_reason TEXT; event public.outbox_events;
BEGIN
    IF NEW.notification_type = 'decision' AND NEW.case_event_id IS NULL THEN
        SELECT reason INTO expected_reason FROM public.sanction_case_decisions
            WHERE id = NEW.decision_id AND case_id = NEW.case_id AND organization_id = NEW.organization_id;
    ELSIF NEW.notification_type IN ('withdrawn', 'closed_by_rectification') AND NEW.decision_id IS NULL THEN
        SELECT reason INTO expected_reason FROM public.sanction_case_events WHERE id = NEW.case_event_id
            AND case_id = NEW.case_id AND organization_id = NEW.organization_id AND event_type = NEW.notification_type;
    END IF;
    SELECT * INTO event FROM public.outbox_events WHERE id = NEW.outbox_event_id;
    IF expected_reason IS NULL OR NEW.reason <> expected_reason OR NOT public.sanction_notice_writer(NEW.case_id)
        OR NOT public.sanction_recipient_allowed(NEW.case_id, NEW.recipient_user_id)
        OR event.organization_id IS DISTINCT FROM NEW.organization_id OR event.status IS DISTINCT FROM 'pending'
        OR event.event_type IS DISTINCT FROM (CASE WHEN NEW.channel = 'email' THEN 'SANCTION_CASE_NOTICE_EMAIL' ELSE 'SANCTION_CASE_NOTICE_INTERNAL' END)
        OR event.payload IS DISTINCT FROM jsonb_build_object('notification_id', NEW.id::TEXT) THEN
        RAISE EXCEPTION 'SANCTION_INVALID_NOTICE' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_sanction_validate_notice BEFORE INSERT ON public.sanction_notifications
    FOR EACH ROW EXECUTE FUNCTION public.sanction_validate_notice();
CREATE POLICY f9_notice_insert ON public.sanction_notifications FOR INSERT TO bracket_app
    WITH CHECK (public.sanction_notice_writer(case_id));
GRANT INSERT ON public.sanction_notifications TO bracket_app;
DROP POLICY f9_read ON public.sanction_notifications;
CREATE POLICY f9_notice_private_read ON public.sanction_notifications FOR SELECT TO bracket_app
    USING (public.sanction_notice_visible(id));

CREATE TABLE public.sanction_notification_deliveries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    notification_id UUID NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('delivered', 'withheld')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (notification_id, outcome),
    FOREIGN KEY (notification_id, organization_id) REFERENCES public.sanction_notifications(id, organization_id) ON DELETE RESTRICT
);
ALTER TABLE public.sanction_notification_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sanction_notification_deliveries FORCE ROW LEVEL SECURITY;
CREATE POLICY f9_delivery_private_read ON public.sanction_notification_deliveries FOR SELECT TO bracket_app
    USING (public.sanction_notice_visible(notification_id));
GRANT SELECT ON public.sanction_notification_deliveries TO bracket_app;
CREATE TRIGGER trg_sanction_delivery_immutable BEFORE UPDATE OR DELETE ON public.sanction_notification_deliveries
    FOR EACH ROW EXECUTE FUNCTION public.protect_sanction_history();

CREATE FUNCTION public.sanction_claimed_notice(target_event UUID)
RETURNS public.sanction_notifications LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE notice public.sanction_notifications; event public.outbox_events;
BEGIN
    SELECT * INTO event FROM public.outbox_events WHERE id = target_event FOR UPDATE;
    SELECT * INTO notice FROM public.sanction_notifications WHERE outbox_event_id = target_event;
    IF notice.id IS NULL OR event.organization_id IS DISTINCT FROM notice.organization_id
        OR event.status IS DISTINCT FROM 'processing' OR event.locked_at IS NULL OR event.attempts < 1
        OR event.payload IS DISTINCT FROM jsonb_build_object('notification_id', notice.id::TEXT)
        OR event.event_type IS DISTINCT FROM (CASE WHEN notice.channel = 'email' THEN 'SANCTION_CASE_NOTICE_EMAIL' ELSE 'SANCTION_CASE_NOTICE_INTERNAL' END) THEN
        RAISE EXCEPTION 'SANCTION_CLAIMED_NOTICE_REQUIRED' USING ERRCODE = '42501';
    END IF;
    RETURN notice;
END;
$$;

CREATE FUNCTION public.deliver_sanction_notice(target_event UUID)
RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE notice public.sanction_notifications; allowed BOOLEAN;
BEGIN
    notice := public.sanction_claimed_notice(target_event);
    IF notice.channel <> 'internal' THEN RAISE EXCEPTION 'SANCTION_INTERNAL_NOTICE_REQUIRED' USING ERRCODE = '42501'; END IF;
    allowed := public.sanction_notice_recipient_authorized(notice.id);
    INSERT INTO public.sanction_notification_deliveries(organization_id, notification_id, outcome)
        VALUES (notice.organization_id, notice.id, CASE WHEN allowed THEN 'delivered' ELSE 'withheld' END)
        ON CONFLICT DO NOTHING;
    RETURN allowed;
END;
$$;

CREATE FUNCTION public.sanction_notice_email_payload(target_event UUID)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE notice public.sanction_notifications; result JSONB;
BEGIN
    notice := public.sanction_claimed_notice(target_event);
    IF notice.channel <> 'email' THEN RAISE EXCEPTION 'SANCTION_EMAIL_NOTICE_REQUIRED' USING ERRCODE = '42501'; END IF;
    IF NOT public.sanction_notice_recipient_authorized(notice.id) THEN
        INSERT INTO public.sanction_notification_deliveries(organization_id, notification_id, outcome)
            VALUES (notice.organization_id, notice.id, 'withheld') ON CONFLICT DO NOTHING;
        RETURN NULL;
    END IF;
    SELECT jsonb_build_object('recipient', u.email, 'case_id', notice.case_id, 'type', notice.notification_type,
        'decision', d.decision, 'reason', notice.reason) INTO result FROM public.users u
        LEFT JOIN public.sanction_case_decisions d ON d.id = notice.decision_id WHERE u.id = notice.recipient_user_id;
    RETURN result;
END;
$$;

REVOKE ALL ON FUNCTION public.sanction_notice_recipient_authorized(UUID), public.sanction_notice_visible(UUID),
    public.sanction_notice_writer(UUID), public.sanction_claimed_notice(UUID), public.deliver_sanction_notice(UUID),
    public.sanction_notice_email_payload(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sanction_notice_visible(UUID), public.sanction_notice_writer(UUID),
    public.deliver_sanction_notice(UUID), public.sanction_notice_email_payload(UUID) TO bracket_app;

DO $private_functions$
DECLARE target REGPROCEDURE;
BEGIN
    FOR target IN SELECT p.oid::REGPROCEDURE FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND (p.proname LIKE 'sanction_%' OR p.proname LIKE 'protect_sanction_%')
    LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', target);
    END LOOP;
END;
$private_functions$;

COMMIT;
