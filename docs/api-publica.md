# API pública de Bracket Craft (`v1`)

Guía para terceros que quieran mostrar en su web o en su aplicación los torneos publicados en Bracket Craft. La API solo lee: devuelve lo mismo que ve cualquier visitante del sitio público, sin documentos de identidad ni fechas de nacimiento, y con las fotos de jugadores solo cuando hay consentimiento de imagen.

Versión en inglés: [api-publica.en.md](api-publica.en.md).

## URL base y documento OpenAPI

- **URL base:** el dominio del sitio seguido de `/api/v1`, por ejemplo `https://torneos.example.org/api/v1`.
- **Documento OpenAPI 3.1:** `GET /api/v1/public/openapi.json`. Solo describe las 9 lecturas de esta guía y es la referencia exacta de cada campo.
- **Copia de referencia en el repositorio:** `docs/api-publica/openapi-v1.json`.

## Lecturas

| Lectura | Ruta | Parámetros de consulta |
|---|---|---|
| Listado de torneos | `GET /api/v1/tournaments/public` | `limit` (1–200, 100 por defecto), `offset` |
| Detalle de un torneo | `GET /api/v1/tournaments/public/{tournament_id}` | — |
| Clasificación | `GET /api/v1/tournaments/public/{tournament_id}/standings` | `stage_id`, `group_id`, `limit` (1–500, 200), `offset` |
| Partidos | `GET /api/v1/tournaments/public/{tournament_id}/matches` | `stage_id`, `group_id`, `limit` (1–500, 200), `offset` |
| Detalle de un partido | `GET /api/v1/tournaments/public/{tournament_id}/matches/{match_id}` | — |
| Cronología de un partido | `GET /api/v1/tournaments/public/{tournament_id}/matches/{match_id}/timeline` | — |
| Estadísticas de jugadores | `GET /api/v1/tournaments/public/{tournament_id}/player-stats` | `stage_id`, `group_id`, `limit` (1–500, 200), `offset` |
| Estadísticas de equipos | `GET /api/v1/tournaments/public/{tournament_id}/team-stats` | `stage_id`, `group_id`, `limit` (1–500, 200), `offset` |
| Ficha de jugador | `GET /api/v1/tournaments/public/players/{player_id}` | — |

Todos los identificadores son UUID. Todas las respuestas son `application/json`.

- **Partidos:** cada partido tiene una forma según `status`. `live` añade el reloj y `is_provisional: true`; `suspended` solo tiene 14 claves (equipos, marcador provisional y reloj). El resto (`scheduled`, `finished`, `cancelled`, `administrative_resolution`) usa la forma completa.
- **Cronología:** `availability` vale `pending` (el partido aún no está cerrado), `not_played` (cerrado sin juego, como un W.O.) o `available`. `score_consistent` indica si los goles registrados cuadran con el marcador.
- **`profile_available`:** indica si existe la ficha pública de ese jugador.

## Autenticación y CORS

- **Sin autenticación:** no hay claves, cookies ni cabeceras propias. No envíes `Authorization`, `X-Organization-ID` ni cookies.
- **CORS:** un navegador puede llamar a estas lecturas desde cualquier origen. La respuesta lleva `Access-Control-Allow-Origin: *` y nunca `Access-Control-Allow-Credentials`. Solo se admite `GET` y su comprobación previa (`OPTIONS`), y solo con cabeceras simples como `Accept` o `Accept-Language`.
- **Resto de la API:** el Workspace, la autenticación, la plataforma y las imágenes para compartir no forman parte de esta API y no aceptan otros orígenes.

## Paginación y filtros

Las listas se paginan con `limit` y `offset`. Para recorrer una lista completa, aumenta `offset` en `limit` hasta recibir menos de `limit` elementos. `stage_id` y `group_id` filtran por fase y grupo del mismo torneo.

## Idioma de los textos

- Los nombres de torneos, fases, grupos, equipos y jugadores salen tal como los escribió la organización, sin traducir.
- Los valores de los campos enumerados (`status`, `event_type`, `stage_type`…) son identificadores en inglés y no cambian con el idioma.
- El mensaje del 404 está en español. Los mensajes del 422 los genera el validador y están en inglés.

## Errores

| Código | Cuándo | Cuerpo |
|---|---|---|
| 404 | El torneo, partido o jugador no existe o no es público. Las dos situaciones son idénticas: no se puede saber si existe algo no publicado. | `{"detail": "Torneo público no encontrado"}` |
| 422 | Un identificador no es un UUID, o `limit`, `offset`, `stage_id` o `group_id` no son válidos. | `{"detail": [{"loc": […], "msg": "…", "type": "…"}]}` |
| 429 | Se superó el límite de peticiones del proxy. | `{"detail": "Demasiadas peticiones"}`, con la cabecera `Retry-After` |

