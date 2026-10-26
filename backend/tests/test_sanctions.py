"""Sanciones (spec 018, T1): derivación pura desde el acta y absorción de la jugada.

**Qué fija esta tarea** (RF-001, RF-002, RF-003, RF-004, RF-005, RF-009, RF-010):

* ``evaluate_suspensions`` conserva nombre y firma (plan D-1): ``current_events``
  es el acta que se cierra y **origina** las sanciones; ``historical_events`` es
  el historial disciplinario y **solo cuenta amarillas**. Una roja histórica no
  crea ninguna fila: el historial nunca origina (RF-005).
* Una expulsión por doble amarilla produce **una** sanción: al final del
  recorrido se absorben **todos** los umbrales de acumulación que crucen las
  amarillas de ese jugador en el acta, sea la primera o la última, y también dos
  umbrales en la misma acta (RF-001, RF-002).
* La duración de esa sanción única es la de la expulsión
  (``direct_red_suspension_matches``), aplicada **una vez**: la acumulación no
  la alarga (RF-003).
* El tipo de roja sale de ``metadata.red_card_type`` tal como queda registrado;
  ausente equivale a directa y nunca se infiere del número de amarillas
  (RF-010). La roja directa **no** absorbe: mantiene las dos sanciones (RF-009).
* El contador de amarillas no se reinicia con la roja (RF-004) y la lista de
  salida es determinista en el orden del acta (RNF-003).

Sin base, sin reloj y sin almacenamiento: solo mappings, como en
``test_double_yellow.py``.

**Qué añade T2** (RF-004, RF-005, RF-012): el orden del historial es total y
estable (``discipline_history_order_key`` / ``order_discipline_history``, plan
§4.5, D-8) —sin fecha primero, después el partido, y dentro del partido minuto,
minuto añadido e identificador del evento—, una permutación del historial no
cambia la derivación y ``drop_recorded_red_sanctions`` quita la sanción de un
evento de roja ya registrado con **cualquier** motivo (plan §4.2, R-3) sin tocar
las demás sanciones del acta.
"""

from __future__ import annotations

from datetime import datetime, timezone
from itertools import permutations
from uuid import UUID

from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.rules_engine.engine import (
    discipline_history_order_key,
    drop_recorded_red_sanctions,
    evaluate_suspensions,
    order_discipline_history,
)

TEAM = UUID(int=7001)


# ---------------------------------------------------------------------------
# Constructores: acta, historial y configuración de disciplina
# ---------------------------------------------------------------------------


def _event_id(number: int) -> UUID:
    """Identificador estable del evento ``number`` (acta o historial)."""

    return UUID(int=9000 + number)


def config(*, limit: int = 3, yellow_matches: int = 1, red_matches: int = 1) -> dict:
    """Configuración de disciplina de la versión, con las claves existentes."""

    return {
        **DEFAULT_RULES_CONFIG,
        "discipline": {
            **DEFAULT_RULES_CONFIG["discipline"],
            "yellow_card_limit": limit,
            "yellow_card_suspension_matches": yellow_matches,
            "direct_red_suspension_matches": red_matches,
        },
    }


def yellow(
    player_id: UUID, number: int, *, minute: int = 20, added_minute: int = 0
) -> dict:
    """Una amarilla, en la forma de ``mapping`` que admite la función."""

    return {
        "id": _event_id(number),
        "event_type": "yellow_card",
        "team_id": TEAM,
        "player_id": player_id,
        "minute": minute,
        "added_minute": added_minute,
    }


def red(
    player_id: UUID,
    number: int,
    *,
    minute: int = 40,
    added_minute: int = 0,
    red_card_type: str | None = "double_yellow_red",
) -> dict:
    """Una roja; por defecto, marcada como doble amarilla.

    ``red_card_type=None`` deja el evento sin ``metadata``, que es la forma de
    una roja directa por defecto del catálogo (RF-010).
    """

    event = {
        "id": _event_id(number),
        "event_type": "red_card",
        "team_id": TEAM,
        "player_id": player_id,
        "minute": minute,
        "added_minute": added_minute,
    }
    if red_card_type is not None:
        event["metadata"] = {"red_card_type": red_card_type}
    return event


