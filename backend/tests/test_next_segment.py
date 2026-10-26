"""Propuesta del siguiente segmento (spec 017, T5): función pura y respuesta aditiva.

**Regla (RF-015).** ``GET /matches/{id}/operation`` devuelve
``next_segment: {segment_number, minute_start, derived}`` derivado de lo
persistido, o **nulo** cuando el partido es terminal o su versión no está
publicada (no se podría crear ningún segmento, D-7). Es una propuesta de solo
lectura: no crea ni modifica nada y no añade consultas (RNF-008); el servidor
sigue siendo la autoridad al crear (RF-013/RF-014).

Los cinco casos de la propuesta:

============================  =================  ===================  ==========
Último segmento                ``segment_number``  ``minute_start``     ``derived``
============================  =================  ===================  ==========
(ninguno)                     1                  0                    verdadero
``interrupted``               n + 1              minuto de la         verdadero
                                                 interrupción
``completed`` con ``minute_end``  n + 1           ``minute_end``       verdadero
``active``                    n + 1              nulo                 falso
``completed`` sin ``minute_end``  n + 1           nulo                 falso
============================  =================  ===================  ==========

Un último segmento **interrumpido** sin fila de interrupción es un dato anómalo:
se trata como «no hay de dónde derivarlo» (``{n+1, nulo, falso}``), igual que el
completado sin fin (plan §4.4). ``suspended`` **sí** recibe propuesta: la ruta de
creación de segmentos lo admite hoy, así que negarla ofrecería menos de lo que el
servidor permite.

Sin PostgreSQL: la función es pura y la ruta se ejerce con una sesión doble que
registra todas las sentencias. La comprobación con base de que la lectura no
escribe ya existe en ``test_match_operation_audit.py``; aquí se repite en la
propia respuesta (sin ``INSERT``/``UPDATE``/``DELETE``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.modules.matches import router as matches_router
from app.modules.matches.schemas import MatchOperationResponse, NextSegmentProposal
from app.modules.matches.service import next_segment_proposal

ORGANIZATION_ID = UUID(int=9101)
USER_ID = UUID(int=9102)
MEMBER_ID = UUID(int=9103)
TOURNAMENT_ID = UUID(int=9104)
STAGE_ID = UUID(int=9105)
MATCH_ID = UUID(int=9106)
SEGMENT_1 = UUID(int=9107)
SEGMENT_2 = UUID(int=9108)
SEGMENT_3 = UUID(int=9109)
HOME_TEAM = UUID(int=9110)
AWAY_TEAM = UUID(int=9111)

CREATED_AT = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

EXISTING_OPERATION_KEYS = {
    "match",
    "segments",
    "interruptions",
    "officials",
    "eligible_officials",
    "rosters",
    "lineup",
    "tactical_lineups",
    "events",
    "substitutions",
    "limits",
}


# ---------------------------------------------------------------------------
# La función pura: deriva de lo persistido, sin base, sin reloj
# ---------------------------------------------------------------------------


def segment(
    number: int,
    *,
    segment_id: UUID | None = None,
    status: str = "active",
    minute_start: int = 0,
    minute_end: int | None = None,
) -> dict:
    """Un segmento en la forma de ``mapping`` que lee la operación."""

    return {
        "id": segment_id if segment_id is not None else UUID(int=9300 + number),
        "segment_number": number,
        "minute_start": minute_start,
        "minute_end": minute_end,
        "status": status,
    }


def interruption(
    segment_id: UUID,
    minute: int,
    *,
    created_at: datetime = CREATED_AT,
    interruption_id: UUID | None = None,
) -> dict:
    """Una interrupción en la forma de ``mapping`` que lee la operación."""

    return {
        "id": interruption_id if interruption_id is not None else UUID(int=9400 + minute),
        "match_id": MATCH_ID,
        "segment_id": segment_id,
        "reason": "weather",
        "minute": minute,
        "notes": None,
        "created_at": created_at,
    }


def test_without_segments_it_proposes_the_first_one():
    proposal = next_segment_proposal("scheduled", "published", [], [])

    assert proposal == {"segment_number": 1, "minute_start": 0, "derived": True}


def test_an_interrupted_segment_proposes_its_interruption_minute():
    first = segment(1, status="interrupted", minute_start=0, minute_end=37)

    proposal = next_segment_proposal(
        "scheduled",
        "published",
        [first],
        [interruption(first["id"], 37)],
    )

    assert proposal == {"segment_number": 2, "minute_start": 37, "derived": True}


def test_the_last_interruption_of_the_segment_is_the_restart_minute():
    first = segment(1, status="completed", minute_start=0, minute_end=20)
    second = segment(2, status="interrupted", minute_start=20, minute_end=48)
    earlier = interruption(
        second["id"], 30, created_at=datetime(2026, 5, 1, 12, 30, tzinfo=timezone.utc)
    )
    later = interruption(
        second["id"], 48, created_at=datetime(2026, 5, 1, 13, 0, tzinfo=timezone.utc)
    )

    proposal = next_segment_proposal(
        "scheduled", "published", [first, second], [later, earlier]
    )

    # El orden de la consulta no cambia el resultado (RNF-006): manda el minuto
    # y, en empate, el registro más reciente.
    assert proposal == {"segment_number": 3, "minute_start": 48, "derived": True}


def test_an_interruption_of_another_segment_does_not_count():
    first = segment(1, status="interrupted", minute_start=0, minute_end=30)
    second = segment(2, status="active", minute_start=30)

    proposal = next_segment_proposal(
        "scheduled",
        "published",
        [first, second],
        [interruption(first["id"], 30)],
    )

    # Manda el último segmento (activo): no hereda la interrupción del primero.
    assert proposal == {"segment_number": 3, "minute_start": None, "derived": False}


def test_a_completed_segment_proposes_its_end():
    first = segment(1, status="completed", minute_start=0, minute_end=45)

    proposal = next_segment_proposal("scheduled", "published", [first], [])

    assert proposal == {"segment_number": 2, "minute_start": 45, "derived": True}


def test_an_active_segment_has_no_base_to_derive_from():
    first = segment(1, status="completed", minute_start=0, minute_end=45)
    second = segment(2, status="active", minute_start=45)

    proposal = next_segment_proposal("scheduled", "published", [first, second], [])

    assert proposal == {"segment_number": 3, "minute_start": None, "derived": False}


def test_a_completed_segment_without_end_has_no_base_to_derive_from():
    """Dato histórico posible: ``completed`` sin ``minute_end`` (RF-015)."""

    first = segment(1, status="completed", minute_start=0, minute_end=None)

    proposal = next_segment_proposal("scheduled", "published", [first], [])

    assert proposal == {"segment_number": 2, "minute_start": None, "derived": False}


def test_an_interrupted_segment_without_its_interruption_has_no_base():
    """Dato anómalo: ``interrupted`` sin fila de interrupción (plan §4.4)."""

    first = segment(1, status="interrupted", minute_start=0, minute_end=30)

    proposal = next_segment_proposal("scheduled", "published", [first], [])

    assert proposal == {"segment_number": 2, "minute_start": None, "derived": False}


def test_the_next_number_is_always_the_one_after_the_last():
    segments = [
        segment(1, segment_id=SEGMENT_1, status="completed", minute_end=20),
        segment(2, segment_id=SEGMENT_2, status="completed", minute_end=45),
        segment(3, segment_id=SEGMENT_3, status="active", minute_start=45),
    ]

    proposal = next_segment_proposal("scheduled", "published", segments, [])

    assert proposal["segment_number"] == 4


def test_the_segment_order_in_the_input_does_not_matter():
    segments = [
        segment(1, status="completed", minute_end=20),
        segment(2, status="completed", minute_end=45),
    ]

    ordered = next_segment_proposal("scheduled", "published", segments, [])
    reversed_input = next_segment_proposal("scheduled", "published", list(reversed(segments)), [])

    assert ordered == reversed_input == {"segment_number": 3, "minute_start": 45, "derived": True}


@pytest.mark.parametrize("status", ["finished", "cancelled", "administrative_resolution"])
def test_a_terminal_match_has_no_proposal(status):
    assert next_segment_proposal(status, "published", [segment(1, minute_end=90, status="completed")], []) is None


@pytest.mark.parametrize("version_status", ["draft", "archived"])
def test_an_unpublished_version_has_no_proposal(version_status):
    assert next_segment_proposal("scheduled", version_status, [], []) is None


def test_a_suspended_match_still_gets_a_proposal():
    """La ruta de segmentos admite ``suspended``: la propuesta no ofrece menos."""

    first = segment(1, status="interrupted", minute_start=0, minute_end=30)

    proposal = next_segment_proposal(
        "suspended", "published", [first], [interruption(first["id"], 30)]
    )

    assert proposal == {"segment_number": 2, "minute_start": 30, "derived": True}


def test_the_proposal_is_deterministic():
    segments = [segment(1, status="interrupted", minute_start=0, minute_end=30)]

    first = next_segment_proposal(
        "scheduled", "published", segments, [interruption(segments[0]["id"], 30)]
    )
    second = next_segment_proposal(
        "scheduled", "published", segments, [interruption(segments[0]["id"], 30)]
    )

    assert first == second == {"segment_number": 2, "minute_start": 30, "derived": True}


def test_it_does_not_read_the_clock():
    """Misma entrada, misma salida: la función no consulta el reloj (RNF-006)."""

    import inspect

    source = inspect.getsource(next_segment_proposal)

    assert "now(" not in source
    assert "datetime" not in source
    assert "time." not in source


# ---------------------------------------------------------------------------
# La respuesta de operación: campo aditivo, sin escrituras (RNF-008)
# ---------------------------------------------------------------------------


class Result:
    def __init__(self, rows=None, scalar=None):
        self._rows = list(rows or [])
        self._scalar = scalar

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def one(self):
        return self._rows[0]

    def scalar_one_or_none(self):
        return self._scalar


class Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class RecordingSession:
    """Sesión doble: registra cada sentencia y no escribe nunca."""

    def __init__(self, *, segments, interruptions):
        self.statements: list[str] = []
        self.calls: list[tuple[str, dict]] = []
        self._segments = segments
        self._interruptions = interruptions

    def begin(self):
        return Transaction()

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append(sql)
        self.calls.append((sql, dict(params or {})))
        return self.handle(sql, dict(params or {}))

    @property
    def writes(self) -> list[str]:
        return [
            sql for sql in self.statements
            if sql.upper().startswith(("INSERT", "UPDATE", "DELETE"))
        ]

    @property
    def locks(self) -> list[str]:
        return [sql for sql in self.statements if "FOR UPDATE" in sql.upper()]

    def handle(self, sql: str, params: dict) -> Result:
        if "set_config" in sql:
            return Result()
        if "FROM match_segments" in sql:
            return Result(rows=self._segments)
        if "FROM match_segment_interruptions" in sql:
            return Result(rows=self._interruptions)
        if "FROM match_officials" in sql:
            return Result(rows=[])
        if "FROM organization_users ou" in sql:
            return Result(rows=[])
        if "FROM rosters r" in sql:
            return Result(rows=[])
        if "FROM match_events me" in sql:
            return Result(rows=[])
        raise AssertionError(f"consulta no esperada: {sql}")


def operation_match(*, status: str = "scheduled", version_status: str = "published") -> dict:
    return {
        "id": MATCH_ID,
        "tournament_id": TOURNAMENT_ID,
        "stage_id": STAGE_ID,
        "status": status,
        "version_status": version_status,
        "home_team_id": HOME_TEAM,
        "away_team_id": AWAY_TEAM,
        "rules_config": {},
    }


def _loader(match: dict):
    async def load(db, context_, match_id, require_operation_permission=True, lock=True):
        return match

    return load


async def _empty_lineup(db, organization_id, match_id):
    return []


async def _empty_tactical(db, organization_id, match_id):
    return []


def _patch_operation(monkeypatch, match: dict) -> None:
    monkeypatch.setattr(matches_router, "_load_operation_match", _loader(match))
    monkeypatch.setattr(matches_router, "_load_match_lineup", _empty_lineup)
    monkeypatch.setattr(matches_router, "_load_match_tactical_lineups", _empty_tactical)


def _context():
    from app.core.tenancy import AuthContext

    return AuthContext(
        user_id=USER_ID,
        organization_id=ORGANIZATION_ID,
        organization_user_id=MEMBER_ID,
    )


async def test_the_operation_returns_the_proposal_without_writing(monkeypatch):
    _patch_operation(monkeypatch, operation_match())
    first = segment(1, status="interrupted", minute_start=0, minute_end=37)
    session = RecordingSession(
        segments=[first], interruptions=[interruption(first["id"], 37)]
    )

    response = await matches_router.get_match_operation(MATCH_ID, _context(), session)

    assert response["next_segment"] == {
        "segment_number": 2,
        "minute_start": 37,
        "derived": True,
    }
    # Sin escrituras, sin bloqueos y sin consultas nuevas: los segmentos y las
    # interrupciones son los que la operación ya lee (RNF-008).
    assert session.writes == []
    assert session.locks == []
    assert [sql for sql in session.statements if "FROM match_segments" in sql] != []
    assert not any("match_segment_team_state" in sql for sql in session.statements)


async def test_the_operation_keeps_the_existing_keys_and_adds_only_the_proposal(monkeypatch):
    _patch_operation(monkeypatch, operation_match())
    session = RecordingSession(segments=[], interruptions=[])

    response = await matches_router.get_match_operation(MATCH_ID, _context(), session)

    assert set(response) == EXISTING_OPERATION_KEYS | {"next_segment"}
    # Las claves existentes conservan su tipo: la propuesta es lo único nuevo.
    assert isinstance(response["segments"], list)
    assert isinstance(response["interruptions"], list)
    assert isinstance(response["limits"], dict)


async def test_the_terminal_operation_returns_no_proposal(monkeypatch):
    _patch_operation(monkeypatch, operation_match(status="finished"))
    session = RecordingSession(
        segments=[segment(1, status="completed", minute_start=0, minute_end=90)],
        interruptions=[],
    )

    response = await matches_router.get_match_operation(MATCH_ID, _context(), session)

    assert response["next_segment"] is None


async def test_the_operation_of_an_unpublished_version_returns_no_proposal(monkeypatch):
    _patch_operation(monkeypatch, operation_match(version_status="draft"))
    session = RecordingSession(segments=[], interruptions=[])

    response = await matches_router.get_match_operation(MATCH_ID, _context(), session)

    assert response["next_segment"] is None


# ---------------------------------------------------------------------------
# El modelo tipado es aditivo
# ---------------------------------------------------------------------------


def test_the_proposal_model_has_the_three_declared_keys():
    assert set(NextSegmentProposal.model_fields) == {
        "segment_number",
        "minute_start",
        "derived",
    }
    proposal = NextSegmentProposal(segment_number=2, minute_start=None, derived=False)
    assert proposal.segment_number == 2
    assert proposal.minute_start is None
    assert proposal.derived is False


def test_the_operation_model_adds_next_segment_without_renaming_the_existing_keys():
    assert set(MatchOperationResponse.model_fields) == EXISTING_OPERATION_KEYS | {
        "next_segment"
    }


def test_the_operation_model_accepts_the_proposal_and_null():
    base = {
        "match": {},
        "segments": [],
        "interruptions": [],
        "officials": [],
        "eligible_officials": [],
        "rosters": [],
        "lineup": [],
        "tactical_lineups": [],
        "events": [],
        "substitutions": {},
        "limits": {},
    }

    with_proposal = MatchOperationResponse(
        **base, next_segment={"segment_number": 1, "minute_start": 0, "derived": True}
    )
    without_proposal = MatchOperationResponse(**base, next_segment=None)

    assert with_proposal.next_segment.segment_number == 1
    assert without_proposal.next_segment is None
