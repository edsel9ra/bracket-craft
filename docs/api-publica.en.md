# Bracket Craft public API (`v1`)

Guide for third parties who want to show tournaments published on Bracket Craft on their own website or app. The API is read-only: it returns the same data any visitor of the public site sees, with no identity documents or dates of birth, and player photos only when image consent was given.

Spanish version: [api-publica.md](api-publica.md).

## Base URL and OpenAPI document

- **Base URL:** the site domain followed by `/api/v1`, for example `https://torneos.example.org/api/v1`.
- **OpenAPI 3.1 document:** `GET /api/v1/public/openapi.json`. It only describes the 9 reads in this guide and is the exact reference for every field.
- **Reference copy in the repository:** `docs/api-publica/openapi-v1.json`.

## Reads

| Read | Path | Query parameters |
|---|---|---|
| Tournament list | `GET /api/v1/tournaments/public` | `limit` (1–200, default 100), `offset` |
| Tournament detail | `GET /api/v1/tournaments/public/{tournament_id}` | — |
| Standings | `GET /api/v1/tournaments/public/{tournament_id}/standings` | `stage_id`, `group_id`, `limit` (1–500, 200), `offset` |
| Matches | `GET /api/v1/tournaments/public/{tournament_id}/matches` | `stage_id`, `group_id`, `limit` (1–500, 200), `offset` |
| Match detail | `GET /api/v1/tournaments/public/{tournament_id}/matches/{match_id}` | — |
| Match timeline | `GET /api/v1/tournaments/public/{tournament_id}/matches/{match_id}/timeline` | — |
| Player statistics | `GET /api/v1/tournaments/public/{tournament_id}/player-stats` | `stage_id`, `group_id`, `limit` (1–500, 200), `offset` |
| Team statistics | `GET /api/v1/tournaments/public/{tournament_id}/team-stats` | `stage_id`, `group_id`, `limit` (1–500, 200), `offset` |
| Player profile | `GET /api/v1/tournaments/public/players/{player_id}` | — |

All identifiers are UUIDs. All responses are `application/json`.

- **Matches:** each match has a shape that depends on `status`. `live` adds the clock and `is_provisional: true`; `suspended` only has 14 keys (teams, provisional score and clock). The others (`scheduled`, `finished`, `cancelled`, `administrative_resolution`) use the full shape.
- **Timeline:** `availability` is `pending` (the match is not closed yet), `not_played` (closed without play, such as a walkover) or `available`. `score_consistent` tells whether the recorded goals match the score.
- **`profile_available`:** tells whether that player has a public profile.

## Authentication and CORS

- **No authentication:** there are no keys, cookies or custom headers. Do not send `Authorization`, `X-Organization-ID` or cookies.
- **CORS:** a browser can call these reads from any origin. The response carries `Access-Control-Allow-Origin: *` and never `Access-Control-Allow-Credentials`. Only `GET` and its preflight (`OPTIONS`) are allowed, and only with simple headers such as `Accept` or `Accept-Language`.
- **Rest of the API:** the Workspace, authentication, the platform and the share images are not part of this API and do not accept other origins.

## Pagination and filters

Lists are paginated with `limit` and `offset`. To walk a whole list, increase `offset` by `limit` until you receive fewer than `limit` items. `stage_id` and `group_id` filter by stage and group of the same tournament.

## Language of texts

- Names of tournaments, stages, groups, teams and players are returned as the organization wrote them, untranslated.
- Values of enumerated fields (`status`, `event_type`, `stage_type`…) are English identifiers and do not change with the language.
- The 404 message is in Spanish. 422 messages come from the validator and are in English.

## Errors

| Code | When | Body |
|---|---|---|
| 404 | The tournament, match or player does not exist or is not public. Both cases are identical: you cannot tell whether something unpublished exists. | `{"detail": "Torneo público no encontrado"}` |
| 422 | An identifier is not a UUID, or `limit`, `offset`, `stage_id` or `group_id` are not valid. | `{"detail": [{"loc": […], "msg": "…", "type": "…"}]}` |
| 429 | The proxy rate limit was exceeded. | `{"detail": "Demasiadas peticiones"}`, with the `Retry-After` header |

## Photos and crests

`photo_url` and `crest_url` are signed links that expire after a few minutes (300 s by default). Do not store them: request the read again to get a fresh link. They are `null` when there is no image or, for photos, when the player did not give image consent.

## Rate limit

The proxy limits each IP to 120 requests per minute, with bursts of up to 60 requests. Above that it answers 429 with `Retry-After`, in seconds. Wait that long before retrying, and cache what does not change often. A deployment can tune these figures; the configuration is in `docs/despliegue-proxy-tiempo-real.md`.

## Versioning policy

- `v1` is stable. Within `v1` there are only compatible changes: new reads, new optional fields or new values in an optional parameter. Your client must ignore fields it does not know.
- An incompatible change, such as removing or renaming a field, changing its type or meaning, or returning new values in an enumerated field, can only arrive in a new version (`v2`) with its own paths.
- An automated test compares every change with the reference copy and rejects incompatible ones. Every compatible change is recorded in the changelog below.

## Examples

Responses are shortened to one or two items. Signed links are cut with `…`.

### Tournament list

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

### Tournament detail

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

### Standings

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

### Matches

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

### Match detail (live)

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

### Match timeline

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

### Player statistics

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

### Team statistics

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

### Player profile

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

## Changelog

- **2026-11-27** · `v1` · First version: 9 reads, OpenAPI document and CORS for any origin (spec 051).
