BEGIN;

-- ============================================================================
-- Spec 047 (F6, parte 2, T1): webhooks firmados por organización.
--
-- Dos tablas tenant con RLS forzado: los webhooks de cada organización y sus
-- entregas. bracket_app puede escribir el secreto cifrado (WEBHOOK_SECRET_KEY,
-- constitución §3.4) pero nunca leerlo; solo webhook_claimed_delivery lo
-- descifra para el worker. record_notification crea las entregas en la
-- transacción del hecho, y el worker las reclama aparte del outbox principal
-- (claim_webhook_delivery_events) para que un destino lento no frene a los
-- demás bucles. Idempotente: reaplicarla no cambia nada.
-- ============================================================================

UPDATE public.role_definitions
SET system_permissions = system_permissions || '["MANAGE_WEBHOOKS"]'::jsonb
WHERE code IN ('owner', 'administrator')
  AND NOT system_permissions @> '["MANAGE_WEBHOOKS"]'::jsonb;

UPDATE public.roles r
SET permissions = r.permissions || '["MANAGE_WEBHOOKS"]'::jsonb
FROM public.role_definitions rd
WHERE rd.id = r.role_definition_id
  AND rd.code IN ('owner', 'administrator')
  AND NOT r.permissions @> '["MANAGE_WEBHOOKS"]'::jsonb;

