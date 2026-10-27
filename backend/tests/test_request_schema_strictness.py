"""Spec 019 — Endurecimiento de los esquemas de petición (T1..T5).

Barrido de comportamiento **puro** (sin base de datos, sin red, sin reloj; plan
§4 y §7): recorre ``app.main.api``, deriva las operaciones con cuerpo JSON y las
compara con el inventario literal de **33** operaciones (**29** modelos de
primer nivel + **5** anidados), excluyendo las **3** operaciones multipart.

T4 convierte el barrido en la garantía completa: ``STRICT_MODELS`` deja de ser
una lista escrita a mano y pasa a ser el **conjunto derivado** de los modelos
alcanzables desde el barrido, recursivamente (**34**), y ese mismo conjunto es
el que se prueba —biyección con el inventario literal en ambos sentidos,
bandera ``extra="forbid"`` y rechazo ``extra_forbidden`` con el valor
conservado solo dentro del error de Pydantic—. Tres salvaguardas fallan con
mensaje explícito: un modelo de **primer nivel** sin bandera, un modelo
**anidado** sin bandera y una **operación JSON sin modelo Pydantic**.

T5 fija la **precedencia por capas** (RF-009) y la **forma saneada del 422**
(RF-010) con un subconjunto HTTP representativo —reglas, creación de torneo,
alta en roster y evento de partido— usando ``httpx.ASGITransport`` sobre
``app.main.api`` y ``dependency_overrides`` (plan §6 D-4, §12). Cada caso
envía una clave no declarada, de modo que la respuesta revela qué capa responde
primero; el 422 siempre sale del saneado real de ``main.py``, nunca de un
manejador simulado.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any, Union, get_args, get_origin
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.params import File as FileField
from fastapi.params import Form as FormField
from fastapi.routing import APIRoute
from pydantic import BaseModel, ValidationError

from app.core.database import get_db
from app.core.platform import PlatformContext, get_platform_context
from app.core.security import get_current_user_id
from app.core.tenancy import AuthContext, get_auth_context
from app.main import api
from app.modules.identity.schemas import (
    GoogleStartRequest,
    LoginRequest,
    RegisterRequest,
)
from app.modules.invitations.schemas import (
    AcceptInvitationRequest,
    CreateInvitationRequest,
    UpdateMemberActiveRequest,
    UpdateMemberRoleRequest,
)
from app.modules.matches.schemas import (
    CloseMatchReportDTO,
    CreateMatchSegmentRequest,
    InterruptMatchSegmentRequest,
    MatchEventPayload,
    MatchLineupEntry,
    MatchTeamLineupConfig,
    OfficialAssignmentRequest,
    PublishMatchLineupRequest,
    SaveMatchLineupRequest,
)
from app.modules.organizations.schemas import OrganizationCreateRequest
from app.modules.platform.schemas import (
    CreateMembershipRequest,
    OutboxReprocessRequest,
    SetActiveRequest,
)
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.rules_engine.schemas import (
    CreateTournamentRequest,
    TournamentRulesConfig,
    UpdateRulesConfigRequest,
)
from app.modules.tournaments.schemas import (
    AssignStageTeamsRequest,
    BulkTournamentTeamItem,
    BulkTournamentTeamRequest,
    CreateDraftVersionRequest,
    CreateMatchRequest,
    CreateRosterPlayerRequest,
    CreateStageRequest,
    CreateTournamentTeamRequest,
    GenerateSingleEliminationRequest,
    UpdatePhotoConsentRequest,
    UpdateRosterStatusRequest,
)

# ---------------------------------------------------------------------------
# Inventario literal (plan §2.1 y §4): (método, ruta, modelo). Biyección con el
# árbol de rutas de la app: una operación nueva sin entrada aquí —o una entrada
# sin operación— rompe la prueba con detalle.
# ---------------------------------------------------------------------------

EXPECTED_OPERATIONS: list[tuple[str, str, str]] = [
    ("POST", "/api/v1/auth/register", "identity.schemas.RegisterRequest"),
    ("POST", "/api/v1/auth/login", "identity.schemas.LoginRequest"),
    ("POST", "/api/v1/auth/google/start", "identity.schemas.GoogleStartRequest"),
    (
        "POST",
        "/api/v1/organizations/invitations",
        "invitations.schemas.CreateInvitationRequest",
    ),
    (
        "POST",
        "/api/v1/invitations/{token}/accept",
        "invitations.schemas.AcceptInvitationRequest",
    ),
    (
        "PATCH",
        "/api/v1/organizations/members/{organization_user_id}/role",
        "invitations.schemas.UpdateMemberRoleRequest",
    ),
    (
        "PATCH",
        "/api/v1/organizations/members/{organization_user_id}/status",
        "invitations.schemas.UpdateMemberActiveRequest",
    ),
    ("POST", "/api/v1/organizations", "organizations.schemas.OrganizationCreateRequest"),
    (
        "POST",
        "/api/v1/platform/outbox/reprocess",
        "platform.schemas.OutboxReprocessRequest",
    ),
    (
        "POST",
        "/api/v1/platform/organizations/{organization_id}/members",
        "platform.schemas.CreateMembershipRequest",
    ),
    ("PATCH", "/api/v1/platform/users/{user_id}/status", "platform.schemas.SetActiveRequest"),
    (
        "PATCH",
        "/api/v1/platform/organizations/{organization_id}/status",
        "platform.schemas.SetActiveRequest",
    ),
    (
        "PATCH",
        "/api/v1/platform/organizations/{organization_id}/members/{organization_user_id}/status",
        "platform.schemas.SetActiveRequest",
    ),
    ("POST", "/api/v1/tournaments", "rules_engine.schemas.CreateTournamentRequest"),
    (
        "POST",
        "/api/v1/tournaments/{tournament_id}/versions",
        "tournaments.schemas.CreateDraftVersionRequest",
    ),
    (
        "PATCH",
        "/api/v1/tournaments/{tournament_id}/versions/{version_id}",
        "rules_engine.schemas.UpdateRulesConfigRequest",
    ),
    (
        "PATCH",
        "/api/v1/tournaments/{tournament_id}/versions/{version_id}/rules",
        "rules_engine.schemas.UpdateRulesConfigRequest",
    ),
    ("POST", "/api/v1/tournaments/{tournament_id}/stages", "tournaments.schemas.CreateStageRequest"),
    (
        "POST",
        "/api/v1/tournaments/{tournament_id}/stages/{stage_id}/teams",
        "tournaments.schemas.AssignStageTeamsRequest",
    ),
    (
        "POST",
        "/api/v1/tournaments/{tournament_id}/teams",
        "tournaments.schemas.CreateTournamentTeamRequest",
    ),
    (
        "POST",
        "/api/v1/tournaments/{tournament_id}/teams/bulk",
        "tournaments.schemas.BulkTournamentTeamRequest",
    ),
    (
        "POST",
        "/api/v1/tournaments/{tournament_id}/rosters",
        "tournaments.schemas.CreateRosterPlayerRequest",
    ),
    (
        "PATCH",
        "/api/v1/tournaments/{tournament_id}/rosters/{roster_id}/photo-consent",
        "tournaments.schemas.UpdatePhotoConsentRequest",
    ),
    (
        "PATCH",
        "/api/v1/tournaments/{tournament_id}/rosters/{roster_id}/status",
        "tournaments.schemas.UpdateRosterStatusRequest",
    ),
    (
        "POST",
        "/api/v1/tournaments/{tournament_id}/matches/generate",
        "tournaments.schemas.GenerateSingleEliminationRequest",
    ),
    (
        "POST",
        "/api/v1/tournaments/{tournament_id}/matches/draw",
        "tournaments.schemas.GenerateSingleEliminationRequest",
    ),
    (
        "POST",
        "/api/v1/tournaments/{tournament_id}/matches",
        "tournaments.schemas.CreateMatchRequest",
    ),
    ("POST", "/api/v1/matches/{match_id}/close", "matches.schemas.CloseMatchReportDTO"),
    (
        "POST",
        "/api/v1/matches/{match_id}/segments",
        "matches.schemas.CreateMatchSegmentRequest",
    ),
    (
        "POST",
        "/api/v1/matches/{match_id}/segments/{segment_id}/interrupt",
        "matches.schemas.InterruptMatchSegmentRequest",
    ),
    ("PUT", "/api/v1/matches/{match_id}/lineup", "matches.schemas.SaveMatchLineupRequest"),
    (
        "PATCH",
        "/api/v1/matches/{match_id}/lineup/publication",
        "matches.schemas.PublishMatchLineupRequest",
    ),
    ("POST", "/api/v1/matches/{match_id}/officials", "matches.schemas.OfficialAssignmentRequest"),
]

# Las tres operaciones multipart quedan fuera de alcance (RF-003, RF-006,
# RNF-011): existen en la app, pero su cuerpo es Form/File, no JSON.
MULTIPART_OPERATIONS: list[tuple[str, str]] = [
    ("POST", "/api/v1/tournaments/{tournament_id}/rosters/bulk"),
    ("POST", "/api/v1/tournaments/{tournament_id}/rosters/{roster_id}/photo"),
    ("POST", "/api/v1/tournaments/{tournament_id}/teams/{team_id}/crest"),
]

# Los cinco modelos que solo aparecen dentro de otro cuerpo (plan §2.1).
EXPECTED_NESTED_MODELS: set[str] = {
    "matches.schemas.MatchEventPayload",
    "matches.schemas.MatchLineupEntry",
    "matches.schemas.MatchTeamLineupConfig",
    "rules_engine.schemas.TournamentRulesConfig",
    "tournaments.schemas.BulkTournamentTeamItem",
}

# Ancla literal de las 34 referencias alcanzables desde el inventario: las 29
# de primer nivel (las de EXPECTED_OPERATIONS) más las 5 anidadas. Contra este
# conjunto se contrasta, en ambos sentidos, el conjunto **derivado** del barrido
# (T4): la lista de modelos que se prueba no se escribe a mano.
EXPECTED_MODEL_REFS: set[str] = (
    {model for _, _, model in EXPECTED_OPERATIONS} | EXPECTED_NESTED_MODELS
)

# Cuerpos mínimos sintácticamente válidos, en mapa literal por modelo (plan §3):
# sirven para inyectar la clave extra sin tocar el resto del cuerpo.
MINIMAL_BODIES: dict[type[BaseModel], dict[str, Any]] = {
    RegisterRequest: {
        "email": "nadia@example.com",
        "password": "secret-pass",
        "full_name": "Nadia example",
        "organization_name": "Demo Federation",
        "organization_slug": "demo-federation",
    },
    LoginRequest: {
        "email": "nadia@example.com",
        "password": "secret-pass",
    },
    GoogleStartRequest: {},
    CreateInvitationRequest: {
        "email": "nadia@example.com",
        "role_code": "viewer",
    },
    UpdateMemberRoleRequest: {"role_code": "viewer"},
    UpdateMemberActiveRequest: {"is_active": True},
    AcceptInvitationRequest: {},
    OrganizationCreateRequest: {
        "name": "Demo Federation",
        "slug": "demo-federation",
    },
    OutboxReprocessRequest: {},
    CreateMembershipRequest: {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "role_code": "viewer",
    },
    SetActiveRequest: {"is_active": True},
    CreateTournamentRequest: {
        "name": "Copa Endurecimiento",
        "season": "2026",
        "start_date": "2026-06-01",
    },
    UpdateRulesConfigRequest: {"rules_config": deepcopy(DEFAULT_RULES_CONFIG)},
    TournamentRulesConfig: deepcopy(DEFAULT_RULES_CONFIG),
    CreateTournamentTeamRequest: {"name": "Equipo Demo", "short_code": "EQU-D1"},
    BulkTournamentTeamRequest: {
        "teams": [{"name": "Equipo Demo", "short_code": "EQU-D1"}],
    },
    BulkTournamentTeamItem: {"name": "Equipo Demo", "short_code": "EQU-D1"},
    CreateStageRequest: {
        "version_id": "00000000-0000-0000-0000-000000000001",
        "name": "Fase Uno",
        "stage_type": "round_robin",
        "stage_order": 1,
    },
    AssignStageTeamsRequest: {
        "team_ids": ["00000000-0000-0000-0000-000000000001"],
    },
    CreateMatchRequest: {
        "version_id": "00000000-0000-0000-0000-000000000001",
        "stage_id": "00000000-0000-0000-0000-000000000002",
        "match_date": "2026-06-01T15:00:00Z",
    },
    GenerateSingleEliminationRequest: {
        "version_id": "00000000-0000-0000-0000-000000000001",
        "stage_id": "00000000-0000-0000-0000-000000000002",
        "start_date": "2026-06-01T15:00:00Z",
    },
    CreateDraftVersionRequest: {},
    CreateRosterPlayerRequest: {
        "team_id": "00000000-0000-0000-0000-000000000001",
        "first_name": "Nadia",
        "last_name": "Example",
        "national_id": "123456789",
        "birth_date": "2000-01-01",
        "dorsal_number": 10,
    },
    UpdatePhotoConsentRequest: {"photo_consent": True},
    UpdateRosterStatusRequest: {"is_active": True},
    SaveMatchLineupRequest: {
        "segment_id": "00000000-0000-0000-0000-000000000001",
        "entries": [],
    },
    PublishMatchLineupRequest: {
        "segment_id": "00000000-0000-0000-0000-000000000001",
        "team_id": "00000000-0000-0000-0000-000000000002",
        "is_public": True,
    },
    OfficialAssignmentRequest: {
        "organization_user_id": "00000000-0000-0000-0000-000000000001",
        "official_role": "main_referee",
    },
    CreateMatchSegmentRequest: {"segment_number": 1, "minute_start": 0},
    InterruptMatchSegmentRequest: {"reason": "weather", "minute": 30},
    CloseMatchReportDTO: {
        "resolution_type": "regular",
        "home_score_regular": 0,
        "away_score_regular": 0,
    },
    MatchTeamLineupConfig: {
        "team_id": "00000000-0000-0000-0000-000000000002",
        "formation_code": "4-3-3",
    },
    MatchLineupEntry: {
        "roster_id": "00000000-0000-0000-0000-000000000003",
        "role": "starter",
    },
    MatchEventPayload: {
        "client_event_id": "00000000-0000-0000-0000-000000000004",
        "event_type": "goal",
        "team_id": "00000000-0000-0000-0000-000000000002",
        "player_id": "00000000-0000-0000-0000-000000000003",
        "minute": 10,
        "segment_id": "00000000-0000-0000-0000-000000000001",
    },
}

_IGNORED_METHODS = {"HEAD", "OPTIONS"}
_MODULE_PREFIX = "app.modules."


# ---------------------------------------------------------------------------
# Ayudantes puros del barrido (plan §4)
# ---------------------------------------------------------------------------


def walk_routes(routes: Any, prefix: str = "") -> Any:
    """Recorre el árbol de rutas rendereando ``(ruta completa, APIRoute)``.

    FastAPI 0.143.1 anida los routers incluidos en
    ``_IncludedRouter.original_router.routes`` y el prefijo del
    ``include_router`` vive en ``include_context.prefix``, no en ``route.path``,
    así que viaja por la recursión.
    """

    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        inner = getattr(route, "original_router", None)
        if inner is not None:
            context = getattr(route, "include_context", None)
            inner_prefix = getattr(context, "prefix", "") or ""
            yield from walk_routes(inner.routes, prefix + inner_prefix)


def unwrap_list_optional(annotation: Any) -> Any:
    """Desenreda ``list[T]`` y ``Optional[T]`` (``T | None``) hasta el tipo."""

    while True:
        origin = get_origin(annotation)
        args = get_args(annotation)
        if origin is Union and len(args) == 2 and type(None) in args:
            annotation = args[0] if args[1] is type(None) else args[1]
            continue
        if origin in (list, tuple, set, frozenset) and len(args) == 1:
            annotation = args[0]
            continue
        return annotation


def body_model(route: APIRoute) -> Any:
    """Itera la anotación del cuerpo de cada parámetro de la petición.

    La anotación vive en ``field_info.annotation`` (``ModelField`` no expone
    ``type_``; plan §4).
    """

    for field in route.dependant.body_params:
        yield unwrap_list_optional(field.field_info.annotation)


def is_json_body_route(route: APIRoute) -> bool:
    """Un cuerpo es JSON si ningún parámetro de cuerpo es ``Form``/``File``.

    ``File`` subclasea ``Form``, así que basta con descartar ambos: las tres
    operaciones multipart (cinco parámetros) quedan fuera del barrido.
    """

    return not any(
        isinstance(field.field_info, (FormField, FileField))
        for field in route.dependant.body_params
    )


def model_ref(model: type[BaseModel]) -> str:
    """Referencia estable ``<módulo>.<Clase>`` tal como aparece en el inventario."""

    module = model.__module__
    if module.startswith(_MODULE_PREFIX):
        module = module[len(_MODULE_PREFIX) :]
    return f"{module}.{model.__name__}"


def collect_json_body_operations(
    app: FastAPI,
) -> list[tuple[str, str, type[BaseModel]]]:
    """Deriva ``(método, ruta, modelo)`` de todas las operaciones con cuerpo JSON.

    Determinista, sin base de datos, sin red y sin reloj. Un cuerpo JSON cuyo
    parámetro no sea un modelo Pydantic es un fallo explícito, nunca un
    silencio (plan §4, punto 1).
    """

    operations: list[tuple[str, str, type[BaseModel]]] = []
    for path, route in walk_routes(app.routes):
        if not route.dependant.body_params or not is_json_body_route(route):
            continue
        methods = sorted(m for m in route.methods if m not in _IGNORED_METHODS)
        annotations = list(body_model(route))
        for annotation in annotations:
            if not (isinstance(annotation, type) and issubclass(annotation, BaseModel)):
                raise AssertionError(
                    f"La operación {methods} {path} declara un cuerpo JSON sin "
                    f"modelo Pydantic: {annotation!r}. El inventario de la spec "
                    "019 exige un modelo por operación."
                )
        for method in methods:
            for annotation in annotations:
                operations.append((method, path, annotation))
    return operations


def _collect_models(annotation: Any, found: set[type[BaseModel]]) -> None:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation in found:
            return
        found.add(annotation)
        for field in annotation.model_fields.values():
            _collect_models(field.annotation, found)
        return
    for argument in get_args(annotation):
        _collect_models(argument, found)


def collect_nested_models(
    top_level: set[type[BaseModel]],
) -> set[type[BaseModel]]:
    """Modelos Pydantic que solo aparecen dentro de otro cuerpo de petición."""

    nested: set[type[BaseModel]] = set()
    for model in top_level:
        for field in model.model_fields.values():
            _collect_models(field.annotation, nested)
    return nested - top_level


def minimal_valid_body(model: type[BaseModel]) -> dict[str, Any]:
    """Cuerpo mínimo sintácticamente válido para ``model`` (mapa literal)."""

    if model not in MINIMAL_BODIES:
        raise AssertionError(
            f"Falta el cuerpo mínimo literal para {model_ref(model)}: "
            "añádelo a MINIMAL_BODIES antes de exigir su rechazo."
        )
    return dict(MINIMAL_BODIES[model])


def derive_strict_models() -> tuple[list[type[BaseModel]], set[type[BaseModel]]]:
    """Deriva del barrido el conjunto completo de modelos servidos (T4).

    Devuelve ``(modelos servidos ordenados, modelos de primer nivel)``: los que
    la app declara como cuerpo **más** los que solo aparecen anidados dentro de
    otro cuerpo, alcanzados **recursivamente** desde cualquier operación.
    Determinista (orden por referencia), sin base de datos, sin red y sin reloj.
    Una operación JSON sin modelo Pydantic falla aquí con mensaje explícito
    (salvaguarda 3), nunca en silencio.
    """

    operations = collect_json_body_operations(api)
    top_level = {model for _, _, model in operations}
    served = top_level | collect_nested_models(top_level)
    return sorted(served, key=model_ref), top_level


# Los 34 modelos que se prueban: **derivados del barrido**, no escritos a mano,
# de modo que una operación o un modelo nuevo entra solo en el conjunto probado
# (biyección con EXPECTED_MODEL_REFS más abajo) y una desviación futura se
# detecta aquí. `TOP_LEVEL_MODELS` solo distingue el rol para los mensajes.
STRICT_MODELS, TOP_LEVEL_MODELS = derive_strict_models()


# ---------------------------------------------------------------------------
# (a) Inventario: biyección exacta con la app
# ---------------------------------------------------------------------------


def test_inventory_has_33_literal_operations():
    assert len(EXPECTED_OPERATIONS) == 33
    assert len(set(EXPECTED_OPERATIONS)) == 33


def test_json_operations_match_the_literal_inventory():
    derived = [
        (method, path, model_ref(model))
        for method, path, model in collect_json_body_operations(api)
    ]
    expected = Counter(EXPECTED_OPERATIONS)
    actual = Counter(derived)
    missing = sorted((expected - actual).elements())
    extra = sorted((actual - expected).elements())
    assert not missing and not extra, (
        "El barrido de app.main.api no coincide con el inventario literal de "
        f"33 operaciones JSON. Faltan: {missing or 'ninguna'}; sobran: "
        f"{extra or 'ninguna'}."
    )
    assert len(derived) == 33


def test_inventory_declares_29_top_level_models():
    refs = {model for _, _, model in EXPECTED_OPERATIONS}
    assert len(refs) == 29


def test_app_yields_29_top_level_and_5_nested_models():
    operations = collect_json_body_operations(api)
    top_level = {model for _, _, model in operations}
    nested = collect_nested_models(top_level)
    assert len(top_level) == 29, sorted(model_ref(m) for m in top_level)
    assert len(nested) == 5, sorted(model_ref(m) for m in nested)


def test_nested_models_match_the_literal_inventory():
    operations = collect_json_body_operations(api)
    top_level = {model for _, _, model in operations}
    nested = {model_ref(m) for m in collect_nested_models(top_level)}
    assert nested == EXPECTED_NESTED_MODELS, (
        f"faltan: {sorted(EXPECTED_NESTED_MODELS - nested)}; "
        f"sobran: {sorted(nested - EXPECTED_NESTED_MODELS)}"
    )


def test_multipart_operations_exist_and_stay_out_of_the_inventory():
    json_pairs = {(method, path) for method, path, _ in collect_json_body_operations(api)}
    body_routes = {
        (method, path): route
        for path, route in walk_routes(api.routes)
        if route.dependant.body_params
        for method in route.methods
        if method not in _IGNORED_METHODS
    }
    for method, path in MULTIPART_OPERATIONS:
        route = body_routes.get((method, path))
        assert route is not None, f"la operación multipart {method} {path} ya no existe"
        assert not is_json_body_route(route), (
            f"{method} {path} dejó de ser multipart y ahora debe figurar en "
            "EXPECTED_OPERATIONS"
        )
        assert (method, path) not in json_pairs, (
            f"{method} {path} es multipart y no puede figurar en el inventario JSON"
        )


# ---------------------------------------------------------------------------
# Salvaguarda 3: una operación JSON sin modelo Pydantic falla con mensaje
# explícito. Se construye la desviación en una app de prueba para no tocar
# `backend/app/` (T4 es solo de pruebas).
# ---------------------------------------------------------------------------


def test_json_operation_without_pydantic_model_fails_with_explicit_message():
    probe = FastAPI()

    @probe.post("/api/v1/probe/payload")
    async def probe_handler(payload: dict):
        return payload

    with pytest.raises(AssertionError) as excinfo:
        collect_json_body_operations(probe)
    message = str(excinfo.value)
    assert "sin modelo Pydantic" in message, message
    assert "/api/v1/probe/payload" in message, message


# ---------------------------------------------------------------------------
# (b) Conjunto derivado de los 34 modelos: biyección, bandera y rechazo
# ---------------------------------------------------------------------------


def test_strict_models_are_exactly_the_34_models_of_the_literal_inventory():
    """T4: lo que se prueba es exactamente lo que sirve la app, y viceversa.

    El conjunto sale **del barrido** (no de una lista escrita a mano) y se
    contrasta con las 34 referencias literales en ambos sentidos: un modelo o
    una operación que aparezca sin entrada literal, o una entrada sin operación,
    falla aquí con mensaje explícito (RF-002, RF-005, RNF-001).
    """

    derived, _ = derive_strict_models()
    derived_refs = {model_ref(m) for m in derived}
    missing = sorted(EXPECTED_MODEL_REFS - derived_refs)
    extra = sorted(derived_refs - EXPECTED_MODEL_REFS)
    assert not missing and not extra, (
        "El conjunto derivado del barrido no coincide con las 34 referencias "
        f"del inventario literal. Faltan: {missing or 'ninguna'}; sobran: "
        f"{extra or 'ninguna'}."
    )
    assert len(derived) == 34, f"el barrido deriva {len(derived)} modelos, no 34"
    assert derived == STRICT_MODELS, (
        "STRICT_MODELS (el conjunto que se parametriza) no es el derivado del "
        "barrido actual: la lista parametrizada quedó desactualizada."
    )


def test_minimal_bodies_cover_exactly_the_derived_models():
    """Cada modelo derivado tiene cuerpo mínimo y no sobra ninguno (RF-006)."""

    derived = set(STRICT_MODELS)
    without_body = [model_ref(m) for m in STRICT_MODELS if m not in MINIMAL_BODIES]
    unused = [model_ref(m) for m in MINIMAL_BODIES if m not in derived]
    assert not without_body and not unused, (
        "MINIMAL_BODIES no cubre exactamente el conjunto derivado del barrido. "
        f"Sin cuerpo mínimo: {without_body or 'ninguno'}; sobrantes: "
        f"{unused or 'ninguno'}."
    )


@pytest.mark.parametrize("model", STRICT_MODELS, ids=lambda m: m.__name__)
def test_minimal_body_is_valid(model):
    model.model_validate(minimal_valid_body(model))


@pytest.mark.parametrize("model", STRICT_MODELS, ids=lambda m: m.__name__)
def test_strict_model_forbids_extra(model):
    """Salvaguardas 1 y 2: el mensaje distingue el rol del modelo.

    Un modelo de **primer nivel** sin bandera y un modelo **anidado** sin
    bandera fallan ambos aquí con el rol y la referencia en el texto, no como
    un ``assert`` mudo (RF-005).
    """

    role = "de primer nivel" if model in TOP_LEVEL_MODELS else "anidado"
    assert model.model_config.get("extra") == "forbid", (
        f"El modelo {role} {model_ref(model)} no declara "
        'model_config = ConfigDict(extra="forbid") (RF-005).'
    )


@pytest.mark.parametrize("model", STRICT_MODELS, ids=lambda m: m.__name__)
def test_strict_model_rejects_extra_key(model):
    """T4: rechazo parametrizado en los 34 modelos derivados del barrido.

    ``model_validate(minimal_valid_body(model) | {"extra": 1})`` lanza
    ``ValidationError`` con ``type == "extra_forbidden"`` y ``loc`` apuntando a
    ``extra``. El valor rechazado (``1``) se conserva **solo** dentro del error
    de Pydantic: el saneado del 422 lo retira (RF-010; lo prueba T5).
    """

    body = minimal_valid_body(model) | {"extra": 1}
    try:
        model.model_validate(body)
    except ValidationError as exc:
        errors = exc.errors()
    else:
        pytest.fail(
            f"{model_ref(model)} aceptó la clave no declarada 'extra': sin "
            'model_config = ConfigDict(extra="forbid") la tolera en silencio '
            "(RF-005)."
        )
    extra_errors = [e for e in errors if list(e["loc"])[:1] == ["extra"]]
    assert extra_errors, (
        f"{model_ref(model)} rechazó 'extra' pero la ubicación no empieza por "
        f"'extra': {[(e['type'], list(e['loc'])) for e in errors]}"
    )
    error = extra_errors[0]
    assert error["type"] == "extra_forbidden", (
        f"{model_ref(model)} rechazó 'extra' con tipo {error['type']!r}, "
        "no 'extra_forbidden'."
    )
    assert error["input"] == 1, (
        f"{model_ref(model)} no conserva el valor rechazado dentro del error "
        "de Pydantic: lo retira el saneado del 422 (T5), no el modelo."
    )


# ---------------------------------------------------------------------------
# T5 — Precedencia por capas y forma saneada del 422 (RF-009, RF-010)
#
# Subconjunto HTTP representativo (reglas, creación de torneo, alta en roster
# y evento de partido) con `httpx.ASGITransport` sobre `app.main.api` y
# `dependency_overrides`. Orden medido (plan §6 D-4, FastAPI 0.143.1):
#
#   middleware (main.py:816-869): Content-Length inválido 400 → tamaño 413 →
#                                 origen/CSRF 403
#   dependencias:                sesión 401 (security.py:45-47, sin tocar BD)
#                                → cabecera de organización ausente 400
#                                  (tenancy.py:24-28, tras la sesión)
#                                → membresía con rol activo 403
#                                  (tenancy.py:59-60, «miembro sin rol»)
#                                → administrador de plataforma 403
#                                  (platform.py:27-28)
#   cuerpo:                      422 saneado (main.py:601-624, sin code)
#   manejador:                   permiso de ruta 403 y recurso de otra
#                                organización 404; con clave de más, 422
#
# Cada caso envía una clave no declarada (o un evento con una), así que una
# capa que se adelante al cuerpo se ve como su código real y el 422 solo
# aparece cuando el cuerpo es la capa decisiva. Ninguna prueba necesita base
# de datos: las dependencias de contexto se sustituyen y los caminos de
# manejador corren contra un sustituto determinista de `AsyncSession` que
# registra cada consulta. El middleware real sí participa (ASGITransport
# ejercita la pila completa de `api`), por lo que los 400/413/403 de forma y
# de origen se prueban de forma fidedigna.
# ---------------------------------------------------------------------------

# Identificadores de prueba: los caminos de manejador nunca resuelven filas
# contra una base real (el sustituto no tiene ninguna).
_TOURNAMENT_ID = "11111111-1111-1111-1111-111111111111"
_VERSION_ID = "22222222-2222-2222-2222-222222222222"
_MATCH_ID = "33333333-3333-3333-3333-333333333333"

# Valor con forma de dato enviando en la clave extra: si el saneado lo
# devolviera (RF-010 prohíbe el eco del valor rechazado), aparecería en la
# respuesta.
REJECTED_VALUE = "clave_inyectada_no_declarada"

_RULES_PATH = f"/api/v1/tournaments/{_TOURNAMENT_ID}/versions/{_VERSION_ID}/rules"
_TOURNAMENT_CREATE_PATH = "/api/v1/tournaments"
_ROSTER_PATH = f"/api/v1/tournaments/{_TOURNAMENT_ID}/rosters"
_CLOSE_PATH = f"/api/v1/matches/{_MATCH_ID}/close"
_PLATFORM_OUTBOX_PATH = "/api/v1/platform/outbox/reprocess"


def invalid_body(model: type[BaseModel]) -> dict[str, Any]:
    """Cuerpo mínimo válido de ``model`` con una clave no declarada."""

    return minimal_valid_body(model) | {"extra": REJECTED_VALUE}


def invalid_close_report_with_extra_event_key() -> dict[str, Any]:
    """Acta mínima cuyo **evento** anidado trae una clave no declarada."""

    event = minimal_valid_body(MatchEventPayload) | {"extra": REJECTED_VALUE}
    return {
        "resolution_type": "regular",
        "home_score_regular": 0,
        "away_score_regular": 0,
        "events": [event],
    }


async def asgi_request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    """Petición real contra ``app.main.api`` por ASGI, sin servidor ni BD."""

    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as client:
        return await client.request(method, path, **kwargs)


def assert_sanitized_validation_error(
    response: httpx.Response, *, expected_loc: list[Any]
) -> None:
    """RF-010: forma saneada del 422, sin ``code`` y sin eco del valor.

    ``main.py:601-624`` reduce cada error a ``VALIDATION_ERROR_FIELDS``
    (``main.py:67``): ``type``/``loc``/``msg``. Un ``input``, un ``ctx``, un
    ``code`` de primer nivel o el valor rechazado en la respuesta significan
    que el saneado se rompió.
    """

    assert response.status_code == 422, response.text
    payload = response.json()
    assert set(payload) == {"detail"}, (
        f"el 422 saneado solo lleva 'detail' (sin 'code'): {sorted(payload)}"
    )
    detail = payload["detail"]
    assert isinstance(detail, list) and detail, "detail sigue siendo una lista de errores"
    for error in detail:
        assert isinstance(error, dict), error
        assert {"type", "loc", "msg"} <= set(error), error
        extra_fields = set(error) - {"type", "loc", "msg"}
        assert not extra_fields, (
            f"el saneado retira input/ctx/cualquier otro campo, pero llegó "
            f"{sorted(extra_fields)}: {error}"
        )
    assert REJECTED_VALUE not in response.text, (
        "el saneado devuelve el valor rechazado en la respuesta (RF-010)"
    )
    extra_errors = [error for error in detail if error["type"] == "extra_forbidden"]
    assert extra_errors, f"sin error extra_forbidden en {detail}"
    locations = [list(error["loc"]) for error in extra_errors]
    assert locations == [expected_loc] * len(extra_errors), (
        f"ubicación {expected_loc} esperada para la clave no declarada; "
        f"llegó {locations}"
    )


@pytest.fixture
def overrides() -> dict[Any, Any]:
    """Limpia y restaura ``api.dependency_overrides`` alrededor de cada caso."""

    saved = api.dependency_overrides.copy()
    api.dependency_overrides.clear()
    try:
        yield api.dependency_overrides
    finally:
        api.dependency_overrides.clear()
        api.dependency_overrides.update(saved)


class _FakeResult:
    """Resultado sin filas: los manejadores resuelven 404/403 con ``None``."""

    def scalar_one_or_none(self) -> None:
        return None


class _FakeTransaction:
    async def __aenter__(self) -> _FakeTransaction:
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False


class _FakeSession:
    """Sustituto determinista de ``AsyncSession`` que registra cada consulta.

    Solo declara lo que estos caminos de manejador usan: ``begin()`` y
    ``execute()`` con un resultado sin filas —el 404 de ``_ensure_tournament``
    (tournaments/router.py:120-130) y el 403 de ``require_permission``
    (core/permissions.py:58-59) se resuelven con ``scalar_one_or_none() is
    None``—. Si un manejador exigiera otra cosa, la prueba falla aquí en
    lugar de fingir comportamiento.
    """

    def __init__(self) -> None:
        self.executed: list[str] = []

    def begin(self) -> _FakeTransaction:
        return _FakeTransaction()

    async def execute(self, statement: Any, parameters: Any = None) -> _FakeResult:
        del parameters
        self.executed.append(str(statement))
        return _FakeResult()


def install_fake_db(overrides: dict[Any, Any]) -> list[_FakeSession]:
    """Sustituye ``get_db`` por un manejador de sesiones deterministas.

    Devuelve la lista de sesiones creadas: la dependencia se resuelve (y la
    sesión aparece) **antes** que el cuerpo, pero sus ``execute()`` solo
    pueden venir del manejador, de modo que una petición con clave de más
    debe dejar la lista de consultas vacía.
    """

    sessions: list[_FakeSession] = []

    async def fake_get_db() -> Any:
        session = _FakeSession()
        sessions.append(session)
        yield session

    overrides[get_db] = fake_get_db
    return sessions


async def authenticated_member() -> AuthContext:
    """Membresía con rol activa resuelta: el manejador recibe su contexto."""

    return AuthContext(
        user_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        organization_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        organization_user_id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
    )


async def membership_without_active_role() -> AuthContext:
    """Dependencia de membresía que lanza 403 («miembro sin rol», tenancy.py:59-60)."""

    raise HTTPException(
        status_code=403, detail="Membresía o rol activo no válido"
    )


async def session_resolved_user() -> UUID:
    """Sesión válida resuelta: el siguiente eslabón es la cabecera de organización."""

    return UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


async def platform_membership_denied() -> PlatformContext:
    """Dependencia de plataforma que lanza 403 (platform.py:27-28)."""

    raise HTTPException(
        status_code=403, detail="Administrador de plataforma requerido"
    )


# --- Capa 1 y 2: rechazos de forma y origen del middleware (RF-009) ---------


async def test_invalid_content_length_400_precedes_body_in_rules(overrides):
    """El middleware rechaza un ``Content-Length`` no numérico antes del cuerpo.

    ``main.py:819-827`` devuelve **400** sin leer el cuerpo: con una clave no
    declarada en la petición sigue ganando el 400, no el 422 (RF-009, capa
    «forma del middleware»). El middleware real participa porque
    ``ASGITransport`` ejercita la pila completa de ``api``.
    """

    del overrides  # sin overrides: la capa responde antes de las dependencias
    response = await asgi_request(
        "PATCH",
        _RULES_PATH,
        content=b"{}",
        headers={
            "content-type": "application/json",
            "content-length": "no-numerico",
        },
    )
    assert response.status_code == 400, response.text
    assert response.json() == {"detail": "Content-Length inválido"}


async def test_oversized_content_length_413_precedes_body_in_tournament_create(overrides):
    """Un ``Content-Length`` por encima del máximo es 413 antes del cuerpo.

    ``main.py:828-832`` compara el tamaño declarado contra
    ``max_request_body_bytes`` y responde **413** sin leer el cuerpo: una
    clave de más no lo convierte en 422 (RF-009, capa «forma del
    middleware»).
    """

    del overrides
    oversized = str(200 * 1024 * 1024)  # por encima del techo del propio settings (200 MiB)
    response = await asgi_request(
        "POST",
        _TOURNAMENT_CREATE_PATH,
        content=b"{}",
        headers={"content-type": "application/json", "content-length": oversized},
    )
    assert response.status_code == 413, response.text
    assert response.json() == {"detail": "La solicitud supera el tamaño máximo permitido"}


async def test_disallowed_origin_403_precedes_body_in_tournament_create(overrides):
    """Un origen no permitido responde 403 en el middleware, antes del cuerpo.

    ``main.py:844-856`` valida el origen con ``validate_request_origin`` y
    devuelve **403** sin ejecutar dependencias ni validar el cuerpo: con una
    clave de más sigue ganando el 403 (RF-009, capa «origen y CSRF»).
    """

    del overrides
    response = await asgi_request(
        "POST",
        _TOURNAMENT_CREATE_PATH,
        json=invalid_body(CreateTournamentRequest),
        headers={"origin": "https://evil.example"},
    )
    assert response.status_code == 403, response.text
    assert response.json() == {"detail": "Origen no permitido"}


# --- Capa 3: dependencias — sesión, cabecera de organización, membresía ---


async def test_missing_session_401_precedes_body_in_roster(overrides):
    """Sin sesión, la cadena real responde 401 antes de validar el cuerpo.

    ``get_auth_context`` (tenancy.py:19-62) resuelve primero
    ``get_current_user_id`` (security.py:106-133), que sin credenciales lanza
    401 en ``decode_access_token_claims`` (security.py:45-47) **antes** de
    tocar la base; por eso ninguna dependencia necesita BD en este caso. El
    control con la sesión resuelta demuestra que el 401 era la capa de
    sesión: la siguiente capa (cabecera de organización) responde 400.
    """

    # Sin overrides: corre la cadena real de dependencias hasta el 401.
    response = await asgi_request(
        "POST", _ROSTER_PATH, json=invalid_body(CreateRosterPlayerRequest)
    )
    assert response.status_code == 401, response.text
    assert response.json() == {"detail": "Autenticación requerida"}

    overrides[get_current_user_id] = session_resolved_user
    after_session = await asgi_request(
        "POST", _ROSTER_PATH, json=invalid_body(CreateRosterPlayerRequest)
    )
    assert after_session.status_code == 400, after_session.text
    assert after_session.json() == {"detail": "Debe indicar X-Organization-ID"}


async def test_missing_organization_header_400_precedes_body_in_tournament_create(overrides):
    """Con sesión válida, la cabecera de organización ausente es 400 (401 → 400).

    Solo se sustituye la sesión (``get_current_user_id``); la dependencia
    **real** ``get_auth_context`` comprueba la cabecera en
    tenancy.py:24-28 **antes** de ``db.begin()``, así que el 400 sale sin
    base de datos y con una clave de más en el cuerpo sigue ganando el 400
    (RF-009, criterio 1: tras la sesión, dentro de la dependencia).
    """

    overrides[get_current_user_id] = session_resolved_user
    response = await asgi_request(
        "POST", _TOURNAMENT_CREATE_PATH, json=invalid_body(CreateTournamentRequest)
    )
    assert response.status_code == 400, response.text
    assert response.json() == {"detail": "Debe indicar X-Organization-ID"}


async def test_membership_dependency_403_precedes_body_in_rules(overrides):
    """La membresía con rol activo (dependencia) responde 403 antes del cuerpo.

    La dependencia real es ``get_auth_context`` (tenancy.py:59-60, «miembro
    sin rol»); aquí se representa con una dependencia de membresía que lanza
    ese mismo 403, sin base de datos. El control con cuerpo válido responde
    igual: la capa no depende del cuerpo, y una validación de cuerpo por
    delante devolvería 422 en lugar de 403 (RF-009, criterio 1).
    """

    overrides[get_auth_context] = membership_without_active_role
    response = await asgi_request(
        "PATCH", _RULES_PATH, json=invalid_body(UpdateRulesConfigRequest)
    )
    assert response.status_code == 403, response.text
    assert response.json() == {"detail": "Membresía o rol activo no válido"}

    control = await asgi_request(
        "PATCH", _RULES_PATH, json=minimal_valid_body(UpdateRulesConfigRequest)
    )
    assert control.status_code == 403, control.text
    assert control.json() == {"detail": "Membresía o rol activo no válido"}


async def test_platform_admin_dependency_403_precedes_body(overrides):
    """El administrador de plataforma (dependencia) responde 403 antes del cuerpo.

    La dependencia real es ``get_platform_context`` (platform.py:27-28); aquí
    se representa con esa dependencia lanzando su 403, sin base de datos. Un
    usuario que no es administrador de plataforma recibe 403 aunque traiga
    una clave de más (RF-009, criterio 1; caso límite 19).
    """

    overrides[get_platform_context] = platform_membership_denied
    response = await asgi_request(
        "POST", _PLATFORM_OUTBOX_PATH, json=invalid_body(OutboxReprocessRequest)
    )
    assert response.status_code == 403, response.text
    assert response.json() == {"detail": "Administrador de plataforma requerido"}


class _MembershipResult:
    """Resultado con las dos formas de lectura que usa ``get_auth_context``."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one(self) -> Any:
        return self._value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _MembershipSession(_FakeSession):
    """Sesión determinista para ejercer la **dependencia real** de membresía.

    ``get_auth_context`` (tenancy.py:19-62) fija el contexto RLS, comprueba la
    pertenencia con ``fn_verify_user_org_membership`` (escalar verdadero) y
    resuelve la fila de rol activo (``None`` = «miembro sin rol»). El sustituto
    responde solo a esas consultas; cualquier otra devuelve un resultado sin
    filas, igual que ``_FakeSession``, y queda registrada.
    """

    ROLE_ROW = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

    def __init__(self, *, has_active_role: bool) -> None:
        super().__init__()
        self._has_active_role = has_active_role

    async def execute(self, statement: Any, parameters: Any = None) -> Any:
        await super().execute(statement, parameters)
        text_ = str(statement)
        if "fn_verify_user_org_membership" in text_:
            return _MembershipResult(True)
        if "organization_user_roles" in text_:
            return _MembershipResult(self.ROLE_ROW if self._has_active_role else None)
        return _FakeResult()