## Fotos y escudos

`photo_url` y `crest_url` son enlaces firmados que caducan a los pocos minutos (300 s por defecto). No los guardes: vuelve a pedir la lectura para obtener un enlace nuevo. Valen `null` si no hay imagen o, en las fotos, si el jugador no dio su consentimiento de imagen.

## Límite de peticiones

El proxy limita cada IP a 120 peticiones por minuto, con ráfagas de hasta 60 peticiones. Al superarlo responde 429 con `Retry-After`, en segundos. Espera ese tiempo antes de repetir y guarda en caché lo que no cambia a menudo. El despliegue puede ajustar estas cifras; la configuración está en `docs/despliegue-proxy-tiempo-real.md`.

## Política de versiones

- `v1` es estable. Dentro de `v1` solo hay cambios compatibles: lecturas nuevas, campos nuevos no obligatorios o valores nuevos en un parámetro opcional. Tu cliente debe ignorar los campos que no conozca.
- Un cambio incompatible, como quitar o renombrar un campo, cambiar su tipo o su significado, o devolver valores nuevos en un campo enumerado, solo puede llegar en una versión nueva (`v2`) con rutas propias.
- Una prueba automática compara cada cambio con la copia de referencia y rechaza los incompatibles. Cada cambio compatible se anota en el historial de abajo.

## Ejemplos

Las respuestas están abreviadas a uno o dos elementos. Los enlaces firmados están recortados con `…`.

### Listado de torneos

```sh
curl -s "https://torneos.example.org/api/v1/tournaments/public?limit=20"
```

<!-- ejemplo: list_tournaments -->
```json
[
  {
    "id": "3f6c2a9e-1b4d-4c8a-9e2f-5a7b8c9d0e1f",
    "name": "Copa Barrial 2026",
    "season": "2026",
    "start_date": "2026-03-07",
    "status": "published"
  }
]
```

### Detalle de un torneo

```sh
curl -s "https://torneos.example.org/api/v1/tournaments/public/3f6c2a9e-1b4d-4c8a-9e2f-5a7b8c9d0e1f"
```

<!-- ejemplo: tournament -->
```json
{
  "id": "3f6c2a9e-1b4d-4c8a-9e2f-5a7b8c9d0e1f",
  "name": "Copa Barrial 2026",
  "season": "2026",
  "start_date": "2026-03-07",
  "status": "published",
  "stages": [
    {
      "id": "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
      "name": "Fase de grupos",
      "stage_order": 1,
      "stage_type": "custom_group"
    }
  ],
  "teams": [
    {
      "team_id": "c3d4e5f6-a7b8-4c9d-8e0f-2a3b4c5d6e7f",
      "name": "Atlético Norte",
      "short_code": "ATN",
      "crest_url": "https://storage.example.org/crests/c3d4e5f6.png?X-Amz-Expires=300&X-Amz-Signature=…"
    },
    {
      "team_id": "d4e5f6a7-b8c9-4d0e-9f1a-3b4c5d6e7f80",
      "name": "Deportivo Sur",
      "short_code": "DSU",
      "crest_url": null
    }
  ]
}
```

### Clasificación

```sh
curl -s "https://torneos.example.org/api/v1/tournaments/public/3f6c2a9e-1b4d-4c8a-9e2f-5a7b8c9d0e1f/standings?group_id=b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e"
```

<!-- ejemplo: standings -->
```json
[
  {
    "tournament_id": "3f6c2a9e-1b4d-4c8a-9e2f-5a7b8c9d0e1f",
    "stage_id": "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
    "stage_name": "Fase de grupos",
    "stage_order": 1,
    "group_id": "b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e",
    "group_name": "Grupo A",
    "team_id": "c3d4e5f6-a7b8-4c9d-8e0f-2a3b4c5d6e7f",
    "team_name": "Atlético Norte",
    "short_code": "ATN",
    "crest_url": "https://storage.example.org/crests/c3d4e5f6.png?X-Amz-Expires=300&X-Amz-Signature=…",
    "rank": 1,
    "played": 3,
    "won": 2,
    "drawn": 1,
    "lost": 0,
    "goals_for": 7,
    "goals_against": 2,
    "goal_difference": 5,
    "points": 7,
    "fair_play_points": -3,
    "calculated_at": "2026-03-21T22:15:04Z"
  }
]
```

### Partidos