CREATE TABLE IF NOT EXISTS public.organization_webhooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    url TEXT NOT NULL CHECK (url LIKE 'https://%' AND char_length(url) <= 2048),
    event_types TEXT[] NOT NULL CHECK (
        cardinality(event_types) > 0
        AND event_types <@ ARRAY['match_scheduled', 'result_confirmed', 'walkover_declared', 'sanction_generated']::TEXT[]),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    secret_encrypted BYTEA NOT NULL,
    created_by_member_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_organization_webhook_context UNIQUE (id, organization_id),
    CONSTRAINT fk_organization_webhook_creator FOREIGN KEY (created_by_member_id, organization_id)
        REFERENCES public.organization_users(id, organization_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_organization_webhooks_org
    ON public.organization_webhooks (organization_id, created_at, id);

CREATE TABLE IF NOT EXISTS public.webhook_deliveries (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    webhook_id UUID NOT NULL,
    notification_id UUID,
    event_type TEXT NOT NULL CHECK (event_type IN
        ('match_scheduled', 'result_confirmed', 'walkover_declared', 'sanction_generated', 'webhook_test')),
    body JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'delivered', 'failed', 'rejected', 'discarded')),
    attempts INT NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 6),
    last_status_code INT CHECK (last_status_code IS NULL OR last_status_code BETWEEN 100 AND 599),
    last_attempt_at TIMESTAMPTZ,
    -- NULL tras purgar el evento procesado (034): la entrega conserva su historial.
    outbox_event_id UUID REFERENCES public.outbox_events(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_webhook_delivery_webhook FOREIGN KEY (webhook_id, organization_id)
        REFERENCES public.organization_webhooks(id, organization_id) ON DELETE CASCADE,
    CONSTRAINT fk_webhook_delivery_notice FOREIGN KEY (notification_id, organization_id)
        REFERENCES public.notifications(id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT chk_webhook_delivery_notice CHECK ((event_type = 'webhook_test') = (notification_id IS NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_webhook_delivery_event
    ON public.webhook_deliveries (outbox_event_id);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_recent
    ON public.webhook_deliveries (organization_id, webhook_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_retention
    ON public.webhook_deliveries (created_at) WHERE status <> 'pending';

ALTER TABLE public.organization_webhooks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_webhooks FORCE ROW LEVEL SECURITY;
ALTER TABLE public.webhook_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.webhook_deliveries FORCE ROW LEVEL SECURITY;

REVOKE ALL ON public.organization_webhooks, public.webhook_deliveries FROM PUBLIC, bracket_app;
GRANT SELECT (id, organization_id, url, event_types, is_active, created_by_member_id, created_at, updated_at)
    ON public.organization_webhooks TO bracket_app;
GRANT INSERT, DELETE ON public.organization_webhooks TO bracket_app;
GRANT UPDATE (url, event_types, is_active, secret_encrypted, updated_at) ON public.organization_webhooks TO bracket_app;
GRANT SELECT ON public.webhook_deliveries TO bracket_app;

DROP POLICY IF EXISTS organization_webhooks_tenant ON public.organization_webhooks;
CREATE POLICY organization_webhooks_tenant ON public.organization_webhooks FOR ALL TO bracket_app
    USING (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID)
    WITH CHECK (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID);

DROP POLICY IF EXISTS webhook_deliveries_tenant_read ON public.webhook_deliveries;
CREATE POLICY webhook_deliveries_tenant_read ON public.webhook_deliveries FOR SELECT TO bracket_app
    USING (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID);

-- Cuerpo de RF-006, fijado al registrar la entrega (CL-6). DA-2: solo datos
-- públicos del hecho; la sanción no lleva jugador ni equipo.
CREATE OR REPLACE FUNCTION public.webhook_event_body(p_delivery UUID, p_org UUID, p_type TEXT,
    p_tournament UUID, p_match UUID, p_match_count INT)
RETURNS JSONB LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    v_tournament TEXT;
    v_match public.matches;
    v_data JSONB := '{}'::jsonb;
    v_body JSONB;
BEGIN
    SELECT t.name INTO v_tournament FROM public.tournaments t WHERE t.id = p_tournament AND t.organization_id = p_org;
    IF p_type = 'match_scheduled' THEN
        v_data := jsonb_build_object('tournament_name', v_tournament, 'match_count', p_match_count);
    ELSIF p_type = 'sanction_generated' THEN
        v_data := jsonb_build_object('tournament_name', v_tournament);
    ELSIF p_type IN ('result_confirmed', 'walkover_declared') THEN
        SELECT * INTO v_match FROM public.matches m WHERE m.id = p_match AND m.organization_id = p_org;
        v_data := jsonb_build_object(
            'tournament_name', v_tournament,
            'home_team', (SELECT jsonb_build_object('id', tm.id::TEXT, 'name', tm.name) FROM public.teams tm
                WHERE tm.id = v_match.home_team_id AND tm.organization_id = p_org),
            'away_team', (SELECT jsonb_build_object('id', tm.id::TEXT, 'name', tm.name) FROM public.teams tm
                WHERE tm.id = v_match.away_team_id AND tm.organization_id = p_org),
            'home_score', v_match.home_score,
            'away_score', v_match.away_score);
        IF p_type = 'walkover_declared' THEN
            v_data := v_data || jsonb_build_object('winner_team_id', v_match.winner_team_id::TEXT);
        END IF;
    END IF;
    v_body := jsonb_build_object(
        'id', p_delivery::TEXT,
        'type', p_type,
        'occurred_at', to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
        'organization_id', p_org::TEXT,
        'data', v_data);
    IF p_tournament IS NOT NULL THEN
        v_body := v_body || jsonb_build_object('tournament_id', p_tournament::TEXT);
    END IF;
    IF p_match IS NOT NULL THEN
        v_body := v_body || jsonb_build_object('match_id', p_match::TEXT);
    END IF;
    RETURN v_body;
END;
$$;

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
    v_webhook UUID;
    v_delivery UUID;
    v_webhook_event UUID;
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
    -- Spec 047 (RF-005): una entrega por webhook activo suscrito al tipo.
    FOR v_webhook IN
        SELECT w.id FROM public.organization_webhooks w
        WHERE w.organization_id = v_org AND w.is_active AND p_type = ANY(w.event_types)
        ORDER BY w.created_at, w.id
    LOOP
        v_delivery := gen_random_uuid();
        INSERT INTO public.outbox_events (organization_id, event_type, payload)
        VALUES (v_org, 'WEBHOOK_DELIVERY', jsonb_build_object('delivery_id', v_delivery::TEXT))
        RETURNING id INTO v_webhook_event;
        INSERT INTO public.webhook_deliveries (id, organization_id, webhook_id, notification_id, event_type, body, outbox_event_id)
        VALUES (v_delivery, v_org, v_webhook, v_notice, p_type,
            public.webhook_event_body(v_delivery, v_org, p_type, p_tournament, p_match, p_match_count), v_webhook_event);
    END LOOP;
    RETURN v_notice;
END;
$$;

-- Webhook de la organización del contexto gestionable por el miembro actual.
CREATE OR REPLACE FUNCTION public.webhook_managed(p_webhook UUID)
RETURNS public.organization_webhooks LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    v_org UUID := NULLIF(current_setting('app.current_organization_id', true), '')::UUID;
    v_webhook public.organization_webhooks;
BEGIN
    IF v_org IS NULL OR NOT public.sanction_member_has_permission(v_org, 'MANAGE_WEBHOOKS') THEN
        RAISE EXCEPTION 'WEBHOOK_MANAGER_REQUIRED' USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_webhook FROM public.organization_webhooks w
        WHERE w.id = p_webhook AND w.organization_id = v_org FOR UPDATE;
    IF v_webhook.id IS NULL THEN
        RAISE EXCEPTION 'WEBHOOK_NOT_FOUND' USING ERRCODE = 'P0002';
    END IF;
    RETURN v_webhook;
END;
$$;

CREATE OR REPLACE FUNCTION public.enqueue_webhook_test(p_webhook UUID)
RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    v_webhook public.organization_webhooks := public.webhook_managed(p_webhook);
    v_delivery UUID := gen_random_uuid();
    v_event UUID;
BEGIN
    IF NOT v_webhook.is_active THEN
        RAISE EXCEPTION 'WEBHOOK_INACTIVE' USING ERRCODE = '55000';
    END IF;
    INSERT INTO public.outbox_events (organization_id, event_type, payload)
    VALUES (v_webhook.organization_id, 'WEBHOOK_DELIVERY', jsonb_build_object('delivery_id', v_delivery::TEXT))
    RETURNING id INTO v_event;
    INSERT INTO public.webhook_deliveries (id, organization_id, webhook_id, event_type, body, outbox_event_id)
    VALUES (v_delivery, v_webhook.organization_id, v_webhook.id, 'webhook_test',
        public.webhook_event_body(v_delivery, v_webhook.organization_id, 'webhook_test', NULL, NULL, NULL), v_event);
    RETURN v_delivery;
END;
$$;

-- RF-008/CL-2: al desactivar, las entregas pendientes se descartan y no vuelven al reactivar.
CREATE OR REPLACE FUNCTION public.discard_webhook_deliveries(p_webhook UUID)
RETURNS INT LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    v_webhook public.organization_webhooks := public.webhook_managed(p_webhook);
    v_discarded INT;
BEGIN
    WITH discarded AS (
        UPDATE public.webhook_deliveries d SET status = 'discarded'
        WHERE d.webhook_id = v_webhook.id AND d.organization_id = v_webhook.organization_id AND d.status = 'pending'
        RETURNING d.outbox_event_id
    ), closed AS (
        UPDATE public.outbox_events e
        SET status = 'processed', processed_at = CURRENT_TIMESTAMP, locked_at = NULL, last_error = 'WEBHOOK_DISCARDED'
        FROM discarded
        WHERE e.id = discarded.outbox_event_id AND e.status = 'pending'
        RETURNING e.id
    )
    SELECT count(*) INTO v_discarded FROM discarded;
    RETURN v_discarded;
END;
$$;

CREATE OR REPLACE FUNCTION public.webhook_claimed_delivery(p_event UUID, p_key TEXT)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    v_event public.outbox_events := public.notification_claimed_event(p_event, 'WEBHOOK_DELIVERY');
    v_delivery public.webhook_deliveries;
    v_webhook public.organization_webhooks;
BEGIN
    SELECT * INTO v_delivery FROM public.webhook_deliveries d
        WHERE v_event.payload = jsonb_build_object('delivery_id', d.id::TEXT)
          AND d.organization_id = v_event.organization_id
        FOR UPDATE;
    IF v_delivery.id IS NULL OR v_delivery.status <> 'pending' THEN
        RETURN NULL;
    END IF;
    SELECT * INTO v_webhook FROM public.organization_webhooks w
        WHERE w.id = v_delivery.webhook_id AND w.organization_id = v_delivery.organization_id;
    IF NOT v_webhook.is_active
        OR (v_delivery.event_type <> 'webhook_test' AND NOT v_delivery.event_type = ANY(v_webhook.event_types)) THEN
        UPDATE public.webhook_deliveries SET status = 'discarded' WHERE id = v_delivery.id;
        RETURN NULL;
    END IF;
    RETURN jsonb_build_object(
        'delivery_id', v_delivery.id::TEXT,
        'url', v_webhook.url,
        'secret', pgp_sym_decrypt(v_webhook.secret_encrypted, p_key),
        'event_type', v_delivery.event_type,
        'body', v_delivery.body);
END;
$$;

-- RF-011: hasta 6 intentos, con esperas de 1, 5, 15 y 30 minutos y 2 horas.
-- Devuelve el estado de la entrega. Los estados finales cierran el evento
-- como procesado para que la retención del outbox (034) pueda purgarlo.
CREATE OR REPLACE FUNCTION public.record_webhook_attempt(p_event UUID, p_outcome TEXT, p_status_code INT)
RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    v_event public.outbox_events;
    v_delivery public.webhook_deliveries;
    v_status TEXT;
    v_waits INTERVAL[] := ARRAY[INTERVAL '1 minute', INTERVAL '5 minutes', INTERVAL '15 minutes',
        INTERVAL '30 minutes', INTERVAL '2 hours'];
BEGIN
    IF p_outcome IS NULL OR p_outcome NOT IN ('delivered', 'failed', 'rejected') THEN
        RAISE EXCEPTION 'WEBHOOK_ATTEMPT_OUTCOME' USING ERRCODE = '22023';
    END IF;
    v_event := public.notification_claimed_event(p_event, 'WEBHOOK_DELIVERY');
    SELECT * INTO v_delivery FROM public.webhook_deliveries d
        WHERE v_event.payload = jsonb_build_object('delivery_id', d.id::TEXT)
          AND d.organization_id = v_event.organization_id
        FOR UPDATE;
    IF v_delivery.id IS NULL OR v_delivery.status <> 'pending' THEN
        v_status := COALESCE(v_delivery.status, 'discarded');
    ELSIF p_outcome = 'failed' AND v_event.attempts < 6 THEN
        v_status := 'pending';
    ELSE
        v_status := p_outcome;
    END IF;
    IF v_delivery.id IS NOT NULL AND v_delivery.status = 'pending' THEN
        UPDATE public.webhook_deliveries
        SET status = v_status, attempts = LEAST(v_event.attempts, 6), last_status_code = p_status_code,
            last_attempt_at = CURRENT_TIMESTAMP
        WHERE id = v_delivery.id;
    END IF;
    IF v_status = 'pending' THEN
        UPDATE public.outbox_events
        SET status = 'pending', locked_at = NULL, last_error = 'WEBHOOK_FAILED',
            available_at = CURRENT_TIMESTAMP + v_waits[v_event.attempts]
        WHERE id = v_event.id;
    ELSE
        UPDATE public.outbox_events
        SET status = 'processed', locked_at = NULL, processed_at = CURRENT_TIMESTAMP,
            last_error = CASE WHEN v_status = 'delivered' THEN NULL ELSE 'WEBHOOK_' || upper(v_status) END
        WHERE id = v_event.id;
    END IF;
    RETURN v_status;
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
        WHERE oe.event_type NOT IN ('NOTIFICATION_EMAIL', 'WEBHOOK_DELIVERY')
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

CREATE OR REPLACE FUNCTION public.claim_webhook_delivery_events(p_limit INT DEFAULT 10)
RETURNS TABLE (id UUID, organization_id UUID, event_type VARCHAR, payload JSONB)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    RETURN QUERY
    WITH candidates AS (
        SELECT oe.id
        FROM public.outbox_events oe
        WHERE oe.event_type = 'WEBHOOK_DELIVERY'
          AND ((oe.status = 'pending' AND oe.available_at <= CURRENT_TIMESTAMP)
            OR (oe.status = 'processing' AND oe.locked_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes'))
        ORDER BY oe.available_at, oe.created_at
        FOR UPDATE SKIP LOCKED
        LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 10), 100))
    )
    UPDATE public.outbox_events oe
    SET status = 'processing', locked_at = CURRENT_TIMESTAMP, attempts = oe.attempts + 1
    FROM candidates
    WHERE oe.id = candidates.id
    RETURNING oe.id, oe.organization_id, oe.event_type, oe.payload;
END;
$$;

-- RF-012: el historial visible cubre 30 días; las entregas finales más antiguas se purgan.
CREATE OR REPLACE FUNCTION public.purge_webhook_deliveries(p_cutoff TIMESTAMPTZ, p_limit INT DEFAULT 500)
RETURNS INT LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE v_deleted INT;
BEGIN
    IF p_cutoff IS NULL OR p_limit IS NULL OR p_limit < 1 OR p_limit > 500 THEN
        RAISE EXCEPTION 'invalid retention parameters';
    END IF;
    WITH candidates AS (
        SELECT d.id FROM public.webhook_deliveries d
        WHERE d.status <> 'pending' AND d.created_at < p_cutoff
        LIMIT p_limit FOR UPDATE SKIP LOCKED
    )
    DELETE FROM public.webhook_deliveries d USING candidates c WHERE d.id = c.id;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$;

REVOKE ALL ON FUNCTION public.webhook_event_body(UUID, UUID, TEXT, UUID, UUID, INT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.record_notification(TEXT, UUID, UUID, UUID, INT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.webhook_managed(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.enqueue_webhook_test(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.discard_webhook_deliveries(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.webhook_claimed_delivery(UUID, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.record_webhook_attempt(UUID, TEXT, INT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_outbox_events(INT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_webhook_delivery_events(INT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.purge_webhook_deliveries(TIMESTAMPTZ, INT) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.record_notification(TEXT, UUID, UUID, UUID, INT) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.enqueue_webhook_test(UUID) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.discard_webhook_deliveries(UUID) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.webhook_claimed_delivery(UUID, TEXT) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.record_webhook_attempt(UUID, TEXT, INT) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.claim_outbox_events(INT) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.claim_webhook_delivery_events(INT) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.purge_webhook_deliveries(TIMESTAMPTZ, INT) TO bracket_app;

COMMIT;