def in_history(
    event: dict, *, match_number: int = 1, match_date=None
) -> dict:
    """Un evento del historial: cada tarjeta identifica el partido al que pertenece."""

    return {
        **event,
        "match_id": UUID(int=8000 + match_number),
        "match_date": match_date,
    }


def summary(suspensions: list[dict]) -> list[tuple]:
    """Lo observable de una sanción: jugador, evento de origen, motivo y duración."""

    return [
        (
            item["player_id"],
            item["source_event_id"],
            item["reason"],
            item["matches_suspended"],
        )
        for item in suspensions
    ]


def sanction(
    player_id: UUID, number: int, reason: str, *, matches: int = 2
) -> dict:
    """Una sanción derivada, en la forma que devuelve ``evaluate_suspensions``."""

    return {
        "player_id": player_id,
        "source_event_id": _event_id(number),
        "matches_suspended": matches,
        "scope": "organization",
        "reason": reason,
    }


def game_date(day: int, month: int = 1) -> datetime:
    """Fecha de juego resuelta por la consulta (TIMESTAMPTZ, sin reloj aquí)."""

    return datetime(2026, month, day, 18, 0, tzinfo=timezone.utc)



# ---------------------------------------------------------------------------
# Una jugada, una sanción (RF-001, RF-002, RF-003)
# ---------------------------------------------------------------------------


def test_a_threshold_reached_by_the_expulsion_yellows_yields_one_sanction():
    player = UUID(int=1)
    act = [
        yellow(player, 1, minute=20),
        yellow(player, 2, minute=30),
        red(player, 3, minute=40),
    ]
    history = [in_history(yellow(player, 4, minute=10))]

    suspensions = evaluate_suspensions(
        config(limit=3, yellow_matches=4, red_matches=2), act, history
    )

    # Historial 1 + amarillas del acta 2 y 3: el umbral se cruza con la segunda
    # amarilla del acta y la expulsión por doble amarilla lo absorbe (RF-002).
    # Queda una sola sanción, con la duración de expulsión (RF-001, RF-003).
    assert summary(suspensions) == [(player, _event_id(3), "double_yellow_red", 2)]


def test_a_threshold_reached_by_the_first_act_yellow_is_absorbed_too():
    player = UUID(int=1)
    act = [
        yellow(player, 1, minute=20),
        yellow(player, 2, minute=30),
        red(player, 3, minute=40),
    ]
    history = [in_history(yellow(player, 4, minute=10))]

    suspensions = evaluate_suspensions(
        config(limit=2, yellow_matches=4, red_matches=2), act, history
    )

    # El umbral (2) se cruza con la PRIMERA amarilla del acta, no con la que
    # provoca la expulsión: se absorbe igual (RF-002).
    assert summary(suspensions) == [(player, _event_id(3), "double_yellow_red", 2)]


def test_two_thresholds_in_the_same_act_are_absorbed_together():
    player = UUID(int=1)
    act = [
        yellow(player, 1, minute=20),
        yellow(player, 2, minute=30),
        red(player, 3, minute=40),
    ]

    suspensions = evaluate_suspensions(
        config(limit=1, yellow_matches=4, red_matches=2), act, []
    )

    # Con límite 1 cada amarilla cruza un umbral (1 y 2): los dos caen con la
    # misma jugada y solo queda la sanción de la expulsión (RF-002).
    assert summary(suspensions) == [(player, _event_id(3), "double_yellow_red", 2)]