```sh
curl -s "https://torneos.example.org/api/v1/tournaments/public/3f6c2a9e-1b4d-4c8a-9e2f-5a7b8c9d0e1f/matches?stage_id=7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
```

<!-- ejemplo: matches -->
```json
[
  {
    "id": "e5f6a7b8-c9d0-4e1f-8a2b-4c5d6e7f8091",
    "tournament_id": "3f6c2a9e-1b4d-4c8a-9e2f-5a7b8c9d0e1f",
    "stage_id": "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
    "stage_name": "Fase de grupos",
    "stage_order": 1,
    "group_id": "b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e",
    "group_name": "Grupo A",
    "matchday": 3,
    "bracket_code": null,
    "match_date": "2026-03-21T20:00:00Z",
    "status": "finished",
    "home_team_id": "c3d4e5f6-a7b8-4c9d-8e0f-2a3b4c5d6e7f",
    "home_team_name": "Atlético Norte",
    "home_team_short_code": "ATN",
    "home_team_crest_url": "https://storage.example.org/crests/c3d4e5f6.png?X-Amz-Expires=300&X-Amz-Signature=…",
    "away_team_id": "d4e5f6a7-b8c9-4d0e-9f1a-3b4c5d6e7f80",
    "away_team_name": "Deportivo Sur",
    "away_team_short_code": "DSU",
    "away_team_crest_url": null,
    "home_score": 2,
    "away_score": 1,
    "home_score_regular": 2,
    "away_score_regular": 1,
    "home_penalties": null,
    "away_penalties": null,
    "winner_team_id": "c3d4e5f6-a7b8-4c9d-8e0f-2a3b4c5d6e7f",
    "resolution_type": null,
    "home_origin": null,
    "away_origin": null,
    "lineup": null,
    "rectified_at": null
  }
]
```

### Detalle de un partido (en vivo)

```sh
curl -s "https://torneos.example.org/api/v1/tournaments/public/3f6c2a9e-1b4d-4c8a-9e2f-5a7b8c9d0e1f/matches/e5f6a7b8-c9d0-4e1f-8a2b-4c5d6e7f8091"
```

<!-- ejemplo: match -->
```json
{
  "id": "e5f6a7b8-c9d0-4e1f-8a2b-4c5d6e7f8091",
  "tournament_id": "3f6c2a9e-1b4d-4c8a-9e2f-5a7b8c9d0e1f",
  "stage_id": "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
  "stage_name": "Fase de grupos",
  "stage_order": 1,
  "group_id": "b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e",
  "group_name": "Grupo A",
  "matchday": 3,
  "bracket_code": null,
  "match_date": "2026-03-21T20:00:00Z",
  "status": "live",
  "is_provisional": true,
  "clock_state": "running",
  "clock_segment_number": 2,
  "clock_elapsed_seconds": 3120,
  "clock_observed_at": "2026-03-21T21:07:30Z",
  "home_team_id": "c3d4e5f6-a7b8-4c9d-8e0f-2a3b4c5d6e7f",
  "home_team_name": "Atlético Norte",
  "home_team_short_code": "ATN",
  "home_team_crest_url": "https://storage.example.org/crests/c3d4e5f6.png?X-Amz-Expires=300&X-Amz-Signature=…",
  "away_team_id": "d4e5f6a7-b8c9-4d0e-9f1a-3b4c5d6e7f80",
  "away_team_name": "Deportivo Sur",
  "away_team_short_code": "DSU",
  "away_team_crest_url": null,
  "home_score": 1,
  "away_score": 1,
  "home_score_regular": null,
  "away_score_regular": null,
  "home_penalties": null,
  "away_penalties": null,
  "winner_team_id": null,
  "resolution_type": null,
  "home_origin": null,
  "away_origin": null,
  "lineup": null,
  "rectified_at": null
}
```

### Cronología de un partido

```sh
curl -s "https://torneos.example.org/api/v1/tournaments/public/3f6c2a9e-1b4d-4c8a-9e2f-5a7b8c9d0e1f/matches/e5f6a7b8-c9d0-4e1f-8a2b-4c5d6e7f8091/timeline"
```

