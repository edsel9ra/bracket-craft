"""Fresh-snapshot authorization adapter for organization deliveries."""

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from app.core.database import set_rls_context
from app.core.realtime_policy import (
    ClassifiedEvent, Decision, classify_organization_event, group_recipients, resolve_event_references,
)


@dataclass(frozen=True)
class SocketDecision:
    sid: str
    generation: str
    decision: Decision
    evaluation_time: datetime


class RealtimeAuthorizer:
    def __init__(self, session_factory, clock):
        self.session_factory = session_factory
        self.clock = clock

    async def evaluate(self, event, server_sessions):
        for principals in group_recipients(server_sessions, event.organization_id):
            yield await self.evaluate_batch(event, principals)

    async def evaluate_batch(self, event, principals):
        if not principals:
            return ()
        if len(principals) > 256:
            raise ValueError('Authorization batches are limited to 256 principals')
        evaluation_time = self.clock()
        decisions = {(p.user_id, p.session_id): Decision.INDETERMINATE for p in principals}
        normalized = classify_organization_event(event.envelope) if isinstance(event, ClassifiedEvent) else None
        if normalized != event or normalized is None or any(p.organization_id != event.organization_id for p in principals):
            decisions = dict.fromkeys(decisions, Decision.DENY)
        else:
            refs = resolve_event_references(event.rule, event.envelope['payload'])
            event_data = {'event_type': event.rule.event_type, 'match_id': str(refs.match_id),
                          'tournament_id': str(refs.tournament_id)}
            if event.rule.version_read:
                event_data.update(scope='organization', version_id=str(refs.version_id))
            candidates = [{'user_id': str(p.user_id), 'session_id': str(p.session_id)} for p in principals]
            try:
                async with self.session_factory() as db:
                    async with db.begin():
                        await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
                        evaluation_time = (await db.execute(text('SELECT statement_timestamp()'))).scalar_one()
                        await set_rls_context(db, event.organization_id, principals[0].user_id)
                        result = await db.execute(text('''SELECT * FROM public.authorize_realtime_recipients(
                            :organization_id,CAST(:candidates AS JSONB),CAST(:event AS JSONB),:evaluation_time)'''),
                            {'organization_id': event.organization_id, 'candidates': json.dumps(candidates),
                             'event': json.dumps(event_data), 'evaluation_time': evaluation_time})
                        seen, conflicting = set(), set()
                        for row in result.mappings().all():
                            try:
                                key = (UUID(str(row['user_id'])), UUID(str(row['session_id'])))
                            except (KeyError, TypeError, ValueError):
                                continue
                            if key not in decisions:
                                continue
                            try:
                                value = Decision(row['decision'])
                            except (KeyError, TypeError, ValueError):
                                value = Decision.INDETERMINATE
                            if key in seen and decisions[key] != value:
                                conflicting.add(key)
                            seen.add(key)
                            decisions[key] = Decision.INDETERMINATE if key in conflicting else value
            except Exception:
                decisions = dict.fromkeys(decisions, Decision.INDETERMINATE)
        results = []
        for principal in principals:
            for socket in principal.sockets:
                decision = decisions[(principal.user_id, principal.session_id)]
                if not isinstance(evaluation_time, datetime) or evaluation_time.utcoffset() is None:
                    decision = Decision.INDETERMINATE
                elif socket.jwt_expires_at <= evaluation_time:
                    decision = Decision.DENY
                results.append(SocketDecision(socket.sid, socket.generation, decision, evaluation_time))
        return tuple(results)