def install_membership_db(
    overrides: dict[Any, Any], *, has_active_role: bool
) -> list[_MembershipSession]:
    """Sustituye solo ``get_db`` y la sesión: ``get_auth_context`` corre real."""

    sessions: list[_MembershipSession] = []

    async def fake_get_db() -> Any:
        session = _MembershipSession(has_active_role=has_active_role)
        sessions.append(session)
        yield session

    overrides[get_db] = fake_get_db
    overrides[get_current_user_id] = session_resolved_user
    return sessions


_ORGANIZATION_HEADERS = {"X-Organization-ID": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"}


async def test_real_membership_dependency_403_precedes_body_in_rules(overrides):
    """Orden **real** de la dependencia de membresía, sin sustituirla (RF-009).

    Solo se sustituyen la sesión (``get_current_user_id``) y ``get_db``: la
    dependencia ``get_auth_context`` corre de verdad. Un miembro activo sin
    ninguna fila de rol recibe **403** «Membresía o rol activo no válido»
    aunque el cuerpo traiga una clave de más, y la única actividad contra la
    base es la propia de la dependencia (contexto RLS, pertenencia y rol).
    Control: con el mismo camino y un rol activo, la misma clave de más llega
    al cuerpo y la respuesta es el 422 saneado, sin ninguna consulta del
    manejador; es decir, la capa de membresía decide **antes** del cuerpo y el
    cuerpo **antes** del manejador.
    """

    dependency_queries = (
        "set_config",
        "fn_verify_user_org_membership",
        "organization_user_roles",
    )

    sessions = install_membership_db(overrides, has_active_role=False)
    denied = await asgi_request(
        "PATCH",
        _RULES_PATH,
        json=invalid_body(UpdateRulesConfigRequest),
        headers=_ORGANIZATION_HEADERS,
    )
    assert denied.status_code == 403, denied.text
    assert denied.json() == {"detail": "Membresía o rol activo no válido"}
    assert len(sessions) == 1 and any(
        "organization_user_roles" in statement for statement in sessions[0].executed
    ), "la dependencia real de membresía no llegó a resolver el rol"

    overrides.clear()
    sessions = install_membership_db(overrides, has_active_role=True)
    passed = await asgi_request(
        "PATCH",
        _RULES_PATH,
        json=invalid_body(UpdateRulesConfigRequest),
        headers=_ORGANIZATION_HEADERS,
    )
    assert_sanitized_validation_error(passed, expected_loc=["body", "extra"])
    assert len(sessions) == 1 and sessions[0].executed, (
        "la dependencia real de membresía no se ejecutó antes del cuerpo"
    )
    foreign = [
        statement
        for statement in sessions[0].executed
        if not any(marker in statement for marker in dependency_queries)
    ]
    assert foreign == [], (
        f"el manejador consultó con una clave de más en el cuerpo: {foreign}"
    )


async def test_read_only_platform_admin_422_on_extra_key_and_403_on_valid_body(overrides):
    """Caso límite 20: perfil de solo lectura de plataforma (RF-009).

    ``get_platform_context`` (la dependencia) **sí** deja pasar a un
    administrador con rol ``platform_support``; el permiso de escritura
    (``require_platform_write``, router.py:131) vive en el **manejador**.
    Por eso, en ``POST /platform/outbox/reprocess``, con una clave de más el
    cuerpo se rechaza antes con el 422 saneado (sin ``code``, sin eco del valor
    y sin ninguna consulta propia), y con el mismo perfil y un cuerpo válido el
    manejador responde **403** «Permiso de escritura de plataforma requerido».
    """

    async def read_only_platform_admin() -> PlatformContext:
        return PlatformContext(
            user_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            role_code="platform_support",
        )

    sessions = install_fake_db(overrides)
    overrides[get_platform_context] = read_only_platform_admin

    invalid = await asgi_request(
        "POST", _PLATFORM_OUTBOX_PATH, json=invalid_body(OutboxReprocessRequest)
    )
    assert_sanitized_validation_error(invalid, expected_loc=["body", "extra"])
    assert len(sessions) == 1 and sessions[0].executed == [], (
        "el manejador de plataforma se ejecutó con una clave de más: el 422 "
        "debió resolverse antes (RF-009, caso límite 20)"
    )

    valid = await asgi_request(
        "POST", _PLATFORM_OUTBOX_PATH, json=minimal_valid_body(OutboxReprocessRequest)
    )
    assert valid.status_code == 403, valid.text
    assert valid.json() == {"detail": "Permiso de escritura de plataforma requerido"}
    assert len(sessions) == 2, "el control con cuerpo válido no llegó al manejador"
    assert sessions[1].executed == [], (
        "el 403 de escritura es de ``require_platform_write``, antes de cualquier consulta"
    )


# --- Capa 5: el 422 del cuerpo gana a las comprobaciones del manejador ----


async def test_handler_resource_404_loses_to_invalid_body_in_roster(overrides):
    """El recurso de otra organización (manejador) pierde ante el 422 del cuerpo.

    Con el sustituto sin filas, un cuerpo **válido** llega al manejador y
    ``_ensure_tournament`` (tournaments/router.py:120-130) resuelve 404
    «Torneo no encontrado» —el mismo 404 que resuelve un torneo ajeno, que
    por organización no aparece—. Con la misma ruta, los mismos overrides y
    una clave de más, la respuesta es el 422 saneado y **ninguna consulta**
    llega a la base: el manejador no se ejecuta (RF-009, criterio 2; caso
    límite 22). El 422 sale del saneado real de ``main.py``, no de un
    manejador simulado.
    """

    sessions = install_fake_db(overrides)
    overrides[get_auth_context] = authenticated_member

    invalid = await asgi_request(
        "POST", _ROSTER_PATH, json=invalid_body(CreateRosterPlayerRequest)
    )
    assert_sanitized_validation_error(invalid, expected_loc=["body", "extra"])
    assert len(sessions) == 1 and sessions[0].executed == [], (
        "el manejador se ejecutó con una clave de más en el cuerpo: el 422 "
        "debió resolverse antes (RF-009)"
    )

    valid = await asgi_request(
        "POST", _ROSTER_PATH, json=minimal_valid_body(CreateRosterPlayerRequest)
    )
    assert valid.status_code == 404, valid.text
    assert valid.json() == {"detail": "Torneo no encontrado"}
    assert len(sessions) == 2 and sessions[1].executed, (
        "el control con cuerpo válido no llegó al manejador"
    )


async def test_handler_permission_403_loses_to_invalid_body_in_tournament_create(overrides):
    """El permiso de ruta (manejador) pierde ante el 422 del cuerpo.

    Con el sustituto sin filas, un cuerpo **válido** llega a
    ``require_permission`` (core/permissions.py:58-59), que resuelve
    ``PermissionError`` → **403** «Permiso requerido: MANAGE_TOURNAMENTS»
    dentro del manejador de creación de torneo
    (tournaments/router.py:386-391). Con la misma ruta, los mismos overrides
    y una clave de más, la respuesta es el 422 saneado y no hay consultas:
    el 422 gana al 403 de permiso (RF-009, criterio 2; caso límite 21).
    """

    sessions = install_fake_db(overrides)
    overrides[get_auth_context] = authenticated_member

    invalid = await asgi_request(
        "POST", _TOURNAMENT_CREATE_PATH, json=invalid_body(CreateTournamentRequest)
    )
    assert_sanitized_validation_error(invalid, expected_loc=["body", "extra"])
    assert len(sessions) == 1 and sessions[0].executed == [], (
        "el manejador se ejecutó con una clave de más en el cuerpo: el 422 "
        "debió resolverse antes (RF-009)"
    )

    valid = await asgi_request(
        "POST", _TOURNAMENT_CREATE_PATH, json=minimal_valid_body(CreateTournamentRequest)
    )
    assert valid.status_code == 403, valid.text
    assert valid.json() == {"detail": "Permiso requerido: MANAGE_TOURNAMENTS"}
    assert len(sessions) == 2 and sessions[1].executed, (
        "el control con cuerpo válido no llegó al manejador"
    )


async def test_match_event_extra_key_is_sanitized_422(overrides):
    """Evento de partido con clave extra: 422 saneado con la ubicación anidada.

    La clave no declarada vive dentro del evento (``events[0]``), así que la
    ubicación señala el camino completo (RF-002, RF-010) y el valor
    rechazado no vuelve. Sin consultas: el acta nunca llega al manejador.
    El control con la dependencia de membresía lanzando 403 demuestra que en
    la ruta del acta la precedencia también se cumple (RF-009).
    """

    sessions = install_fake_db(overrides)
    overrides[get_auth_context] = authenticated_member

    response = await asgi_request(
        "POST", _CLOSE_PATH, json=invalid_close_report_with_extra_event_key()
    )
    assert_sanitized_validation_error(
        response, expected_loc=["body", "events", 0, "extra"]
    )
    assert sessions and sessions[0].executed == [], (
        "el cierre se ejecutó con una clave de más en un evento: el 422 "
        "estructural debe resolverse antes (RF-008, RF-009)"
    )

    overrides[get_auth_context] = membership_without_active_role
    dependency_first = await asgi_request(
        "POST", _CLOSE_PATH, json=invalid_close_report_with_extra_event_key()
    )
    assert dependency_first.status_code == 403, dependency_first.text
    assert dependency_first.json() == {"detail": "Membresía o rol activo no válido"}