def test_absorption_does_not_reach_another_player():
    expelled = UUID(int=1)
    other = UUID(int=2)
    act = [
        yellow(expelled, 1, minute=10),
        yellow(other, 2, minute=20),
        yellow(expelled, 3, minute=30),
        yellow(other, 4, minute=40),
        red(expelled, 5, minute=50),
    ]

    suspensions = evaluate_suspensions(
        config(limit=2, yellow_matches=4, red_matches=2), act, []
    )

    # La acumulación del otro jugador sigue su curso (RF-002).
    assert summary(suspensions) == [
        (other, _event_id(4), "yellow_card_accumulation", 4),
        (expelled, _event_id(5), "double_yellow_red", 2),
    ]


def test_a_threshold_already_reached_in_the_history_is_not_re_emitted():
    player = UUID(int=1)
    history = [
        in_history(yellow(player, 1, minute=10), match_number=1),
        in_history(yellow(player, 2, minute=20), match_number=1),
    ]
    act = [
        yellow(player, 3, minute=10),
        yellow(player, 4, minute=20),
        red(player, 5, minute=30),
    ]

    suspensions = evaluate_suspensions(
        config(limit=2, yellow_matches=4, red_matches=2), act, history
    )

    # El historial ya sancionó su umbral en su propia acta y no se reemite; el
    # umbral que cruza el acta (4) se absorbe por la expulsión (RF-002, RF-005).
    assert summary(suspensions) == [(player, _event_id(5), "double_yellow_red", 2)]


# ---------------------------------------------------------------------------
# Solo el acta origina (RF-005)
# ---------------------------------------------------------------------------


def test_a_historical_red_originates_nothing():
    player = UUID(int=1)
    history = [in_history(red(player, 1, red_card_type="double_yellow_red"))]

    assert evaluate_suspensions(config(), [], history) == []


def test_historical_yellows_only_count_and_never_originate():
    player = UUID(int=1)
    history = [
        in_history(yellow(player, number, minute=10 * number), match_number=number)
        for number in (1, 2, 3)
    ]

    # Con límite 1 cada amarilla histórica habría cruzado un umbral; sin acta
    # que se cierre no se deriva ninguna sanción (RF-005).
    assert evaluate_suspensions(config(limit=1), [], history) == []


# ---------------------------------------------------------------------------
# El tipo de roja registrado manda (RF-009, RF-010)
# ---------------------------------------------------------------------------


def test_a_direct_red_keeps_both_sanctions_with_their_own_durations():
    player = UUID(int=1)
    act = [
        yellow(player, 1, minute=20),
        yellow(player, 2, minute=30),
        red(player, 3, minute=40, red_card_type="direct_red"),
    ]

    suspensions = evaluate_suspensions(
        config(limit=2, yellow_matches=4, red_matches=2), act, []
    )

    # Dos hechos distintos: el umbral se cruza con una amarilla y la expulsión
    # es otra tarjeta; cada sanción con su duración (RF-009).
    assert summary(suspensions) == [
        (player, _event_id(2), "yellow_card_accumulation", 4),
        (player, _event_id(3), "direct_red_card", 2),
    ]


def test_the_red_reason_comes_from_the_registered_type_not_the_yellow_count():
    player = UUID(int=1)
    two_yellows = [yellow(player, 1, minute=20), yellow(player, 2, minute=30)]
    # Límite alto: no se cruza ningún umbral y solo queda la roja.
    high_limit = config(limit=30)

    # Sin `metadata` la roja es directa aunque el acta traiga dos amarillas.
    absent = [*two_yellows, red(player, 3, minute=40, red_card_type=None)]
    assert summary(evaluate_suspensions(high_limit, absent, [])) == [
        (player, _event_id(3), "direct_red_card", 1)
    ]

    # Marcada como doble amarilla sin ninguna amarilla en el acta: su tipo manda.
    marked = [red(player, 4, minute=40)]
    assert summary(evaluate_suspensions(high_limit, marked, [])) == [
        (player, _event_id(4), "double_yellow_red", 1)
    ]

    # Y una directa explícita no se convierte en doble amarilla por las amarillas.
    explicit = [*two_yellows, red(player, 5, minute=40, red_card_type="direct_red")]
    assert summary(evaluate_suspensions(high_limit, explicit, [])) == [
        (player, _event_id(5), "direct_red_card", 1)
    ]


