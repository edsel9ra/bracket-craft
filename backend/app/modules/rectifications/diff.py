import json
from typing import Any, Mapping

from app.modules.matches.schemas import MatchEventPayload

REPORT_FIELDS = (
    "resolution_type", "resolution_reason", "home_score_regular", "away_score_regular",
    "home_score", "away_score", "home_penalties", "away_penalties", "winner_team_id",
)


def _json_value(value):
    return json.loads(json.dumps(value, default=str))


def _fields(before, after, names):
    return [{"field": name, "before": _json_value(before.get(name)), "after": _json_value(after.get(name))}
            for name in names if _json_value(before.get(name)) != _json_value(after.get(name))]


def _events(report):
    events = {}
    for row in report.get("events", ()):
        if row.get("is_voided", False):
            continue
        event = {name: _json_value(row.get(name)) for name in MatchEventPayload.model_fields}
        identity = str(event["client_event_id"])
        if identity in events:
            raise ValueError("client_event_id duplicado")
        event.update(client_event_id=identity, metadata=event["metadata"] or {},
                     added_minute=event["added_minute"] or 0)
        events[identity] = event
    return events


def diff_reports(current: Mapping[str, Any], proposed: Mapping[str, Any]) -> dict:
    before, after = _events(current), _events(proposed)
    changed = []
    for identity in sorted(before.keys() & after.keys()):
        fields = _fields(before[identity], after[identity], MatchEventPayload.model_fields)
        if fields:
            changed.append({"client_event_id": identity, "fields": fields})
    return {"fields": _fields(current, proposed, REPORT_FIELDS), "events": {
        "added": [after[key] for key in sorted(after.keys() - before.keys())],
        "removed": [before[key] for key in sorted(before.keys() - after.keys())],
        "changed": changed,
    }}
