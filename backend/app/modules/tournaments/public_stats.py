"""Funciones puras de estadísticas deportivas públicas y porterías imbatidas (spec 022).

Toda función de este módulo es **pura**: no lee la base de datos ni el reloj.
Recibe listas ya cargadas (partidos, eventos, alineaciones publicadas, segmentos,
plantillas) y devuelve valores deterministas. El aislamiento por organización y
la firma de fotos se resuelven en la capa de endpoints, nunca aquí.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Iterable, Mapping, Sequence
from uuid import UUID


def _v(row: Any, key: str, default: Any = None) -> Any:
    """Lee un campo de una fila sea ``Mapping`` u objeto con atributos."""

    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _has(row: Any, key: str) -> bool:
    if isinstance(row, Mapping):
        return key in row
    return hasattr(row, key)


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y", "si", "sí"}
    return bool(value)


def _match_id(match: Any) -> Any:
    return _v(match, "id")


def _event_match_id(event: Any) -> Any:
    return _v(event, "match_id")


def _confirmed(match: Any) -> bool:
    status = _v(match, "status")
    if status not in ("finished", "administrative_resolution"):
        return False
    if _has(match, "result_confirmed"):
        return _truthy(_v(match, "result_confirmed"))
    # Sin la clave, un partido finalizado se considera confirmado (compatibilidad).
    return True


def _final_score(match: Any, side: str) -> int:
    """Marcador final (prórroga incluida, penales excluidos) de un lado."""

    if side == "home":
        for key in ("home_score", "home_score_regular"):
            value = _v(match, key)
            if value is not None:
                return int(value)
    else:
        for key in ("away_score", "away_score_regular"):
            value = _v(match, key)
            if value is not None:
                return int(value)
    return 0


def _resolution(match: Any) -> str | None:
    return _v(match, "resolution_type")


def _effective_duration(match: Any, segments: Iterable[Any]) -> int:
    """Duración efectiva del partido: último ``minute_end`` o máximo de la fase."""

    match_id = _match_id(match)
    segs = [
        s for s in (segments or [])
        if _v(s, "match_id") in (None, match_id)
    ]
    if segs:
        ordered = sorted(segs, key=lambda s: int(_v(s, "segment_number", 0) or 0))
        last = ordered[-1]
        minute_end = _v(last, "minute_end")
        if minute_end is not None:
            return int(minute_end)

    # Máximo efectivo de la fase (reglamentario o de prórroga).
    rules = _v(match, "rules_config")
    stage_defaults: Mapping[str, Any] = {}
    if isinstance(rules, Mapping):
        if isinstance(rules.get("stage_defaults"), Mapping):
            stage_defaults = rules["stage_defaults"]
        else:
            stage_defaults = rules
    regular = _v(match, "regular_time_minutes")
    if regular is None:
        regular = _v(match, "max_minute_regular")
    if regular is None:
        regular = stage_defaults.get("regular_time_minutes", 90)
    regular = int(regular or 90)

    resolution = _resolution(match)
    extra_enabled = stage_defaults.get("extra_time_enabled", True)
    if resolution in ("extra_time", "penalties") and extra_enabled:
        extra = _v(match, "extra_time_minutes")
        if extra is None:
            extra = _v(match, "max_minute_extra")
        if extra is None:
            extra = stage_defaults.get("extra_time_minutes", 120)
        return int(extra or regular)
    return regular


def _player_id(row: Any) -> Any:
    return _v(row, "player_id", _v(row, "id"))


def _match_for_event(event: Any, matches: Sequence[Any]) -> Any:
    mid = _event_match_id(event)
    for m in matches:
        if _match_id(m) == mid:
            return m
    if len(matches) == 1:
        return matches[0]
    return None


def _events_for_match(events: Iterable[Any], match: Any) -> list[Any]:
    mid = _match_id(match)
    result = []
    for e in events or []:
        emid = _event_match_id(e)
        if emid is None or emid == mid:
            result.append(e)
    return result


def _segments_for_match(segments: Iterable[Any], match: Any) -> list[Any]:
    mid = _match_id(match)
    result = []
    for s in segments or []:
        smid = _v(s, "match_id")
        if smid is None or smid == mid:
            result.append(s)
    return result


def _formation_players(formation: Any) -> list[Any]:
    if formation is None:
        return []
    if isinstance(formation, (list, tuple)):
        # Puede ser lista de formaciones o lista de jugadores.
        if formation and isinstance(formation[0], (list, tuple, Mapping)):
            # Si los elementos tienen position_slot/player_id, son jugadores.
            first = formation[0]
            if _has(first, "position_slot") or _has(first, "position") or _has(first, "player_id"):
                return list(formation)
        return []
    for key in ("players", "snapshots", "entries", "lineup", "members", "starters"):
        value = _v(formation, key)
        if isinstance(value, (list, tuple)):
            return list(value)
    positions = _v(formation, "positions")
    if isinstance(positions, Mapping):
        out = []
        for pos, pid in positions.items():
            out.append({"position_slot": pos, "player_id": pid, "is_starter": True})
        return out
    return []


def _is_formation_published(formation: Any) -> bool:
    if _has(formation, "is_public"):
        return _truthy(_v(formation, "is_public"))
    return True


def _position_slot(player: Any) -> str | None:
    for key in ("position_slot", "position", "slot"):
        value = _v(player, key)
        if value is not None:
            return str(value)
    return None


def _is_starter(player: Any) -> bool:
    if _has(player, "is_starter"):
        return _truthy(_v(player, "is_starter"))
    role = _v(player, "role")
    if role is not None:
        return str(role).lower() in ("starter", "titular")
    return False


#: Umbral fijo de la estadística (RF-027, RNF-009): no es configurable, no se
#: evalúa en el motor de reglas y no cambia ``engine_version`` (2026.1).
MIN_GOALKEEPER_MINUTES = 60

_FORMATION_PLAYER_KEYS = ("players", "snapshots", "entries", "lineup", "members", "starters")
_FORMATION_FLAG_KEYS = ("is_public", "segment_id", "segment_number", "formation_code", "team_id")
_SEGMENT_KEYS = ("minute_start", "minute_end", "status")


def _is_goalkeeper(player: Any) -> bool:
    """¿La fila ocupa la posición ``GK`` de una formación táctica?"""

    return str(_position_slot(player) or "").upper() == "GK"


def _is_formation_object(row: Any) -> bool:
    """Distingue una formación agrupada de una fila plana jugador-partido.

    La proyección interna ``public.v_public_match_formations`` (migración 031)
    devuelve **filas planas** que llevan ``player_id`` y también ``match_id``,
    ``team_id``, ``segment_id`` e ``is_public``; una formación agrupada lleva la
    lista de jugadores (``players``/``positions``/…) y no un ``player_id``.
    """

    if any(_has(row, key) for key in _FORMATION_PLAYER_KEYS):
        return True
    if _has(row, "player_id"):
        return False
    if any(_has(row, key) for key in _SEGMENT_KEYS):
        # Una fila de segmento no es una formación.
        return False
    return any(_has(row, key) for key in _FORMATION_FLAG_KEYS)


def _as_formation(row: Any) -> Any:
    """Envuelve una lista de jugadores o una fila suelta como formación."""

    if row is None:
        return None
    if isinstance(row, (list, tuple)):
        return {"players": list(row)}
    if isinstance(row, Mapping) and not _is_formation_object(row):
        return {"players": [row]}
    return row


def _group_flat_rows(rows: Sequence[Any]) -> list[dict]:
    """Agrupa filas jugador-partido en formaciones por partido, segmento y equipo.

    Es el formato de la proyección de la 031: una fila por jugador con
    ``match_id``, ``segment_id``, ``segment_number``, ``team_id``, ``player_id``,
    ``position_slot``, ``is_starter`` e ``is_public``. La formación resulta
    publicada solo si **ninguna** de sus filas dice lo contrario.
    """

    grouped: "OrderedDict[tuple, dict]" = OrderedDict()
    for row in rows:
        key = (
            _v(row, "match_id"),
            _v(row, "segment_id"),
            _v(row, "team_id"),
            _v(row, "segment_number"),
        )
        formation = grouped.get(key)
        if formation is None:
            formation = {
                "match_id": _v(row, "match_id"),
                "segment_id": _v(row, "segment_id"),
                "segment_number": _v(row, "segment_number"),
                "team_id": _v(row, "team_id"),
                "players": [],
                "is_public": True,
            }
            grouped[key] = formation
        formation["players"].append(row)
        if _has(row, "is_public") and not _truthy(_v(row, "is_public")):
            formation["is_public"] = False
    return list(grouped.values())


def _normalize_formations(formations: Any) -> list[Any]:
    """Normaliza la entrada a una lista de formaciones con ``players``.

    Acepta una formación suelta (``{"players": [...]}``), una lista de jugadores
    (una sola formación), una lista de formaciones y una lista de **filas
    planas** como las de ``public.v_public_match_formations`` (031), que se
    agrupan por partido, segmento y equipo. No lee la base de datos ni el reloj.
    """

    if formations is None:
        return []
    if isinstance(formations, Mapping):
        return [_as_formation(formations)]
    if isinstance(formations, (list, tuple)):
        if not formations:
            return []
        first = formations[0]
        if isinstance(first, (list, tuple)):
            # Lista de formaciones, cada una como lista de jugadores.
            return [{"players": list(item)} for item in formations]
        if isinstance(first, Mapping) and not _is_formation_object(first):
            # Filas planas de la proyección (031).
            return _group_flat_rows(formations)
        normalized = [_as_formation(item) for item in formations]
        return [formation for formation in normalized if formation is not None]
    if not isinstance(formations, (str, bytes)) and hasattr(formations, "__iter__"):
        # Cualquier iterable de formaciones (generador, ``tuple``, etc.).
        return _normalize_formations(list(formations))
    return [_as_formation(formations)]


def _segment_sort_key(formation: Any, index: int) -> int:
    number = _v(formation, "segment_number")
    if number is None:
        number = index
    try:
        return int(number)
    except (TypeError, ValueError):
        return index


def published_formations(formations: Any, match_id: Any = None) -> list[Any]:
    """Formaciones **publicadas**, ordenadas por ``(segment_number, id)``.

    El filtro de publicación se comprueba **aquí**, en la propia regla: no se
    delega en el ``WHERE`` de la vista, de modo que una proyección mal filtrada
    no puede atribuir una portería imbatida a partir de una formación no
    publicada (RF-026, caso 13). ``match_id`` acota además al partido en curso;
    ``id`` se representa con el orden de entrada de cada formación, que es
    estable.
    """

    ordered: list[tuple[int, Any]] = []
    for index, formation in enumerate(_normalize_formations(formations)):
        if formation is None:
            continue
        if match_id is not None and _v(formation, "match_id") not in (None, match_id):
            continue
        if not _is_formation_published(formation):
            continue
        ordered.append((index, formation))
    ordered.sort(key=lambda pair: (_segment_sort_key(pair[1], pair[0]), pair[0]))
    return [formation for _, formation in ordered]


def clean_sheet_team(match: Any, *args: Any, events: Any = None, team_id: Any = None, **kwargs: Any) -> bool:
    """Portería imbatida del equipo.

    Firma tolerante: ``clean_sheet_team(match, events)`` o
    ``clean_sheet_team(match, events, team_id)`` o con ``team_id=``.
    """

    parsed_events = events
    parsed_team = team_id
    for arg in args:
        if isinstance(arg, (list, tuple)):
            parsed_events = arg
        elif isinstance(arg, Mapping) and "event_type" in arg:
            if parsed_events is None:
                parsed_events = [arg]
            else:
                parsed_events = list(parsed_events) + [arg]
        else:
            if parsed_team is None:
                parsed_team = arg
    events = parsed_events if parsed_events is not None else []

    if parsed_team is None:
        parsed_team = _v(match, "team_id")
    if parsed_team is None:
        parsed_team = _v(match, "home_team_id")

    if not _confirmed(match):
        return False
    resolution = _resolution(match)
    if resolution in ("walkover", "administrative"):
        return False

    home_id = _v(match, "home_team_id")
    away_id = _v(match, "away_team_id")

    if parsed_team == home_id:
        received = _final_score(match, "away")
    elif parsed_team == away_id:
        received = _final_score(match, "home")
    else:
        received = _v(match, "goals_against", _v(match, "received"))
        if received is None:
            received = 0
            for e in _events_for_match(events, match):
                if _truthy(_v(e, "is_voided")):
                    continue
                etype = _v(e, "event_type")
                owner = _v(e, "team_id")
                if etype in ("goal", "penalty_goal"):
                    if owner != parsed_team:
                        received += 1
                elif etype == "own_goal":
                    if owner == parsed_team:
                        received += 1

    try:
        received = int(received)
    except (TypeError, ValueError):
        received = 0
    return received == 0


def _player_minutes(match: Any, player_id: Any, events: Iterable[Any], segments: Iterable[Any], started: bool) -> int:
    """Minutos jugados por un jugador (portero) en el partido."""

    duration = _effective_duration(match, segments)
    mevents = _events_for_match(events, match)
    # Orden canónico: (minute, added_minute, index).
    ordered = sorted(
        list(mevents),
        key=lambda e: (int(_v(e, "minute", 0) or 0), int(_v(e, "added_minute", 0) or 0), 0),
    )
    # Para estabilidad, conservar índice de entrada.
    indexed = list(enumerate(mevents))
    ordered = sorted(
        indexed,
        key=lambda pair: (
            int(_v(pair[1], "minute", 0) or 0),
            int(_v(pair[1], "added_minute", 0) or 0),
            pair[0],
        ),
    )
    ordered_events = [e for _, e in ordered]

    if started:
        exit_minute = None
        for e in ordered_events:
            etype = _v(e, "event_type")
            # Sustitución en la que sale el jugador.
            if etype == "substitution":
                out_id = _v(e, "player_out_id", _v(e, "player_id"))
                if out_id == player_id:
                    exit_minute = int(_v(e, "minute", 0) or 0) + int(_v(e, "added_minute", 0) or 0)
                    break
            if etype == "red_card" and _v(e, "player_id") == player_id:
                exit_minute = int(_v(e, "minute", 0) or 0) + int(_v(e, "added_minute", 0) or 0)
                break
        if exit_minute is None:
            return int(duration)
        return int(min(exit_minute, duration))
    # Sustituto.
    entry_minute = None
    for e in ordered_events:
        if _v(e, "event_type") == "substitution" and _v(e, "player_in_id") == player_id:
            entry_minute = int(_v(e, "minute", 0) or 0) + int(_v(e, "added_minute", 0) or 0)
            break
    if entry_minute is None:
        return 0
    exit_minute = None
    for e in ordered_events:
        emin = int(_v(e, "minute", 0) or 0) + int(_v(e, "added_minute", 0) or 0)
        if emin < entry_minute:
            continue
        if _v(e, "event_type") == "substitution":
            out_id = _v(e, "player_out_id", _v(e, "player_id"))
            if out_id == player_id:
                exit_minute = emin
                break
        if _v(e, "event_type") == "red_card" and _v(e, "player_id") == player_id:
            exit_minute = emin
            break
    end = exit_minute if exit_minute is not None else duration
    minutes = int(end) - int(entry_minute)
    return max(0, int(minutes))


def goalkeeper_minutes(match: Any, *args: Any, events: Any = None, segments: Any = None, **kwargs: Any) -> int:
    """Minutos jugados por el portero identificado por ``formation``."""

    formation = None
    parsed_events = events
    parsed_segments = segments
    for arg in args:
        if isinstance(arg, (list, tuple)):
            if not arg:
                if parsed_events is None:
                    parsed_events = arg
                elif parsed_segments is None:
                    parsed_segments = arg
                else:
                    parsed_events = arg
                continue
            first = arg[0]
            if isinstance(first, Mapping):
                if "event_type" in first:
                    parsed_events = arg
                    continue
                if "segment_number" in first or "minute_end" in first or "minute_start" in first:
                    if parsed_segments is None:
                        parsed_segments = arg
                    else:
                        parsed_events = arg
                    continue
                if "position_slot" in first or "position" in first or "player_id" in first:
                    if formation is None:
                        formation = {"players": list(arg)}
                    else:
                        # tratar como jugadores de una formación adicional (no aplica aquí)
                        pass
                    continue
            # Desconocido: asignar al primero libre.
            if parsed_events is None:
                parsed_events = arg
            elif parsed_segments is None:
                parsed_segments = arg
            else:
                parsed_events = arg
        else:
            if formation is None:
                formation = arg
    if parsed_events is None:
        parsed_events = []
    if parsed_segments is None:
        parsed_segments = []

    # Identificar al portero (GK) en la formación.
    players = _formation_players(formation)
    gk_player = None
    started = True
    for p in players:
        if str(_position_slot(p) or "").upper() == "GK":
            if _is_starter(p) or not players:
                gk_player = p
                started = True
                break
    if gk_player is None:
        for p in players:
            if str(_position_slot(p) or "").upper() == "GK":
                gk_player = p
                started = False
                break
    # Si la formación es en realidad un jugador.
    if gk_player is None and _has(formation, "player_id") and str(_position_slot(formation) or "").upper() == "GK":
        gk_player = formation
        started = _is_starter(formation)

    if gk_player is None:
        return 0
    pid = _player_id(gk_player)
    started_flag = _is_starter(gk_player) if _has(gk_player, "is_starter") or _has(gk_player, "role") else started
    return _player_minutes(match, pid, parsed_events, parsed_segments, started_flag)


def clean_sheet_goalkeepers(match: Any, formations: Any, events: Any = None, segments: Any = None) -> list[Any]:
    """Porteros con portería imbatida en un partido (0, 1 o 2 como máximo).

    Regla única (RF-015, RF-024, RF-026, RF-027, RF-030) sobre **todas** las
    formaciones publicadas del partido:

    * el filtro ``is_public`` se comprueba dentro de la propia regla
      (:func:`published_formations`), no se delega en la vista: sin formación
      publicada no hay portero (casos 12 y 13);
    * el equipo debe tener portería imbatida (:func:`clean_sheet_team`);
    * el portero **titular** es el ``GK`` de la formación publicada del primer
      segmento del equipo, y sus minutos llegan hasta la sustitución o la
      expulsión;
    * el portero **entrante** se reconoce cuando figura como ``GK`` en una
      formación publicada **posterior** —aunque allí sea titular— y una
      ``substitution`` acredita su entrada (``player_in_id``); sus minutos
      cuentan desde la sustitución;
    * un suplente que no figura como ``GK`` en ninguna formación publicada no
      es portero identificable: no se le atribuye nada y el equipo conserva su
      portería imbatida (caso 16c, RF-026);
    * se emite **como máximo una** atribución por portero y partido (RF-030).

    ``formations`` acepta las filas planas de ``public.v_public_match_formations``
    (migración 031), formaciones agrupadas o una sola formación. Es una función
    pura: no lee la base de datos ni el reloj.
    """

    events = list(events or [])
    segments = list(segments or [])

    published = published_formations(formations, match_id=_match_id(match))
    if not published:
        return []

    segs = _segments_for_match(segments, match)
    default_team = _v(match, "home_team_id")

    by_team: "OrderedDict[Any, list[Any]]" = OrderedDict()
    for formation in published:
        team = _v(formation, "team_id")
        if team is None:
            team = default_team
        by_team.setdefault(team, []).append(formation)

    keepers: list[Any] = []
    attributed: set[Any] = set()
    for team, team_formations in by_team.items():
        if not clean_sheet_team(match, events, team_id=team):
            continue
        candidates: list[tuple[Any, bool]] = []
        first_keepers = [p for p in _formation_players(team_formations[0]) if _is_goalkeeper(p)]
        if first_keepers:
            starter = next((p for p in first_keepers if _is_starter(p)), first_keepers[0])
            candidates.append((starter, True))
        # Formaciones posteriores: el portero entrante figura como GK en ellas
        # (aunque allí sea titular). Sin sustitución que lo acredite sus minutos
        # son 0 y no alcanza el umbral.
        for formation in team_formations[1:]:
            for player in _formation_players(formation):
                if _is_goalkeeper(player):
                    candidates.append((player, False))
        for player, started in candidates:
            pid = _player_id(player)
            if pid is None or pid in attributed:
                continue
            minutes = _player_minutes(match, pid, events, segs, started)
            if minutes >= MIN_GOALKEEPER_MINUTES:
                keepers.append(pid)
                attributed.add(pid)
    return keepers


def clean_sheet_goalkeeper(
    match: Any,
    *args: Any,
    formation: Any = None,
    events: Any = None,
    segments: Any = None,
    formations: Any = None,
    **kwargs: Any,
) -> Any:
    """Portero(s) con portería imbatida (firma tolerante).

    Mantiene la firma histórica —formación suelta, lista de formaciones,
    ``formations=``— y delega **siempre** en la regla única
    :func:`clean_sheet_goalkeepers`. Con **una sola** formación devuelve el
    ``player_id`` que cumple (o ``None``), como antes; con varias devuelve la
    lista de ``player_id`` que cumplen (vacía si ninguna).
    """

    parsed_events = events
    parsed_segments = segments
    formation_inputs: list[Any] = []
    if formations is not None:
        formation_inputs.extend(_normalize_formations(formations))
    if formation is not None:
        formation_inputs.extend(_normalize_formations(formation))

    for arg in args:
        if arg is None:
            continue
        if isinstance(arg, (list, tuple)):
            if not arg:
                if parsed_events is None:
                    parsed_events = arg
                elif parsed_segments is None:
                    parsed_segments = arg
                continue
            first = arg[0]
            if isinstance(first, Mapping):
                if _has(first, "event_type"):
                    parsed_events = arg
                    continue
                if _has(first, "minute_start") or _has(first, "minute_end"):
                    if parsed_segments is None:
                        parsed_segments = arg
                    else:
                        parsed_events = arg
                    continue
            formation_inputs.extend(_normalize_formations(list(arg)))
            continue
        if isinstance(arg, Mapping) and _has(arg, "event_type"):
            if parsed_events is None:
                parsed_events = [arg]
            else:
                parsed_events = list(parsed_events) + [arg]
            continue
        formation_inputs.extend(_normalize_formations(arg))

    if parsed_events is None:
        parsed_events = []
    if parsed_segments is None:
        parsed_segments = []

    if not formation_inputs:
        return None

    qualifying = clean_sheet_goalkeepers(match, formation_inputs, parsed_events, parsed_segments)
    if len(formation_inputs) == 1:
        return qualifying[0] if qualifying else None
    return qualifying


def _visible_criteria_key(visible_criteria: Any) -> Any:
    """Normaliza los criterios visibles a una función ``fila -> tupla``.

    ``visible_criteria`` puede ser una función que devuelve la tupla ya
    orientada para ordenar (goles descendentes → ``-goals``) o una secuencia de
    nombres de campo, que se leen de cada fila con :func:`_v`.
    """

    if callable(visible_criteria):
        return visible_criteria
    names = tuple(visible_criteria)

    def by_fields(row: Any) -> tuple:
        return tuple(_v(row, name) for name in names)

    return by_fields


def _stable_identity(row: Any, stable_id: Any) -> str:
    """Identificador estable como texto; solo ordena dentro del empate."""

    if stable_id is None:
        return ""
    value = _v(row, stable_id)
    return "" if value is None else str(value)


def _write_rank(row: Any, rank: int) -> None:
    if isinstance(row, dict):
        row["rank"] = rank
    else:
        setattr(row, "rank", rank)


def assign_ranks(rows: Any, visible_criteria: Any, stable_id: Any = None) -> list[Any]:
    """Ordena las filas y asigna ``rank`` compartido en los empates.

    RF-006, RF-022: el orden es ``(criterios visibles, identificador estable)``.
    El identificador **solo** decide el orden de presentación dentro del empate
    y **no** lo desempata a efectos de posición, así que dos filas empatadas en
    **todos** los criterios visibles comparten ``rank``. La numeración continúa
    después del grupo (1, 2, 2, 4), porque se calcula con el índice 1-based de la
    primera fila del grupo sobre el conjunto **completo** recibido: paginar
    después no reinicia nada (D9).

    ``visible_criteria`` es la tupla de criterios ya orientada para ordenar
    —por ejemplo ``(-goals, matches_played, last_name)`` de
    :func:`player_stats_rank_key`— o una secuencia de nombres de campo. Es una
    función pura: no lee la base de datos ni el reloj.
    """

    criteria = _visible_criteria_key(visible_criteria)
    ordered = sorted(
        rows,
        key=lambda row: (criteria(row), _stable_identity(row, stable_id)),
    )
    rank = 0
    previous: Any = None
    for index, row in enumerate(ordered, start=1):
        visible = criteria(row)
        if index == 1 or visible != previous:
            rank = index
            previous = visible
        _write_rank(row, rank)
    return ordered


def player_stats_rank_key(row: Any) -> tuple:
    """Criterios **visibles** de la tabla de jugadores (RF-022).

    Goles descendente, después menos partidos disputados y después apellido. El
    identificador estable no forma parte de estos criterios: solo ordena dentro
    del empate.
    """

    return (
        -int(_v(row, "goals", 0) or 0),
        int(_v(row, "matches_played", 0) or 0),
        str(_v(row, "last_name") or ""),
    )


def team_stats_rank_key(row: Any) -> tuple:
    """Criterios **visibles** de la tabla de equipos (RF-022).

    Goles a favor descendente, después menos goles en contra y después nombre.
    El identificador estable no forma parte de estos criterios.
    """

    return (
        -int(_v(row, "goals_for", 0) or 0),
        int(_v(row, "goals_against", 0) or 0),
        str(_v(row, "team_name") or ""),
    )


def compute_player_stats(
    matches: Any,
    events: Any,
    formations: Any = None,
    segments: Any = None,
    rosters: Any = None,
    **kwargs: Any,
) -> list[dict]:
    """Agrega estadísticas por jugador a partir de partidos confirmados.

    ``formations`` acepta las **filas planas** de la proyección interna
    ``public.v_public_match_formations`` (migración 031) —``match_id``,
    ``team_id``, ``segment_id``, ``segment_number``, ``player_id``,
    ``position_slot``, ``is_starter`` e ``is_public``— o formaciones ya
    agrupadas como ``{"players": [...]}``. Quien alimente esta función debe
    pasar **todas** las formaciones publicadas del partido y no solo la última
    por equipo (lo que permite reconocer al portero entrante, caso 16b); el
    filtro ``is_public`` se vuelve a comprobar aquí (RF-026).

    La portería imbatida de cada portero sale de la regla única
    :func:`clean_sheet_goalkeepers`, aplicada una vez por ``(partido, equipo)``:
    no se vuelve a filtrar por titularidad ni se duplica el cálculo.

    **Participación (RF-012, RF-022).** Un evento acredita un partido disputado a
    su jugador (``player_id``). En una ``substitution`` el catálogo de la spec 015
    fija ``player_id = player_out_id``, así que el jugador que **entra**
    (``player_in_id``) se acredita además con ese mismo partido: «una sustitución
    acredita a **ambos** jugadores implicados» (definición de «Partido disputado
    por un jugador»). Esa acreditación es **solo de participación**: no suma
    goles, tarjetas ni porterías imbatidas, y ``matches_played`` es un conjunto de
    partidos, así que varios eventos del mismo jugador en el mismo partido —o un
    mismo jugador en la plantilla y en un evento— cuentan **una sola vez**. Se
    mantienen las exclusiones ya vigentes: evento anulado (``is_voided``), partido
    sin resultado confirmado y jugador fuera de la plantilla cargada (huérfano).
    """

    if formations is None:
        formations = kwargs.pop("lineups", None)

    matches = list(matches or [])
    events = list(events or [])
    formations = _normalize_formations(formations)
    segments = list(segments or [])
    rosters = list(rosters or [])

    matches_by_id = {_match_id(m): m for m in matches}

    player_info: dict[Any, dict[str, Any]] = {}
    for r in rosters:
        pid = _player_id(r)
        if pid is None:
            continue
        info = player_info.setdefault(pid, {})
        for key in ("first_name", "last_name", "team_id", "team_name", "photo_url", "photo_consent"):
            value = _v(r, key)
            if value is not None and key not in info:
                info[key] = value

    stats: dict[Any, dict[str, Any]] = {}

    def ensure(pid: Any) -> dict[str, Any]:
        if pid not in stats:
            entry = {
                "player_id": pid,
                "first_name": "",
                "last_name": "",
                "goals": 0,
                "yellow_cards": 0,
                "red_cards": 0,
                "clean_sheets": 0,
                "matches_played": set(),
            }
            if pid in player_info:
                for key, value in player_info[pid].items():
                    if value is not None:
                        entry[key] = value
            stats[pid] = entry
        return stats[pid]

    def match_of(formation: Any) -> tuple[Any, Any]:
        mid = _v(formation, "match_id")
        m = matches_by_id.get(mid)
        if m is None and len(matches) == 1:
            m = matches[0]
            mid = _match_id(m)
        if m is None or not _confirmed(m):
            return None, None
        return mid, m

    # Eventos.
    for e in events:
        mid = _event_match_id(e)
        m = matches_by_id.get(mid)
        if m is None and len(matches) == 1:
            m = matches[0]
            mid = _match_id(m)
        if m is None or not _confirmed(m):
            continue
        if _truthy(_v(e, "is_voided")):
            continue
        etype = _v(e, "event_type")
        pid = _v(e, "player_id")
        # Acreditación del evento: el jugador del acta y, en una sustitución, el
        # que entra (``player_id`` es ``player_out_id`` por el catálogo de la 015).
        credited: list[tuple[Any, str | None]] = []
        if pid is not None:
            credited.append((pid, etype))
        if etype == "substitution":
            in_pid = _v(e, "player_in_id")
            if in_pid is not None and in_pid != pid:
                # Solo participación: no hereda goles, tarjetas ni porterías.
                credited.append((in_pid, None))
        for credited_pid, credit_type in credited:
            if credited_pid not in player_info:
                continue
            d = ensure(credited_pid)
            d["matches_played"].add(mid)
            if credit_type in ("goal", "penalty_goal"):
                d["goals"] += 1
            elif credit_type == "yellow_card":
                d["yellow_cards"] += 1
            elif credit_type == "red_card":
                d["red_cards"] += 1

    # Formaciones publicadas: presencia del jugador y agrupación por partido.
    by_match: "OrderedDict[Any, list[Any]]" = OrderedDict()
    for formation in formations:
        mid, m = match_of(formation)
        if m is None:
            continue
        if not _is_formation_published(formation):
            continue
        for player in _formation_players(formation):
            pid = _player_id(player)
            if pid is None:
                continue
            ensure(pid)["matches_played"].add(mid)
        by_match.setdefault(mid, []).append(formation)

    # Porterías imbatidas por jugador: una sola regla por (partido, equipo).
    counted: set[tuple[Any, Any]] = set()
    for mid, match_formations in by_match.items():
        m = matches_by_id.get(mid)
        if m is None:
            continue
        segs = _segments_for_match(segments, m)
        by_team: "OrderedDict[Any, list[Any]]" = OrderedDict()
        for formation in match_formations:
            team = _v(formation, "team_id")
            if team is None:
                team = _v(m, "home_team_id")
            by_team.setdefault(team, []).append(formation)
        for team_formations in by_team.values():
            for pid in clean_sheet_goalkeepers(m, team_formations, events, segs):
                if pid is None or (pid, mid) in counted:
                    continue
                ensure(pid)["clean_sheets"] += 1
                counted.add((pid, mid))

    # Finalizar matches_played como entero.
    for d in stats.values():
        d["matches_played"] = len(d["matches_played"])

    return list(stats.values())


def compute_team_stats(matches: Any, events: Any, fair_play: Any = None, *args: Any, **kwargs: Any) -> list[dict]:
    """Agrega estadísticas por equipo a partir de partidos confirmados."""

    matches = list(matches or [])
    events = list(events or [])

    # Mapa de fair play por equipo.
    fair_map: dict[Any, Any] = {}
    if isinstance(fair_play, Mapping):
        fair_map = dict(fair_play)
    elif isinstance(fair_play, (list, tuple)):
        for item in fair_play:
            if isinstance(item, Mapping):
                tid = _v(item, "team_id", _v(item, "id"))
                val = _v(item, "fair_play_points", _v(item, "points", _v(item, "fair_play")))
                if tid is not None:
                    fair_map[tid] = val
            else:
                tid = getattr(item, "team_id", None)
                if tid is not None:
                    fair_map[tid] = getattr(item, "fair_play_points", 0)

    teams: dict[Any, dict[str, Any]] = {}

    def ensure(team: Any) -> dict[str, Any]:
        if team not in teams:
            teams[team] = {
                "team_id": team,
                "goals_for": 0,
                "goals_against": 0,
                "clean_sheets": 0,
                "fair_play_points": fair_map.get(team, 0),
            }
        return teams[team]

    for m in matches:
        if not _confirmed(m):
            continue
        home = _v(m, "home_team_id")
        away = _v(m, "away_team_id")
        home_score = _final_score(m, "home")
        away_score = _final_score(m, "away")

        for team, received, scored in ((home, away_score, home_score), (away, home_score, away_score)):
            if team is None:
                continue
            d = ensure(team)
            d["goals_for"] += int(scored or 0)
            d["goals_against"] += int(received or 0)
            if clean_sheet_team(m, list(events), team_id=team):
                d["clean_sheets"] += 1

    for team, d in teams.items():
        if team in fair_map and d["fair_play_points"] == 0:
            d["fair_play_points"] = fair_map.get(team, 0)
        else:
            d["fair_play_points"] = fair_map.get(team, d["fair_play_points"])

    return list(teams.values())


# Alias histórico del plan.
minutes_played_by_goalkeeper = goalkeeper_minutes
