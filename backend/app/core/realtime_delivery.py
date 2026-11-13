import logging
from uuid import uuid4

from app.core.realtime_policy import (
    Decision, build_private_invalidation, classify_organization_event,
    group_recipients, reduce_delivery_state, resolve_event_references,
)


logger = logging.getLogger(__name__)


class PrivateDelivery:
    def __init__(self, sessions, authorizer, validate_context, emit, disconnect, clock):
        self.sessions = sessions
        self.authorizer = authorizer
        self.validate_context = validate_context
        self.emit = emit
        self.disconnect = disconnect
        self.clock = clock
        self.states = {}
        self.controls = set()

    def forget(self, sid, generation=None):
        state = self.states.get(sid)
        if state is not None and (generation is None or state.generation == generation):
            self.states.pop(sid, None)

    def current(self, sid, metadata):
        return self.sessions().get(sid) == metadata

    def suspend(self, sid, metadata):
        if self.current(sid, metadata):
            state = self.states.get(sid)
            if state is not None and state.generation != metadata['generation']:
                state = None
            self.states[sid] = reduce_delivery_state(
                state, Decision.INDETERMINATE, metadata['generation'], self.clock(),
            ).state

    async def control(self, sessions, reason):
        pending = []
        for sid, metadata in sessions.items():
            if self.current(sid, metadata) and sid not in self.controls:
                self.suspend(sid, metadata)
                pending.append((sid, metadata))
        self.controls.update(sid for sid, _ in pending)
        try:
            for start in range(0, len(pending), 256):
                snapshot = dict(pending[start:start + 256])
                try:
                    validations = await self.validate_context(snapshot)
                except Exception:
                    logger.warning('No se pudo revalidar un lote de controles privados')
                    continue
                for sid, metadata in snapshot.items():
                    if not self.current(sid, metadata):
                        self.forget(sid, metadata['generation'])
                        continue
                    valid = validations.get(sid)
                    if valid is False or metadata['jwt_expires_at'] <= self.clock():
                        try:
                            await self.disconnect(sid)
                            self.forget(sid, metadata['generation'])
                        except Exception:
                            logger.warning('No se pudo desconectar un socket invalidado')
                    elif valid is True:
                        try:
                            state = self.states.get(sid)
                            await self.emit('RESYNC', {'event_id': f'resync:{uuid4()}', 'reason': reason}, to=sid)
                            if self.states.get(sid) is state:
                                self.forget(sid, metadata['generation'])
                        except Exception:
                            logger.warning('No se pudo emitir un control privado')
        finally:
            self.controls.difference_update(sid for sid, _ in pending)

    async def recover(self, sids=None):
        snapshot = {}
        for sid, state in tuple(self.states.items()):
            metadata = self.sessions().get(sid)
            if not metadata or metadata.get('generation') != state.generation:
                self.forget(sid, state.generation)
            elif sids is None or sid in sids:
                snapshot[sid] = dict(metadata)
        await self.control(snapshot, 'RELAY_START')

    async def deliver(self, envelope):
        event = classify_organization_event(envelope)
        if event is None:
            return
        registry = self.sessions()
        sessions = (registry.organization_sessions(event.organization_id)
                    if hasattr(registry, 'organization_sessions') else dict(registry))
        sessions = {sid: dict(metadata) for sid, metadata in sessions.items()}
        batches = group_recipients(sessions, event.organization_id)
        payload = build_private_invalidation(event.event_id, resolve_event_references(event.rule, envelope['payload']))
        for principals in batches:
            try:
                results = await self.authorizer.evaluate_batch(event, principals)
            except Exception:
                results = ()
                logger.warning('No se pudo autorizar un lote privado')
            decisions = {}
            for result in results:
                key = (result.sid, result.generation)
                if key in decisions and decisions[key] != result.decision:
                    decisions[key] = Decision.INDETERMINATE
                else:
                    decisions[key] = result.decision
            await self.recover({sid for (sid, _), decision in decisions.items() if decision == Decision.ALLOW})
            for principal in principals:
                for socket in principal.sockets:
                    sid = socket.sid
                    metadata = sessions[sid]
                    if not self.current(sid, metadata):
                        continue
                    decision = decisions.get((sid, socket.generation), Decision.INDETERMINATE)
                    if decision == Decision.INDETERMINATE:
                        self.suspend(sid, metadata)
                    elif decision == Decision.ALLOW and sid in self.controls:
                        self.suspend(sid, metadata)
                    elif decision == Decision.ALLOW and sid not in self.states and sid not in self.controls:
                        if socket.jwt_expires_at <= self.clock():
                            continue
                        try:
                            await self.emit(event.rule.event_type, payload, to=sid)
                        except Exception:
                            self.suspend(sid, metadata)
                            logger.warning('No se pudo emitir una invalidación privada')
