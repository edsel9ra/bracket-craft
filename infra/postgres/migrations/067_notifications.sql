BEGIN;

-- ============================================================================
-- Spec 046 (F6, parte 1, T1): avisos en la bandeja de la app y por correo.
--
-- Tres tablas tenant con RLS forzado: avisos, destinatarios por canal y
-- preferencias por miembro. Los avisos se registran con record_notification
-- dentro de la transacción del hecho; el worker los entrega con las funciones
-- de entrega, que revalidan la membresía y la preferencia (RF-007).
-- El correo se reclama aparte (claim_notification_email_events) para que un
-- SMTP lento no frene el bucle principal del outbox (RNF-002).
-- Idempotente: reaplicarla no cambia nada.
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    notification_type TEXT NOT NULL CHECK (notification_type IN
        ('match_scheduled', 'result_confirmed', 'walkover_declared', 'sanction_generated')),
    tournament_id UUID NOT NULL,
    match_id UUID,
    suspension_id UUID,
    match_count INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_notification_context UNIQUE (id, organization_id),
    CONSTRAINT fk_notification_tournament FOREIGN KEY (tournament_id, organization_id)
        REFERENCES public.tournaments(id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT fk_notification_match FOREIGN KEY (match_id, organization_id)
        REFERENCES public.matches(id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT fk_notification_suspension FOREIGN KEY (suspension_id, organization_id)
        REFERENCES public.player_suspensions(id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT chk_notification_shape CHECK (
        (notification_type = 'match_scheduled' AND match_id IS NULL AND suspension_id IS NULL
            AND match_count IS NOT NULL AND match_count > 0)
        OR (notification_type IN ('result_confirmed', 'walkover_declared') AND match_id IS NOT NULL
            AND suspension_id IS NULL AND match_count IS NULL)
        OR (notification_type = 'sanction_generated' AND match_id IS NOT NULL
            AND suspension_id IS NOT NULL AND match_count IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS public.notification_recipients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    notification_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    channel TEXT NOT NULL CHECK (channel IN ('inbox', 'email')),
    outbox_event_id UUID NOT NULL REFERENCES public.outbox_events(id) ON DELETE RESTRICT,
    outcome TEXT NOT NULL DEFAULT 'pending' CHECK (outcome IN ('pending', 'delivered', 'withheld')),
    delivered_at TIMESTAMPTZ,
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_notification_recipient UNIQUE (notification_id, user_id, channel),
    CONSTRAINT fk_notification_recipient_notice FOREIGN KEY (notification_id, organization_id)
        REFERENCES public.notifications(id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT chk_notification_recipient_delivery CHECK (
        (outcome = 'delivered') = (delivered_at IS NOT NULL)
        AND (read_at IS NULL OR (channel = 'inbox' AND outcome = 'delivered'))
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_recipient_email_event
    ON public.notification_recipients (outbox_event_id) WHERE channel = 'email';
CREATE INDEX IF NOT EXISTS idx_notification_recipients_inbox
    ON public.notification_recipients (organization_id, user_id, created_at DESC, notification_id DESC)
    WHERE channel = 'inbox' AND outcome = 'delivered';
CREATE INDEX IF NOT EXISTS idx_notification_recipients_pending
    ON public.notification_recipients (notification_id) WHERE outcome = 'pending';

CREATE TABLE IF NOT EXISTS public.notification_preferences (
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    notification_type TEXT NOT NULL CHECK (notification_type IN
        ('match_scheduled', 'result_confirmed', 'walkover_declared', 'sanction_generated')),
    channel TEXT NOT NULL CHECK (channel IN ('inbox', 'email')),
    enabled BOOLEAN NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (organization_id, user_id, notification_type, channel)
);

ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notifications FORCE ROW LEVEL SECURITY;
ALTER TABLE public.notification_recipients ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notification_recipients FORCE ROW LEVEL SECURITY;
ALTER TABLE public.notification_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notification_preferences FORCE ROW LEVEL SECURITY;

REVOKE ALL ON public.notifications, public.notification_recipients,
    public.notification_preferences FROM PUBLIC, bracket_app;
GRANT SELECT ON public.notifications, public.notification_recipients TO bracket_app;
GRANT SELECT, INSERT, UPDATE ON public.notification_preferences TO bracket_app;

CREATE OR REPLACE FUNCTION public.notification_member_active(p_org UUID, p_user UUID)
RETURNS BOOLEAN LANGUAGE SQL STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT EXISTS (SELECT 1 FROM public.organization_users ou
        JOIN public.users u ON u.id = ou.user_id AND u.is_active
        JOIN public.organizations o ON o.id = ou.organization_id AND o.is_active
        WHERE ou.organization_id = p_org AND ou.user_id = p_user AND ou.is_active);
$$;

CREATE OR REPLACE FUNCTION public.notification_channel_enabled(p_org UUID, p_user UUID, p_type TEXT, p_channel TEXT)
RETURNS BOOLEAN LANGUAGE SQL STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    -- Sin preferencia guardada: bandeja activada y correo desactivado (DA-2).
    SELECT COALESCE((SELECT p.enabled FROM public.notification_preferences p
        WHERE p.organization_id = p_org AND p.user_id = p_user
          AND p.notification_type = p_type AND p.channel = p_channel), p_channel = 'inbox');
$$;

DROP POLICY IF EXISTS notifications_own_read ON public.notifications;
CREATE POLICY notifications_own_read ON public.notifications FOR SELECT TO bracket_app
    USING (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND EXISTS (SELECT 1 FROM public.notification_recipients r
            WHERE r.notification_id = notifications.id AND r.organization_id = notifications.organization_id
              AND r.user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
              AND r.channel = 'inbox' AND r.outcome = 'delivered'));

DROP POLICY IF EXISTS notification_recipients_own_read ON public.notification_recipients;
CREATE POLICY notification_recipients_own_read ON public.notification_recipients FOR SELECT TO bracket_app
    USING (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID);

DROP POLICY IF EXISTS notification_preferences_own ON public.notification_preferences;
CREATE POLICY notification_preferences_own ON public.notification_preferences FOR ALL TO bracket_app
    USING (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
        AND public.notification_member_active(organization_id, user_id))
    WITH CHECK (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
        AND public.notification_member_active(organization_id, user_id));

CREATE OR REPLACE FUNCTION public.record_notification(p_type TEXT, p_tournament UUID, p_match UUID,
    p_suspension UUID, p_match_count INT)
RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    v_org UUID := NULLIF(current_setting('app.current_organization_id', true), '')::UUID;
    v_user UUID := NULLIF(current_setting('app.current_user_id', true), '')::UUID;
    v_notice UUID := gen_random_uuid();
    v_inbox_event UUID;
    v_email_event UUID;
    v_recipient UUID;
    v_member UUID;
BEGIN
    IF v_org IS NULL OR v_user IS NULL OR NOT public.notification_member_active(v_org, v_user) THEN
        RAISE EXCEPTION 'NOTIFICATION_WRITER_REQUIRED' USING ERRCODE = '42501';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.tournaments t WHERE t.id = p_tournament AND t.organization_id = v_org)
        OR (p_match IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.matches m
            WHERE m.id = p_match AND m.organization_id = v_org AND m.tournament_id = p_tournament))
        OR (p_suspension IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.player_suspensions s
            WHERE s.id = p_suspension AND s.organization_id = v_org
              AND s.source_tournament_id = p_tournament AND s.origin_match_id = p_match)) THEN
        RAISE EXCEPTION 'NOTIFICATION_SUBJECT_REQUIRED' USING ERRCODE = '42501';
    END IF;
    INSERT INTO public.notifications (id, organization_id, notification_type, tournament_id, match_id,
        suspension_id, match_count)
    VALUES (v_notice, v_org, p_type, p_tournament, p_match, p_suspension, p_match_count);
    INSERT INTO public.outbox_events (organization_id, event_type, payload)
    VALUES (v_org, 'NOTIFICATION_INBOX', jsonb_build_object('notification_id', v_notice::TEXT))
    RETURNING id INTO v_inbox_event;
    FOR v_member IN
        SELECT ou.user_id FROM public.organization_users ou
        WHERE ou.organization_id = v_org AND public.notification_member_active(v_org, ou.user_id)
        ORDER BY ou.user_id
    LOOP
        IF public.notification_channel_enabled(v_org, v_member, p_type, 'inbox') THEN
            INSERT INTO public.notification_recipients (organization_id, notification_id, user_id, channel, outbox_event_id)
            VALUES (v_org, v_notice, v_member, 'inbox', v_inbox_event);
        END IF;
        IF public.notification_channel_enabled(v_org, v_member, p_type, 'email') THEN
            v_recipient := gen_random_uuid();
            INSERT INTO public.outbox_events (organization_id, event_type, payload)
            VALUES (v_org, 'NOTIFICATION_EMAIL', jsonb_build_object('recipient_id', v_recipient::TEXT))
            RETURNING id INTO v_email_event;
            INSERT INTO public.notification_recipients (id, organization_id, notification_id, user_id, channel, outbox_event_id)
            VALUES (v_recipient, v_org, v_notice, v_member, 'email', v_email_event);
        END IF;
    END LOOP;
    RETURN v_notice;
END;
$$;

CREATE OR REPLACE FUNCTION public.notification_claimed_event(p_event UUID, p_type TEXT)
RETURNS public.outbox_events LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE event public.outbox_events;
BEGIN
    SELECT * INTO event FROM public.outbox_events WHERE id = p_event FOR UPDATE;
    IF event.id IS NULL OR event.event_type IS DISTINCT FROM p_type OR event.status IS DISTINCT FROM 'processing'
        OR event.locked_at IS NULL OR event.attempts < 1 THEN
        RAISE EXCEPTION 'NOTIFICATION_CLAIMED_EVENT_REQUIRED' USING ERRCODE = '42501';
    END IF;
    RETURN event;
END;
$$;

CREATE OR REPLACE FUNCTION public.deliver_notification_inbox(p_event UUID)
RETURNS INT LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE event public.outbox_events; notice public.notifications; delivered INT;
BEGIN
    event := public.notification_claimed_event(p_event, 'NOTIFICATION_INBOX');
    SELECT * INTO notice FROM public.notifications n
        WHERE event.payload = jsonb_build_object('notification_id', n.id::TEXT)
          AND n.organization_id = event.organization_id;
    IF notice.id IS NULL THEN
        RAISE EXCEPTION 'NOTIFICATION_CLAIMED_EVENT_REQUIRED' USING ERRCODE = '42501';
    END IF;
    UPDATE public.notification_recipients r
    SET outcome = CASE WHEN public.notification_member_active(r.organization_id, r.user_id)
            AND public.notification_channel_enabled(r.organization_id, r.user_id, notice.notification_type, 'inbox')
            THEN 'delivered' ELSE 'withheld' END,
        delivered_at = CASE WHEN public.notification_member_active(r.organization_id, r.user_id)
            AND public.notification_channel_enabled(r.organization_id, r.user_id, notice.notification_type, 'inbox')
            THEN CURRENT_TIMESTAMP END
    WHERE r.notification_id = notice.id AND r.organization_id = notice.organization_id
      AND r.channel = 'inbox' AND r.outcome = 'pending';
    SELECT count(*) INTO delivered FROM public.notification_recipients r
        WHERE r.notification_id = notice.id AND r.channel = 'inbox' AND r.outcome = 'delivered';
    RETURN delivered;
END;
$$;

CREATE OR REPLACE FUNCTION public.notification_claimed_email(p_event UUID)
RETURNS public.notification_recipients LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE event public.outbox_events; recipient public.notification_recipients;
BEGIN
    event := public.notification_claimed_event(p_event, 'NOTIFICATION_EMAIL');
    SELECT * INTO recipient FROM public.notification_recipients r
        WHERE r.outbox_event_id = event.id AND r.channel = 'email' AND r.organization_id = event.organization_id
          AND event.payload = jsonb_build_object('recipient_id', r.id::TEXT)
        FOR UPDATE;
    IF recipient.id IS NULL THEN
        RAISE EXCEPTION 'NOTIFICATION_CLAIMED_EVENT_REQUIRED' USING ERRCODE = '42501';
    END IF;
    RETURN recipient;
END;
$$;

CREATE OR REPLACE FUNCTION public.notification_email_payload(p_event UUID)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE recipient public.notification_recipients; notice public.notifications; result JSONB;
BEGIN
    recipient := public.notification_claimed_email(p_event);
    IF recipient.outcome <> 'pending' THEN
        RETURN NULL;
    END IF;
    SELECT * INTO notice FROM public.notifications WHERE id = recipient.notification_id;
    IF NOT public.notification_member_active(recipient.organization_id, recipient.user_id)
        OR NOT public.notification_channel_enabled(recipient.organization_id, recipient.user_id,
            notice.notification_type, 'email') THEN
        UPDATE public.notification_recipients SET outcome = 'withheld' WHERE id = recipient.id;
        RETURN NULL;
    END IF;
    -- DA-4: el correo nunca lleva el nombre del jugador sancionado.
    SELECT jsonb_build_object(
        'recipient', u.email,
        'notification_id', notice.id::TEXT,
        'type', notice.notification_type,
        'tournament_name', t.name,
        'match_id', notice.match_id::TEXT,
        'home_team_name', home.name,
        'away_team_name', away.name,
        'match_count', notice.match_count)
    INTO result
    FROM public.users u
    JOIN public.tournaments t ON t.id = notice.tournament_id AND t.organization_id = notice.organization_id
    LEFT JOIN public.matches m ON m.id = notice.match_id AND m.organization_id = notice.organization_id
    LEFT JOIN public.teams home ON home.id = m.home_team_id AND home.organization_id = notice.organization_id
    LEFT JOIN public.teams away ON away.id = m.away_team_id AND away.organization_id = notice.organization_id
    WHERE u.id = recipient.user_id;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_notification_email_delivery(p_event UUID)
RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE recipient public.notification_recipients;
BEGIN
    recipient := public.notification_claimed_email(p_event);
    UPDATE public.notification_recipients SET outcome = 'delivered', delivered_at = CURRENT_TIMESTAMP
        WHERE id = recipient.id AND outcome = 'pending';
    RETURN FOUND;
END;
$$;

CREATE OR REPLACE FUNCTION public.mark_notifications_read(p_ids UUID[])
RETURNS INT LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    v_org UUID := NULLIF(current_setting('app.current_organization_id', true), '')::UUID;
    v_user UUID := NULLIF(current_setting('app.current_user_id', true), '')::UUID;
    marked INT;
BEGIN
    IF v_org IS NULL OR v_user IS NULL OR NOT public.notification_member_active(v_org, v_user) THEN
        RAISE EXCEPTION 'NOTIFICATION_READER_REQUIRED' USING ERRCODE = '42501';
    END IF;
    UPDATE public.notification_recipients r SET read_at = CURRENT_TIMESTAMP
    WHERE r.organization_id = v_org AND r.user_id = v_user AND r.channel = 'inbox'
      AND r.outcome = 'delivered' AND r.read_at IS NULL
      AND (p_ids IS NULL OR r.notification_id = ANY(p_ids));
    GET DIAGNOSTICS marked = ROW_COUNT;
    RETURN marked;
END;
$$;

CREATE OR REPLACE FUNCTION public.claim_outbox_events(p_limit INT DEFAULT 20)
RETURNS TABLE (id UUID, organization_id UUID, event_type VARCHAR, payload JSONB)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    RETURN QUERY
    WITH candidates AS (
        SELECT oe.id
        FROM public.outbox_events oe
        WHERE oe.event_type <> 'NOTIFICATION_EMAIL'
          AND ((oe.status = 'pending' AND oe.available_at <= CURRENT_TIMESTAMP)
            OR (oe.status = 'processing' AND oe.locked_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes'))
        ORDER BY oe.created_at
        FOR UPDATE SKIP LOCKED
        LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 20), 100))
    )
    UPDATE public.outbox_events oe
    SET status = 'processing', locked_at = CURRENT_TIMESTAMP, attempts = oe.attempts + 1
    FROM candidates
    WHERE oe.id = candidates.id
    RETURNING oe.id, oe.organization_id, oe.event_type, oe.payload;
END;
$$;

CREATE OR REPLACE FUNCTION public.claim_notification_email_events(p_limit INT DEFAULT 20)
RETURNS TABLE (id UUID, organization_id UUID, event_type VARCHAR, payload JSONB)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    RETURN QUERY
    WITH candidates AS (
        SELECT oe.id
        FROM public.outbox_events oe
        WHERE oe.event_type = 'NOTIFICATION_EMAIL'
          AND ((oe.status = 'pending' AND oe.available_at <= CURRENT_TIMESTAMP)
            OR (oe.status = 'processing' AND oe.locked_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes'))
        ORDER BY oe.created_at
        FOR UPDATE SKIP LOCKED
        LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 20), 100))
    )
    UPDATE public.outbox_events oe
    SET status = 'processing', locked_at = CURRENT_TIMESTAMP, attempts = oe.attempts + 1
    FROM candidates
    WHERE oe.id = candidates.id
    RETURNING oe.id, oe.organization_id, oe.event_type, oe.payload;
END;
$$;

REVOKE ALL ON FUNCTION public.notification_member_active(UUID, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.notification_channel_enabled(UUID, UUID, TEXT, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.record_notification(TEXT, UUID, UUID, UUID, INT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.notification_claimed_event(UUID, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.deliver_notification_inbox(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.notification_claimed_email(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.notification_email_payload(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.record_notification_email_delivery(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.mark_notifications_read(UUID[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_outbox_events(INT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_notification_email_events(INT) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.notification_member_active(UUID, UUID) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.record_notification(TEXT, UUID, UUID, UUID, INT) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.deliver_notification_inbox(UUID) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.notification_email_payload(UUID) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.record_notification_email_delivery(UUID) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.mark_notifications_read(UUID[]) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.claim_outbox_events(INT) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.claim_notification_email_events(INT) TO bracket_app;

COMMIT;