def test_the_yellow_counter_is_not_reset_by_the_red():
    player = UUID(int=1)
    # La 017 rechaza en un acta real una amarilla posterior a la roja del mismo
    # jugador (paso 8), pero el contador de la función no depende de la roja:
    # la amarilla posterior sigue contando desde el saldo anterior (RF-004).
    act = [
        yellow(player, 1, minute=20),
        red(player, 2, minute=30, red_card_type="direct_red"),
        yellow(player, 3, minute=50),
    ]

    suspensions = evaluate_suspensions(
        config(limit=2, yellow_matches=4, red_matches=2), act, []
    )

    assert summary(suspensions) == [
        (player, _event_id(2), "direct_red_card", 2),
        (player, _event_id(3), "yellow_card_accumulation", 4),
    ]


# ---------------------------------------------------------------------------
# Determinismo (RNF-003)
# ---------------------------------------------------------------------------


def test_the_same_act_gives_the_same_list_and_order():
    first_player = UUID(int=1)
    second_player = UUID(int=2)
    act = [
        yellow(first_player, 1, minute=10),
        yellow(second_player, 2, minute=20),
        yellow(first_player, 3, minute=30),
        red(second_player, 4, minute=40, red_card_type="direct_red"),
        yellow(first_player, 5, minute=50),
        red(first_player, 6, minute=60),
    ]
    rules = config(limit=2, yellow_matches=4, red_matches=2)

    once = evaluate_suspensions(rules, act, [])
    twice = evaluate_suspensions(rules, act, [])

    assert once == twice
    # Orden del acta: la roja directa del segundo jugador (evento 4) antes que
    # la expulsión por doble amarilla del primero (evento 6).
    assert summary(once) == [
        (second_player, _event_id(4), "direct_red_card", 2),
        (first_player, _event_id(6), "double_yellow_red", 2),
    ]


# ---------------------------------------------------------------------------
# Orden total y estable del historial (RF-004, plan §4.5, D-8)
# ---------------------------------------------------------------------------


def test_history_order_puts_undated_events_before_dated_ones():
    player = UUID(int=1)
    dated = in_history(
        yellow(player, 1, minute=1), match_number=1, match_date=game_date(1)
    )
    undated = in_history(yellow(player, 2, minute=90), match_number=2)

    ordered = order_discipline_history([dated, undated])

    # Un evento sin fecha va antes que cualquiera con fecha, aunque su minuto
    # sea posterior (RF-004: un partido sin fecha se ordena primero).
    assert [event["id"] for event in ordered] == [_event_id(2), _event_id(1)]


def test_history_order_breaks_ties_by_match_then_minute_added_and_event_id():
    player = UUID(int=1)
    date = game_date(1, month=5)
    events = [
        # Otro partido con el mismo día: el partido manda sobre el minuto.
        in_history(yellow(player, 1, minute=90), match_number=2, match_date=date),
        # Dentro del partido 1: minuto, después minuto añadido y, a igualdad de
        # ambos, el identificador del evento (4 antes que 5).
        in_history(yellow(player, 2, minute=89), match_number=1, match_date=date),
        in_history(
            yellow(player, 3, minute=90, added_minute=1),
            match_number=1,
            match_date=date,
        ),
        in_history(yellow(player, 5, minute=90), match_number=1, match_date=date),
        in_history(yellow(player, 4, minute=90), match_number=1, match_date=date),
    ]

    ordered = order_discipline_history(events)

    assert [event["id"] for event in ordered] == [
        _event_id(2),
        _event_id(4),
        _event_id(5),
        _event_id(3),
        _event_id(1),
    ]