<!-- ejemplo: timeline -->
```json
{
  "match_id": "e5f6a7b8-c9d0-4e1f-8a2b-4c5d6e7f8091",
  "availability": "available",
  "score_consistent": true,
  "segment_numbers": [
    1,
    2
  ],
  "events": [
    {
      "event_type": "goal",
      "segment_number": 1,
      "minute": 23,
      "added_minute": 0,
      "team_id": "c3d4e5f6-a7b8-4c9d-8e0f-2a3b4c5d6e7f",
      "beneficiary_team_id": "c3d4e5f6-a7b8-4c9d-8e0f-2a3b4c5d6e7f",
      "player": {
        "player_id": "f6a7b8c9-d0e1-4f2a-9b3c-5d6e7f8091a2",
        "first_name": "Laura",
        "last_name": "Gómez",
        "profile_available": true
      },
      "player_in": null,
      "red_card_type": null
    },
    {
      "event_type": "yellow_card",
      "segment_number": 2,
      "minute": 45,
      "added_minute": 2,
      "team_id": "d4e5f6a7-b8c9-4d0e-9f1a-3b4c5d6e7f80",
      "beneficiary_team_id": null,
      "player": {
        "player_id": "0a1b2c3d-4e5f-4061-8a7b-8c9d0e1f2a3b",
        "first_name": "Marta",
        "last_name": "Ríos",
        "profile_available": false
      },
      "player_in": null,
      "red_card_type": null
    }
  ]
}
```

### Estadísticas de jugadores

```sh
curl -s "https://torneos.example.org/api/v1/tournaments/public/3f6c2a9e-1b4d-4c8a-9e2f-5a7b8c9d0e1f/player-stats?limit=10"
```

<!-- ejemplo: player_stats -->
```json
[
  {
    "rank": 1,
    "player_id": "f6a7b8c9-d0e1-4f2a-9b3c-5d6e7f8091a2",
    "first_name": "Laura",
    "last_name": "Gómez",
    "team_id": "c3d4e5f6-a7b8-4c9d-8e0f-2a3b4c5d6e7f",
    "team_name": "Atlético Norte",
    "photo_url": "https://storage.example.org/players/f6a7b8c9.jpg?X-Amz-Expires=300&X-Amz-Signature=…",
    "profile_available": true,
    "matches_played": 3,
    "goals": 4,
    "yellow_cards": 1,
    "red_cards": 0,
    "clean_sheets": 0
  }
]
```

### Estadísticas de equipos

```sh
curl -s "https://torneos.example.org/api/v1/tournaments/public/3f6c2a9e-1b4d-4c8a-9e2f-5a7b8c9d0e1f/team-stats"
```

<!-- ejemplo: team_stats -->
```json
[
  {
    "rank": 1,
    "team_id": "c3d4e5f6-a7b8-4c9d-8e0f-2a3b4c5d6e7f",
    "team_name": "Atlético Norte",
    "short_code": "ATN",
    "crest_url": "https://storage.example.org/crests/c3d4e5f6.png?X-Amz-Expires=300&X-Amz-Signature=…",
    "goals_for": 7,
    "goals_against": 2,
    "clean_sheets": 1,
    "fair_play_points": -3
  }
]
```

### Ficha de jugador

```sh
curl -s "https://torneos.example.org/api/v1/tournaments/public/players/f6a7b8c9-d0e1-4f2a-9b3c-5d6e7f8091a2"
```

<!-- ejemplo: player_profile -->
```json
{
  "player_id": "f6a7b8c9-d0e1-4f2a-9b3c-5d6e7f8091a2",
  "first_name": "Laura",
  "last_name": "Gómez",
  "photo_url": "https://storage.example.org/players/f6a7b8c9.jpg?X-Amz-Expires=300&X-Amz-Signature=…",
  "totals": {
    "matches_played": 8,
    "goals": 9,
    "yellow_cards": 2,
    "red_cards": 0,
    "clean_sheets": 0
  },
  "tournaments": [
    {
      "tournament_id": "3f6c2a9e-1b4d-4c8a-9e2f-5a7b8c9d0e1f",
      "tournament_name": "Copa Barrial 2026",
      "team_id": "c3d4e5f6-a7b8-4c9d-8e0f-2a3b4c5d6e7f",
      "team_name": "Atlético Norte",
      "matches_played": 3,
      "goals": 4,
      "yellow_cards": 1,
      "red_cards": 0,
      "clean_sheets": 0
    },
    {
      "tournament_id": "1b2c3d4e-5f60-4172-8b9c-0d1e2f3a4b5c",
      "tournament_name": "Liga Distrital 2025",
      "team_id": "c3d4e5f6-a7b8-4c9d-8e0f-2a3b4c5d6e7f",
      "team_name": "Atlético Norte",
      "matches_played": 5,
      "goals": 5,
      "yellow_cards": 1,
      "red_cards": 0,
      "clean_sheets": 0
    }
  ]
}
```

## Historial de cambios

- **2026-11-27** · `v1` · Primera versión: 9 lecturas, documento OpenAPI y CORS para cualquier origen (spec 051).