def test_history_order_is_total_stable_and_idempotent():
    player = UUID(int=1)
    events = [
        in_history(yellow(player, 1, minute=30), match_number=2),
        in_history(
            yellow(player, 2, minute=30), match_number=1, match_date=game_date(2)
        ),
        in_history(yellow(player, 3, minute=30), match_number=1),
        in_history(
            yellow(player, 4, minute=30), match_number=1, match_date=game_date(1)
        ),
    ]

    once = order_discipline_history(events)
    twice = order_discipline_history(events)

    # Dos ejecuciones dan el mismo orden, reordenar lo ya ordenado no lo cambia
    # y `sorted` con la clave pública coincide con la función (RNF-003).
    assert once == twice
    assert order_discipline_history(once) == once
    assert sorted(events, key=discipline_history_order_key) == once
    # Sin fecha primero (por identificador de partido) y, con la misma fecha, el
    # día de juego decide.
    assert [event["id"] for event in once] == [
        _event_id(3),
        _event_id(1),
        _event_id(4),
        _event_id(2),
    ]


def test_a_permuted_history_does_not_change_the_derivation():
    player = UUID(int=1)
    history = [
        in_history(
            yellow(player, number, minute=10 * number),
            match_number=number,
            match_date=game_date(number),
        )
        for number in (1, 2, 3)
    ]
    act = [
        yellow(player, 4, minute=20),
        red(player, 5, minute=30, red_card_type="direct_red"),
    ]
    rules = config(limit=2, yellow_matches=4, red_matches=2)

    # Historial 3 + amarilla del acta = umbral 4 (límite 2): la acumulación se
    # origina en el acta y la roja directa no la absorbe. Contar es conmutativo,
    # así que cualquier orden de lectura del historial da el mismo resultado
    # (RF-004, RNF-003).
    assert summary(evaluate_suspensions(rules, act, history)) == [
        (player, _event_id(4), "yellow_card_accumulation", 4),
        (player, _event_id(5), "direct_red_card", 2),
    ]

    for permutation in permutations(history):
        suspensions = evaluate_suspensions(rules, act, list(permutation))
        assert summary(suspensions) == [
            (player, _event_id(4), "yellow_card_accumulation", 4),
            (player, _event_id(5), "direct_red_card", 2),
        ]


# ---------------------------------------------------------------------------
# Unicidad por evento de roja: cualquier motivo (RF-005, RF-012, plan §4.2)
# ---------------------------------------------------------------------------


def test_a_recorded_red_sanction_is_dropped_whatever_its_reason():
    player = UUID(int=1)
    direct = sanction(player, 1, "direct_red_card")
    legacy = sanction(player, 2, "direct_red_card", matches=3)
    double = sanction(player, 3, "double_yellow_red")

    # Sin rojas registradas la lista se conserva tal cual.
    assert drop_recorded_red_sanctions([direct], set()) == [direct]

    # Un evento de roja ya sancionado con el motivo corregido.
    assert drop_recorded_red_sanctions([direct, double], {_event_id(3)}) == [direct]

    # Y una roja guardada con el motivo heredado (`direct_red_card`) se quita
    # igual; además, los identificadores pueden llegar como texto.
    remaining = drop_recorded_red_sanctions(
        [direct, legacy, double], {str(_event_id(1)), _event_id(2)}
    )
    assert summary(remaining) == [(player, _event_id(3), "double_yellow_red", 2)]


def test_a_recorded_red_does_not_drop_another_players_accumulation():
    expelled = UUID(int=1)
    other = UUID(int=2)
    suspensions = [
        sanction(expelled, 1, "direct_red_card"),
        sanction(other, 2, "yellow_card_accumulation", matches=4),
        sanction(expelled, 3, "yellow_card_accumulation", matches=4),
    ]

    remaining = drop_recorded_red_sanctions(suspensions, {_event_id(1)})

    # Solo cae la sanción del evento de roja registrado: la acumulación del otro
    # jugador y la del propio jugador por otra jugada siguen (RF-005).
    assert summary(remaining) == [
        (other, _event_id(2), "yellow_card_accumulation", 4),
        (expelled, _event_id(3), "yellow_card_accumulation", 4),
    ]
