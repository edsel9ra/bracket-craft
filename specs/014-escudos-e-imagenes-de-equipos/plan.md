# Plan 014 — Escudos e imágenes de equipos

Spec de referencia: `specs/014-escudos-e-imagenes-de-equipos/spec.md` (aprobada).
Constitución aplicable: `docs/constitution.md` v1.4.0.

## 1. Alcance técnico y resultado

Una persona con `MANAGE_TOURNAMENTS` de la organización carga, reemplaza y elimina
**una** imagen por equipo desde el torneo donde el equipo está inscrito. La imagen
vive en el almacenamiento privado existente (SeaweedFS/S3) y se sirve **solo** por
enlace temporal. El Workspace y las superficies públicas la muestran en un campo
aditivo `crest_url`; `logo_url` conserva su significado y queda en `null` desde la
primera carga confirmada.

No se añade ninguna dependencia, ninguna variable de configuración, ningún evento
de outbox ni ninguna pantalla nueva: se amplían la pantalla de equipos del torneo,
la operación del partido y la página pública existentes.

## 2. Rama, numeración y orden de despliegue

- Rama `014-escudos-e-imagenes-de-equipos`, creada desde `main`. En `main` la
  última migración es la **023** (`023_stage_schedule_legs.sql`).
- La spec 013 (Google) está en el PR #10, pendiente de merge, y reserva la **024**:
  **no** está en `main` y este plan no da por presentes sus archivos.
- Esta spec reserva la **025**: `infra/postgres/migrations/025_team_crests.sql`.
  Comprobado que no existe `024*` ni `025*` ni en `main` ni en esta rama.
- **Orden de despliegue: 024 (PR #10) → 025 → código de la 014.**
  `infra/postgres/migrate.sh` aplica en orden numérico las migraciones no
  registradas; la 025 debe quedar **después** de la 024. Si esta rama llegara a
  `main` antes que el PR #10, la 025 se **renumera** en el merge: no se edita ni se
  desaplica ninguna migración ya aplicada.
- La 025 no depende de la 024 (no toca identidades, sesiones ni `users`).

## 3. Decisiones técnicas

| # | Decisión | Alternativa descartada | Motivo |
|---|----------|------------------------|--------|
| D-1 | La referencia se guarda en `teams.crest_object_key TEXT` (una sola columna nueva). | `teams.crest_url` con una dirección permanente, o `crest_object_key` + `crest_content_type`. | `crest_url` contradeciría RF-37/RF-47/RNF-13 (el escudo nunca se sirve por dirección pública permanente). La columna de tipo es innecesaria: `put_object` ya declara el `ContentType` detectado y el enlace firmado lo devuelve; la extensión de la clave también sale del contenido. `crest_object_key` replica la convención existente `rosters.photo_object_key` y nombra lo que es: una clave de objeto, no una URL. |
| D-2 | La visibilidad pública del escudo se resuelve en **una vista nueva** `public.v_public_tournament_teams`, con `GRANT SELECT` a `bracket_app`. | (a) Añadir `crest_object_key` a `v_public_standings`, `v_public_matches` y `v_public_match_lineups_unpublished`; (b) `SECURITY DEFINER` en el router. | (a) obliga a reescribir tres vistas grandes y la interna `…_unpublished`, que además fue endurecida por la 013 por coincidencia de texto (riesgo de fallo silencioso); `CREATE OR REPLACE VIEW` solo admite columnas nuevas al final y la vista de alineaciones se compone con `raw.*`. (b) daría privilegios elevados al rol de aplicación y rompería la constitución §2.2. La vista nueva es aditiva, mide ~30 líneas, reutiliza el patrón `security_barrier` de las proyecciones existentes y sirve a las **cuatro** superficies públicas (detalle, clasificación, partidos y alineaciones). |
| D-3 | Módulo propio `backend/app/modules/crests/`, con su router registrado en `main.py` (prefijo `/tournaments`, rutas `/{tournament_id}/teams/{team_id}/crest`). | Colocar todo dentro de `backend/app/modules/tournaments/` (como la foto de roster). | Constitución §3.2: «cada funcionalidad vive en su propio módulo». El ciclo de vida (validación por contenido, N-2, compensación, huérfano, auditoría) es lo bastante específico para tener módulo y pruebas propias; el módulo de torneos ya es el más grande del backend. Precedente de importación cruzada: `matches/router.py` importa `tournaments/roster_status.py`; aquí las superficies importan `crests/resolver.py`. |
| D-4 | `POST` responde **200** siempre (primera carga y reemplazo) con el cuerpo `TeamCrestResponse`; `DELETE` responde **204**; `GET` responde **200**. | `POST` 201 en la primera carga y 200 en el reemplazo. | RF-13/RF-14 piden el mismo resultado con y sin imagen previa; distinguir 201/200 obligaría al cliente a ramificar y expondría si el equipo ya tenía imagen, información que la spec no pide. No hay estado de conflicto: por eso esta funcionalidad **no** usa 409. |
| D-5 | Serialización de la escritura con `SELECT … FOR UPDATE OF t` sobre la fila de `teams` en la **transacción de escritura** (no en la lectura previa). Desempate: última escritura confirmada gana. | Bloqueo optimista con `updated_at`/versión; bloqueo de `tournament_teams`; unicidad parcial. | El lock pesimista sobre el equipo deja el orden «leer anterior → escribir clave» atómico y evita que dos cargas dejen una referencia a un archivo borrado. Un bloqueo optimista exigiría reintentos (RNF-14 prohíbe reintentos automáticos) y una columna de versión nueva. |
| D-6 | Un único primitivo de firma en lote por respuesta, `sign_media_rows(groups, policy=…)`, en `crests/resolver.py`; `sign_photo_rows` se conserva para las respuestas que solo llevan fotos. | Extender `sign_photo_rows` con un segundo campo de clave. | RNF-5 exige **una** preparación de enlaces por respuesta; la respuesta de partidos públicos lleva fotos y escudos. Un segundo campo dentro de `photos.py` metería escudos en el módulo de fotos y ensuciaría su contrato ya probado. |
| D-7 | El detalle público **añade** `teams: [{team_id, name, short_code, crest_url}]` a `PublicTournamentResponse`. | Mostrar el escudo solo en clasificación y partidos. | RF-47 nombra el «detalle público del torneo» como superficie propia: un torneo eliminatorio recién publicado no tiene clasificación y puede no tener partidos, y entonces ningún escudo sería visible. El campo es aditivo (RNF-10) y sale de la misma vista pública; no añade `logo_url`, documentos, edades ni fechas. |
| D-8 | El sustituto de iniciales y la precedencia `escudo > logo_url > iniciales` se implementan en el **frontend** como funciones puras. | Devolver desde la API un campo «qué mostrar». | RF-4 distingue superficie (Workspace/público) y RF-18 depende de un fallo de carga del navegador, que el servidor no puede observar. La API solo publica datos (`crest_url`, `logo_url`); la regla se prueba con `node --test`. |
| D-9 | La firma de enlaces ocurre **después** de cerrar la transacción en las tres superficies del Workspace y en las públicas (N-2). | Firmar dentro del `async with db.begin()`. | RNF-4 y la regla ya vigente en `photos.py`: no se deja la conexión inactiva en transacción mientras se firma. |
| D-10 | La validación del contenido no decodifica: se recorre el contenedor. | Usar Pillow/`imghdr`/`filetype`. | RNF-2 prohíbe dependencias de procesamiento y RF-34/RF-35 declaran que una animación o un truncamiento que solo se manifiestan al decodificar **no** se detectan. Un recorrido de bloques propio es auditable y sin dependencias. |

## 4. Archivos y responsabilidades

### 4.1 Base de datos

| Archivo | Responsabilidad |
|---------|-----------------|
| `infra/postgres/migrations/025_team_crests.sql` (nuevo) | Añade `teams.crest_object_key TEXT` y crea `public.v_public_tournament_teams` con `GRANT SELECT` a `bracket_app`. No toca `init/01` ni `init/02`. |
| `backend/tests/test_migration_025.py` (nuevo, opt-in) | Forma de la columna, privilegios heredados, RLS, visibilidad de la vista, cadena limpia vs. migrada. |

### 4.2 Backend — módulo nuevo `backend/app/modules/crests/`

| Archivo | Responsabilidad |
|---------|-----------------|
| `__init__.py` (nuevo) | Paquete. |
| `errors.py` (nuevo) | `CrestError(HTTPException)` con `status_code`, `detail` (cadena) y `code` aditivo; constantes de los ocho códigos del catálogo de la spec y sus textos en español; `crest_error_body(exc)`. |
| `validation.py` (nuevo) | Funciones puras: `detect_image_type`, `png_declares_animation`, `webp_declares_animation`, `validate_crest_content`, `crest_object_key`. Dataclass `CrestFile(content, content_type, extension)`. |
| `audit.py` (nuevo) | `crest_audit_action(before, after)` (puro), `SET_TEAM_CREST`/`REMOVE_TEAM_CREST`, `record_crest_audit(db, …)` (INSERT dentro de la transacción del llamador). |
| `resolver.py` (nuevo) | `MediaGroup` (rows, `key_field`, `value_field`, `consent_field`), `sign_media_rows(groups, policy, storage, logger)` (un solo lote por respuesta, quita la clave de la fila) y `sign_crest_rows(...)` como envoltorio. Política `null` (público) / `error` (Workspace, 503 con `CREST_STORAGE_UNAVAILABLE`). |
| `service.py` (nuevo) | Orquestación de `read_crest`, `load_crest` (carga y reemplazo comparten camino) y `delete_crest`: resolución del equipo y la inscripción, transacción de escritura con `FOR UPDATE`, retirada de `logo_url`, auditoría, borrado posterior al commit, compensación. |
| `router.py` (nuevo) | `APIRouter(prefix="/tournaments", tags=["crests"])` con `GET`, `POST` (multipart) y `DELETE`. |

| Archivo existente | Cambio |
|-------------------|--------|
| `backend/app/main.py` | Importa `crests_router`, lo registra con `api.include_router(crests_router, prefix="/api/v1")` y registra `api.add_exception_handler(CrestError, _coded_exception_handler)`. El manejador actual `_coded_conflict_exception_handler` se generaliza para servir a cualquier estado (no solo 409) manteniendo `{"detail": str, "code": str}`. |
| `backend/app/modules/tournaments/schemas.py` | `TournamentTeamSummaryResponse` añade `crest_url: str | None = None`; nuevos `TeamCrestResponse` y `PublicTournamentTeamResponse`; `PublicTournamentResponse` añade `teams`; `PublicStandingResponse`, `PublicMatchResponse` y `PublicTeamLineupResponse` añaden los campos de escudo. |
| `backend/app/modules/tournaments/router.py` | `GET /{tournament_id}/teams` selecciona `t.crest_object_key`, sale de la transacción y firma (`policy="error"`); `GET /public/{tournament_id}` devuelve `teams`; `public_standings` y `public_matches` integran la vista nueva y firman en un solo lote (`policy="null"`). |
| `backend/app/modules/matches/router.py` | `_load_operation_match` selecciona `ht.crest_object_key`/`at.crest_object_key` y `ht.logo_url`/`at.logo_url`; `get_match_operation` firma tras cerrar la transacción y deja `match.home_team_crest_url`/`away_team_crest_url` y `match.home_team_logo_url`/`away_team_logo_url` (respaldo del Workspace), sin las claves internas. |

### 4.3 Frontend

| Archivo | Responsabilidad |
|---------|-----------------|
| `frontend/app/utils/teamCrest.ts` (nuevo) | Puro y sin DOM: `teamInitials(name, shortCode)`, `crestSource({crestUrl, logoUrl, surface})` → `'crest' \| 'logo' \| 'initials'`, `CREST_ERROR_CODES`, `crestErrorMessageKey(code)`. |
| `frontend/app/components/TeamCrest.vue` (nuevo) | Imagen con `alt` = nombre del equipo, sustituto de iniciales con `aria-hidden` cuando no hay fuente o la carga falla, sin reintento automático. |
| `frontend/app/pages/workspace/tournaments/[id]/index.vue` | Cada equipo del panel `#equipos` muestra `TeamCrest` y, con permiso de gestión, el control de archivo con etiqueta, «Cargar»/«Reemplazar» y «Eliminar», estado de espera y error asociados; actualiza la fila en sitio. |
| `frontend/app/pages/workspace/matches/[id].vue` | Escudo de los dos equipos en la cabecera; ninguna acción de escritura. |
| `frontend/app/pages/tournaments/[id].vue` | Escudo en clasificación, tarjetas de partido, diálogo de alineaciones y lista de equipos del torneo; nunca `logo_url`. |
| `frontend/app/composables/useI18n.ts` | Claves nuevas en español e inglés (paridad). |
| `frontend/tests/team-crest.test.ts` (nuevo) | Iniciales, precedencia, mapeo de códigos. `frontend/tests/labels.test.ts` barrerá las claves nuevas sin cambios. |

### 4.4 Documentación

| Archivo | Cambio |
|---------|--------|
| `README.md` | Sección nueva de escudos (endpoints, límites compartidos con fotos, validación declarada, migración 025 y orden 024 → 025 → código, riesgos aceptados). |
| `AGENTS.md` | Contrato de endpoints de escudo, campos exactos, códigos, migración 025 y su orden, «escudo sin consentimiento» y por qué, límites declarados (metadatos, truncamiento, animación), y que el escudo no emite eventos. |
| `docs/runbook-despliegue-025.md` (nuevo, opcional) | Ventana de despliegue, pre/comprobaciones y smoke, siguiendo el formato de `docs/runbook-despliegue-019-023.md`. |

## 5. Funciones puras

Ninguna lee el reloj, la configuración global, la red ni la base de datos; el
tamaño máximo, el TTL y los identificadores entran como parámetros.

**Backend (`crests/validation.py`, `crests/audit.py`)**

| Función | Firma | Contrato |
|---------|-------|----------|
| `detect_image_type` | `(content: bytes) -> str \| None` | Devuelve la **extensión** detectada por la firma: `.jpg` (JPEG `FF D8 FF`), `.png` (PNG `89 50 4E 47 0D 0A 1A 0A`) o `.webp` (`RIFF` + `WEBP` en 8..12). El `content_type` (`image/jpeg`, `image/png`, `image/webp`) lo resuelve la tabla interna de `validate_crest_content`. Cualquier otro contenido —incluidos `GIF87a`/`GIF89a`, `<svg`, `<?xml` y HTML— devuelve `None`. |
| `png_declares_animation` | `(content: bytes) -> bool` | `True` si aparece un bloque `acTL` antes del primer `IDAT`; `False` si llega a `IDAT`/`IEND` sin `acTL` o si el recorrido no puede completarse (el archivo se acepta y el riesgo queda declarado). |
| `webp_declares_animation` | `(content: bytes) -> bool` | `True` si el bloque `VP8X` tiene el bit de animación (`0x02`) o si existe un bloque `ANIM`; `False` si recorre todos los bloques sin encontrarlos o si el recorrido no puede completarse (el archivo se acepta y el riesgo queda declarado). |
| `validate_crest_content` | `(content: bytes, *, max_bytes: int) -> CrestFile` | Orden: vacío → `CREST_FILE_EMPTY`; `len(content) > max_bytes` → `CREST_TOO_LARGE`; `detect_image_type` nulo → `CREST_FORMAT_UNSUPPORTED`; animación detectada → `CREST_ANIMATION_UNSUPPORTED`; un contenedor ilegible se acepta y se declara el riesgo. Devuelve `CrestFile(content, content_type, extension)` con el tipo derivado del contenido. |
| `crest_object_key` | `(organization_id: UUID, tournament_id: UUID, team_id: UUID, extension: str, *, token: str \| None = None) -> str` | `private/organizations/{org}/tournaments/{tournament_id}/teams/{team_id}/{token}{extension}`; `extension` es la derivada del contenido (solo `.jpg`, `.png` o `.webp`) y `token` es un `uuid4()` generado dentro (inyectable solo para pruebas), así que la clave no depende del reloj, del torneo ni del nombre elegido. Comprobado con `_is_valid_key` de `core/storage.py`. |
| `crest_audit_action` | `(before: str \| None, after: str \| None) -> str \| None` | `SET_TEAM_CREST` si `after` no es nulo (carga o reemplazo); `REMOVE_TEAM_CREST` si `before` no es nulo y `after` es nulo; `None` si ambos son nulos (eliminación sin imagen previa). |

**Frontend (`app/utils/teamCrest.ts`)**

| Función | Firma | Contrato |
|---------|-------|----------|
| `teamInitials` | `(name: string, shortCode: string) -> string` | `shortCode.trim()` con 2 o más caracteres → sus dos primeros en mayúsculas; con menos de 2 → los dos primeros de `name.trim()` en mayúsculas; si `name` tuviera 1 carácter, ese carácter. Nunca cadena vacía (nombre y código son obligatorios y no vacíos). |
| `crestSource` | `({crestUrl, logoUrl, surface}) -> 'crest' \| 'logo' \| 'initials'` | `crestUrl` → `'crest'`; sin escudo y `surface === 'workspace'` y `logoUrl` → `'logo'`; en `'public'` nunca `'logo'`; resto → `'initials'`. El fallo de carga de la imagen lo resuelve el componente y también termina en `'initials'`. |
| `crestErrorMessageKey` | `(code: unknown) -> string \| null` | Código del catálogo → clave i18n; código ausente o desconocido → `null` (el llamador usa `errorMessage`). |

## 6. Algoritmos

### 6.1 Validación de la imagen (RF-28…RF-37, RNF-1…RNF-3)

```
validate_crest_content(content, max_bytes):
    si content está vacío:                        → 422 CREST_FILE_EMPTY
    si len(content) > max_bytes:                  → 422 CREST_TOO_LARGE
    extension = detect_image_type(content)        # '.jpg' | '.png' | '.webp' | None
    si extension es nulo:                         → 422 CREST_FORMAT_UNSUPPORTED   # GIF/SVG/HTML
    content_type = tabla del tipo                 # image/jpeg | image/png | image/webp
    si extension == '.png':
        animado = png_blocks(content)
    si extension == '.webp':
        animado = webp_blocks(content)
    si animado:                                    → 422 CREST_ANIMATION_UNSUPPORTED
    # estructura ilegible: los helpers devuelven False, se acepta y se declara
    # el riesgo (RF-34, RNF-3)
    devolver CrestFile(content, content_type, extension)
```

```
png_blocks(content):
    pos = 8                                        # firma de 8 bytes
    mientras pos + 8 <= len(content):
        longitud = big_endian(content[pos : pos+4])
        tipo_bloque = content[pos+4 : pos+8]
        si tipo_bloque == 'acTL': devolver True     # animación declarada
        si tipo_bloque en {'IDAT', 'IEND'}: devolver False
        si pos + 12 + longitud > len(content): devolver False  # truncado: se acepta
        pos += 12 + longitud                        # longitud + tipo + CRC
    devolver False                                  # nunca llegó a IDAT: se acepta
```

```
webp_blocks(content):
    si content[0:4] != 'RIFF' o content[8:12] != 'WEBP': devolver False
    pos = 12
    mientras pos + 8 <= len(content):
        fourcc = content[pos : pos+4]; tamaño = little_endian(content[pos+4 : pos+8])
        si fourcc == 'ANIM': devolver True
        si fourcc == 'VP8X':
            flags = content[pos+8]                  # primer byte de la carga
            si flags & 0x02: devolver True          # bit de animación
        si pos + 8 + tamaño > len(content): devolver False
        pos += 8 + tamaño + (tamaño & 1)            # relleno a par
    devolver False
```

Se aceptan los metadatos tal como llegan y no se recorta, redimensiona, re-codifica
ni convierte (RF-37). El `ContentType` del objeto es el detectado (RF-36).

### 6.2 Carga y reemplazo (RF-12, RF-13, RF-19, RF-38…RF-42, RNF-4, RNF-14)

```
POST /tournaments/{tid}/teams/{team_id}/crest  (multipart 'file')
  1. contexto de organización y sesión        → ya resuelto por get_auth_context (RF-24, RF-25)
  2. transacción de lectura corta (antes de leer el archivo):
        set_rls_context(org, user)
        _ensure_tournament(org, tid)                         → 404 «Torneo no encontrado»
        require_permission('MANAGE_TOURNAMENTS')             → 403 CREST_FORBIDDEN
        SELECT equipo inscrito en el torneo (teams ⋈ tournament_teams,
               org y tid)                                    → si no: 404 CREST_NOT_FOUND
        recordar logo_url y crest_object_key actuales
  3. leer el archivo con tope max_bytes + 1   → valida (6.1) SIN tocar BD ni almacenamiento
  4. clave = crest_object_key(org, tournament_id, team_id, uuid4(), extension)
  5. FUERA de transacción: storage.put_bytes(clave, content, content_type)
        fallo → 503 CREST_STORAGE_UNAVAILABLE; nada escrito en BD (RF-39)
  6. transacción de escritura:
        set_rls_context(org, user)
        require_permission('MANAGE_TOURNAMENTS')             # se revalida
        SELECT t.id, t.crest_object_key, t.logo_url
          FROM teams t ⋈ tournament_teams tt
         WHERE … FOR UPDATE OF t                             # serializa (D-5)
        si no hay fila: lanzar  → compensa paso 7
        anterior = crest_object_key de la fila bloqueada
        UPDATE teams SET crest_object_key = clave, logo_url = NULL
         WHERE id = team_id AND organization_id = org         # RF-5
        si crest_audit_action(anterior, clave) no es nulo:
            INSERT administrative_audit_logs (SET_TEAM_CREST) # RF-45
        cuerpo_de_escritura_terminado = True
     confirmación implícita:
        commit_confirmado = True
  7. finally:
        si NO cuerpo_de_escritura_terminado:
            storage.delete_key(clave)                        # compensación (RF-41)
        si commit_confirmado y anterior != clave:
            intentar storage.delete_key(anterior):
                fallo → una línea de registro estable, la respuesta sigue siendo correcta,
                        el archivo queda huérfano, sin reintento (RF-40)
  8. FUERA de transacción: firmar la clave nueva (policy='error') → 200 {team_id, crest_url, logo_url: null}
```

Reglas del paso 7, copiadas del patrón ya probado de la foto de roster
(`upload_roster_player_photo`): un fallo **después** del final del cuerpo de
escritura es una confirmación ambigua; se conservan los dos archivos y no se borra
nada (RF-41, caso límite 21). Un fallo **antes** garantiza rollback y permite
compensar.

### 6.3 Eliminación (RF-14, RF-40, RF-46)

```
DELETE /tournaments/{tid}/teams/{team_id}/crest
  1. contexto → 2. transacción de lectura (mismo orden que 6.2) → anterior
  3. si anterior es nulo: devolver 204 sin transacción de escritura, sin borrado,
     sin llamada al almacenamiento y sin auditoría              # RF-14, RF-46
  4. transacción de escritura:
        SELECT … FOR UPDATE OF t
        anterior = crest_object_key de la fila bloqueada
        si anterior es nulo: 204 (idempotente, no audita)
        UPDATE teams SET crest_object_key = NULL WHERE …
        INSERT administrative_audit_logs (REMOVE_TEAM_CREST)     # cambio efectivo
     commit
  5. tras el commit: storage.delete_key(anterior)
        fallo → una línea de registro, 204 igualmente, huérfano declarado (RF-40)
```

`logo_url` **no** se restituye nunca (RF-7): la eliminación solo escribe
`crest_object_key = NULL`.

### 6.4 Firma en lote y degradación (RF-44, RNF-5, RNF-6)

```
sign_media_rows(groups, policy):
    claves = concatenar y deduplicar (respetando el orden) las claves válidas de
             todos los grupos (fotos y escudos de la MISMA respuesta)
    si no hay claves: asignar None y devolver
    resultado = storage.signed_urls(claves)                       # una sola llamada
    para cada grupo y fila: quitar el campo de clave y escribir value_field = url o None
    si hay claves fallidas:
        log.warning('No se pudieron firmar N enlaces (motivo)')    # una sola línea
        si policy == 'error': 503 CREST_STORAGE_UNAVAILABLE
        si policy == 'null':  la respuesta sigue siendo 200 con el campo en None
```

`policy='error'` en las tres superficies del Workspace (listado de equipos,
operación del partido, `GET`/`POST` de escudo); `policy='null'` en las cuatro
superficies públicas.

### 6.5 Concurrencia (RF-42, casos límite 6 y 7)

- Dos cargas: cada una sube su propia clave (nunca se comparte archivo, RF-8) y
  entra en la transacción de escritura; el `FOR UPDATE OF t` las serializa. La
  primera deja `clave1` y borra la anterior; la segunda lee `clave1` como anterior,
  escribe `clave2` y borra `clave1` al confirmar. Resultado: exactamente una
  referencia (`clave2`) y ningún archivo referenciado borrado.
- Carga y eliminación: la eliminación que llega segunda ve la clave nueva y la
  retira; la carga que llega segunda ve `NULL` y no borra archivo. Nunca queda una
  referencia a un archivo borrado.
- Si la segunda operación falla antes de confirmar, su archivo se compensa y la
  imagen de la primera sigue vigente.

### 6.6 Precedencia y sustituto (RF-4, RF-17, RF-18) — frontend

```
mostrar(equipo, superficie):
    estado = crestSource({crestUrl: equipo.crest_url, logoUrl: equipo.logo_url, surface: superficie})
    si estado == 'crest' y la imagen falla al cargar: estado = 'initials'   # sin reintento
    si estado == 'logo'  y la imagen falla al cargar: estado = 'initials'
    'initials' → teamInitials(equipo.name, equipo.short_code)
```

La nueva solicitud de enlace ocurre solo cuando la vista vuelve a pedir los datos:
no hay sondeo, ni reintento, ni corrección automática de la fila (RF-18, RF-43).

## 7. Interfaz exacta

### 7.1 Gestión del escudo (Workspace)

| Método y ruta | Cuerpo | Permiso | Respuesta |
|---|---|---|---|
| `GET /api/v1/tournaments/{tournament_id}/teams/{team_id}/crest` | — | membresía activa con al menos un rol activo (contexto) | `200 TeamCrestResponse`; `503 CREST_STORAGE_UNAVAILABLE` si falla la firma |
| `POST /api/v1/tournaments/{tournament_id}/teams/{team_id}/crest` | `multipart/form-data` con campo `file` | `MANAGE_TOURNAMENTS` | `200 TeamCrestResponse` (carga o reemplazo) |
| `DELETE /api/v1/tournaments/{tournament_id}/teams/{team_id}/crest` | — | `MANAGE_TOURNAMENTS` | `204` sin cuerpo (idempotente) |

`TeamCrestResponse`:

```json
{ "team_id": "…", "crest_url": "https://…firmado… | null", "logo_url": "https://externa | null" }
```

- `crest_url`: enlace temporal (TTL `STORAGE_PRESIGN_SECONDS`, 300 s por defecto);
  `null` cuando no hay imagen vigente. Nunca una dirección pública permanente.
- `logo_url`: la dirección externa heredada, `null` desde la primera carga
  confirmada y `null` tras eliminar.
- Nunca aparece `crest_object_key`, ni el tipo declarado, ni el tamaño, ni el
  nombre original del archivo.

Estados por endpoint:

| Estado | `GET` | `POST` | `DELETE` | Origen |
|---|---|---|---|---|
| 200 | sí | sí | — | consulta / carga / reemplazo |
| 204 | — | — | sí | eliminación, con o sin imagen previa |
| 400 | sí | sí | sí | falta `X-Organization-ID` o `Content-Length` inválido (código existente) |
| 403 | sí | sí | sí | `Membresía o rol activo no válido` (contexto, **sin** `code`) o `CREST_FORBIDDEN` (sin `MANAGE_TOURNAMENTS`) |
| 404 | sí | sí | sí | `Torneo no encontrado` (código existente) o `CREST_NOT_FOUND` (equipo inexistente, de otra organización o no inscrito en el torneo del contexto) |
| 409 | no | no | no | esta funcionalidad no tiene estado de conflicto (D-4) |
| 413 | — | sí | — | límite global del cuerpo, middleware de `main.py`, **antes** del manejador (fuera del catálogo de la spec, RF-30) |
| 422 | — | sí | — | `CREST_FILE_EMPTY`, `CREST_TOO_LARGE`, `CREST_FORMAT_UNSUPPORTED`, `CREST_ANIMATION_UNSUPPORTED`; también el 422 estándar de FastAPI si falta el campo `file` (sin `code` propio) |
| 500 | — | sí | — | `CREST_UPLOAD_FAILED` para un fallo no clasificado durante la operación (compensado antes de responder) |
| 503 | sí | sí | — | `CREST_STORAGE_UNAVAILABLE` (subida o preparación de enlaces); un borrado fallido del archivo anterior **no** es 503 (RF-40) |

Orden de validación (idéntico en las tres rutas): sesión y organización →
torneo (404) → permiso (403 `CREST_FORBIDDEN`) → equipo inscrito (404
`CREST_NOT_FOUND`) → lectura del archivo y validación (422) → almacenamiento.
Un rechazo en cualquier paso anterior al 5 no escribe en la base, no borra
objetos, no llama al almacenamiento y no audita (RF-22, RF-46, RNF-11).

### 7.2 Superficies del Workspace ya existentes

| Endpoint | Campo nuevo | Contenido |
|---|---|---|
| `GET /api/v1/tournaments/{id}/teams` | `crest_url` por fila (`TournamentTeamSummaryResponse`) | enlace firmado o `null`; el resto de campos no cambia; `logo_url` sigue ahí y pasa a `null` tras la primera carga |
| `GET /api/v1/matches/{id}/operation` | `match.home_team_crest_url`, `match.away_team_crest_url`, `match.home_team_logo_url`, `match.away_team_logo_url` | enlaces firmados o `null`; `home_team_logo_url`/`away_team_logo_url` son la dirección externa heredada que el Workspace usa como respaldo mientras no haya escudo (RF-4) y **nunca** se publican; `home_team_crest_object_key`/`away_team_crest_object_key` **no** se devuelven |

### 7.3 Superficies públicas

| Endpoint | Campos exactos | Ausencia |
|---|---|---|
| `GET /api/v1/tournaments/public/{id}` | `teams: [{team_id, name, short_code, crest_url}]` (aditivo, D-7) | `[]` si el torneo no tiene equipos inscritos; `crest_url: null` sin imagen |
| `GET /api/v1/tournaments/public/{id}/standings` | `crest_url` por fila | `null` |
| `GET /api/v1/tournaments/public/{id}/matches` | `home_team_crest_url`, `away_team_crest_url`; `lineup.home.crest_url`, `lineup.away.crest_url` | `null` |
| `GET /api/v1/tournaments/public` | sin cambios (un listado de torneos no muestra equipos) | — |

Condición de visibilidad: exactamente la de `v_public_tournaments` — versión
publicada (`status = 'published'`), torneo `published`/`live`/`finished` y
organización activa. Fuera de esa condición la vista no devuelve fila y el campo
sale `null`, indistinguible de un equipo sin imagen (RF-49).

Nunca en una respuesta pública: `logo_url`, `crest_object_key`, nombre de archivo,
tamaño, documentos, fecha de nacimiento ni edad. La clave interna solo viaja
**dentro** del enlace firmado, como en las fotos (RF-11, RF-51, RNF-13).

## 8. Base de datos — migración 025

`infra/postgres/migrations/025_team_crests.sql`, aditiva, un solo `BEGIN/COMMIT`:

```sql
ALTER TABLE public.teams ADD COLUMN crest_object_key TEXT;

CREATE VIEW public.v_public_tournament_teams
WITH (security_barrier = true) AS
SELECT DISTINCT
       tr.id AS tournament_id,
       t.id  AS team_id,
       t.name,
       t.short_code,
       t.crest_object_key
FROM public.tournament_teams tt
JOIN public.tournaments tr
  ON tr.id = tt.tournament_id AND tr.organization_id = tt.organization_id
JOIN public.organizations org
  ON org.id = tr.organization_id AND org.is_active = TRUE
JOIN public.tournament_versions tv
  ON tv.id = tr.published_version_id
 AND tv.organization_id = tr.organization_id
 AND tv.tournament_id = tr.id
 AND tv.status = 'published'
JOIN public.teams t
  ON t.id = tt.team_id AND t.organization_id = tt.organization_id
WHERE tr.status IN ('published', 'live', 'finished');

REVOKE ALL ON public.v_public_tournament_teams FROM PUBLIC;
GRANT SELECT ON public.v_public_tournament_teams TO bracket_app;
```

- **Columna.** `TEXT` nula, sin default: la ausencia de escudo es `NULL`. No se
  añade índice (se accede siempre por `teams.id`, ya es clave primaria) ni
  restricción de longitud (la clave la genera el sistema, no el usuario).
- **Privilegios.** `teams` ya tiene `GRANT SELECT, INSERT, UPDATE, DELETE` a
  `bracket_app` en `init/01`; no hace falta ningún grant por columna y **no** se
  toca `init/01`. La vista nueva necesita su propio `GRANT` (se concede aquí) y el
  `REVOKE` de `PUBLIC`, igual que las proyecciones existentes.
- **RLS.** `teams` ya es tabla tenant con su política y `FORCE ROW LEVEL SECURITY`
  del bucle de `init/01`; la columna la hereda. No se añade política. La vista es
  una proyección `security_barrier` propiedad del rol de migraciones, como
  `v_public_standings`/`v_public_matches`; el rol de aplicación no obtiene lectura
  de `teams` fuera de RLS ni de las proyecciones.
- **Pre-chequeo.** Ninguno: la columna es nueva y nula, y la vista se crea desde
  cero. No hay reescritura de datos ni `VALIDATE CONSTRAINT`.
- **Rollback.** No hay `down`: cualquier defecto se corrige con una migración nueva
  (*forward-fix*).
- **Verificación en volumen limpio:** `init/00-03` → `001`…`025` (el runner aplica
  en orden y salta las registradas) debe terminar con el mismo esquema que la
  cadena migrada.
- **Verificación en volumen migrado:** `023 → 024 → 025` cuando la 024 esté en
  `main`; mientras no lo esté, `023 → 025` sobre una base desechable. El test
  opt-in compara la instantánea de `teams` (columnas y restricciones) y de la vista
  entre ambas cadenas, igual que `test_migration_023.py`.
- **Orden de despliegue:** 024 → 025 → código. La imagen anterior no conoce la
  columna y sigue funcionando (es nula y no la selecciona); el código nuevo
  **falla** contra el esquema 023 si se despliega antes de la 025.

## 9. Backend

- **Módulo y registro.** `backend/app/modules/crests/router.py` con
  `APIRouter(prefix="/tournaments", tags=["crests"])`;
  `api.include_router(crests_router, prefix="/api/v1")` en `main.py` (junto a los
  seis routers existentes) y un `add_exception_handler(CrestError, …)` que conserva
  `{"detail": str, "code": str}` — el mismo formato que ya usan invitaciones y
  `ROSTER_SIZE_OUT_OF_RANGE`, generalizando el manejador actual a cualquier estado.
- **RLS.** Cada transacción (lectura y escritura) abre con
  `set_rls_context(db, context.organization_id, context.user_id)` **antes** de
  cualquier consulta tenant, y toda consulta filtra además por `organization_id`
  (RF-27, defensa en profundidad).
- **Pertenencia equipo ↔ torneo ↔ organización.** Una sola consulta:
  `teams t JOIN tournament_teams tt ON tt.team_id = t.id AND tt.organization_id = t.organization_id AND tt.tournament_id = :tid` con `t.id = :team_id AND t.organization_id = :org`. Sin fila: `CREST_NOT_FOUND` (404) idéntico para equipo inexistente, de otra organización y no inscrito (RF-23).
- **CSRF y origen.** No se añade nada: el middleware de `main.py` valida `Origin` y
  `Referer` por separado en toda escritura y el token doble CSRF llega por
  `useApi.ts` (RNF-15). El test verifica que un `Origin` no permitido responde 403
  antes del manejador y sin tocar el almacenamiento.
- **Lectura del archivo.** `await file.read(settings.storage_max_image_bytes + 1)`
  — el mismo patrón que la foto de roster: detecta el exceso aunque el cuerpo quepa
  en el límite global de 32 MiB.
- **Claves.** `private/organizations/{org}/tournaments/{tournament_id}/teams/{team}/crest/{uuid4}{ext}`; pasan
  `_is_valid_key` y no contienen nada del nombre original (RF-11, RF-36).
- **Errores.** `CrestError(status_code, code, detail)`; el detalle es una cadena en
  español (respaldo para clientes que ignoran `code`) y el frontend traduce por
  `code`. Ningún código incluye la referencia interna ni el nombre del archivo.
- **Registro.** `logger = logging.getLogger(__name__)`; un `warning` por respuesta
  cuando falla la firma o el borrado, sin claves, nombres, rutas ni contenido
  (RNF-6). Los rechazos de validación no registran nada.
- **Sin eventos.** No se publica nada en `outbox_events` (RF-54); el cambio se ve
  cuando la vista vuelve a pedir los datos.

## 10. Frontend

- **Pantalla de equipos** (`workspace/tournaments/[id]/index.vue`, panel
  `#equipos`): cada fila muestra `TeamCrest` + nombre + código corto. Con
  `canManageTournaments` se añade un `<input type="file" accept="image/jpeg,image/png,image/webp">` con `<label>` asociada (`for`/`id`), un botón «Cargar»/«Reemplazar»
  (el texto depende de si hay `crest_url` o `logo_url`) y «Eliminar» solo cuando hay
  `crest_url`. Sin permiso no se renderiza ningún control de escritura (RF-56).
- **Peticiones** por `useApi().request`: `FormData` con el campo `file` en `POST`
  (sin fijar `Content-Type`: lo pone el navegador), `DELETE` sin cuerpo. El error
  se traduce con `crestErrorMessageKey(code)` y, si falta el código, con
  `errorMessage(cause, t('crest.error.generic'))`.
- **Estados:** `busyTeamId` deshabilita los controles de ese equipo mientras dura la
  operación; `<p role="status">` anuncia «Cargando escudo…» / «Escudo actualizado»;
  el error va en un `<p role="alert" :id="…">` referenciado con
  `aria-describedby` desde el botón y el campo (RNF-8).
- **Actualización en sitio (RF-19):** con la respuesta se reemplaza la fila en
  `teams` (`crest_url`, `logo_url`) sin recargar la página ni perder versión
  seleccionada, asistentes ni borradores; tras `DELETE` se ponen ambos a `null`.
- **Operación del partido** (`workspace/matches/[id].vue`): `TeamCrest` junto a los
  dos nombres de la cabecera, sin controles (RF-16). Si falta la imagen o falla, se
  ven las iniciales.
- **Página pública** (`tournaments/[id].vue`): `TeamCrest` en las filas de
  clasificación, en las tarjetas de partido, en el diálogo de alineaciones y en la
  lista de equipos del torneo (D-7). La página no renderiza `logo_url` en ningún
  punto (RF-48).
- **Sin `?step=` nuevo:** no hay asistente; el estado de la operación vive en la
  página. No se añade nada a `sessionStorage` ni a `localStorage`.
- **i18n (RNF-9):** claves nuevas en `useI18n.ts` es/en, entre otras:
  `crest.load`, `crest.replace`, `crest.remove`, `crest.uploading`, `crest.updated`,
  `crest.removed`, `crest.alt` (`Escudo de {team}` / `{team} crest`),
  `crest.error.generic` y una por código (`crest.error.empty`, `.format`,
  `.animation`, `.tooLarge`, `.notFound`, `.forbidden`, `.storage`, `.failed`).
  `frontend/tests/labels.test.ts` barre las claves usadas y exige paridad, así que
  una clave sin traducción pone `pnpm test` en rojo.

## 11. Exposición pública y privacidad

- **Campos exactos** (los de §7.3): `crest_url` en clasificación y equipos del
  torneo; `home_team_crest_url`/`away_team_crest_url` en partidos;
  `crest_url` en la cabecera de cada alineación. Nada más.
- **Sin datos personales:** la vista pública solo lee `teams` (`name`,
  `short_code`, `crest_object_key`). No toca `players`, `rosters` ni
  `v_public_tournament_players`; no añade documentos, fecha de nacimiento ni edad
  (RF-51). La proyección existente de jugadores y el consentimiento de fotos no se
  modifican (RF-50, `test_public_player_views.py` debe seguir en verde).
- **`logo_url` nunca público** (RF-48): no se añade a ningún DTO público y la vista
  nueva no la expone; la página pública no la lee, así que no hay peticiones a
  terceros para mostrar el escudo.
- **Caducidad:** 300 s por defecto (`STORAGE_PRESIGN_SECONDS`, 60..3600). Un enlace
  emitido no es revocable; el objeto borrado deja de resolver en el acto (RF-52).
- **Fallo del almacenamiento:** Workspace 503; público con el campo a `null` y el
  resto de la respuesta intacto (RF-44).

## 12. Configuración y secretos

Se reutiliza todo lo existente; **no hay variables nuevas**:

| Variable | Uso en esta funcionalidad |
|---|---|
| `STORAGE_*` (`provider`, `endpoint_url`, `signing_endpoint_url`, `region`, `bucket`, claves) | subida, borrado y firma |
| `STORAGE_PRESIGN_SECONDS` | TTL del enlace (300 por defecto) |
| `STORAGE_MAX_IMAGE_BYTES` | tope del escudo, **compartido con las fotos de jugadores** (5 MiB por defecto) |
| `MAX_REQUEST_BODY_BYTES` | límite global del cuerpo (32 MiB por defecto), ajeno a esta spec |

No se añaden secretos ni defaults; `.env.example` no cambia. El cambio del tope de
imagen afecta a ambas funciones y se documenta en `README.md` y `AGENTS.md`
(RNF-1).

## 13. Auditoría

- Un `INSERT` en `administrative_audit_logs` **dentro de la transacción** que
  cambia la imagen: `entity_type = 'teams'`, `entity_id = team_id`,
  `action = 'SET_TEAM_CREST'` (carga o reemplazo) o `'REMOVE_TEAM_CREST'`
  (eliminación efectiva), `payload = {"tournament_id": "…"}`,
  `performed_by_member_id = context.organization_user_id`.
- Sin cambios efectivos no hay entrada: eliminación sobre un equipo sin imagen,
  segunda eliminación, rechazo por permiso, 404 o 422 (RF-46).
- Nunca en el `payload`: clave del objeto, nombre de archivo, contenido, tamaño,
  datos de jugadores (RNF-7).

## 14. Documentación

`README.md` (nueva sección «Escudos de equipo» + entrada de la migración 025 y su
orden), `AGENTS.md` (contrato de endpoints y campos, códigos, «el escudo no es dato
personal y no exige consentimiento», límites declarados —metadatos, truncamiento,
animación no detectada—, migración 025 y orden 024 → 025 → código, «los cambios de
escudo no emiten eventos y otras vistas no se refrescan»). El runbook de despliegue
se documenta como sección de `README.md` siguiendo el patrón 022/023; no se crea un
archivo aparte salvo que el usuario lo pida.

## 15. Estrategia de tests

| Nivel | Archivo | Contenido | RF |
|---|---|---|---|
| Unitario puro | `backend/tests/test_crest_validation.py` | JPEG/PNG/WEBP aceptados; extensión que no coincide; SVG, GIF y HTML rechazados por contenido; vacío; exceso de tamaño; APNG (`acTL` antes de `IDAT`) rechazado; `acTL` después de `IDAT` aceptado; WEBP con bit de animación en `VP8X` y con bloque `ANIM`; contenedor truncado/ilegible aceptado; clave sin el nombre elegido y válida para `_is_valid_key` | RF-28…RF-37, RNF-1…RNF-3 |
| Unitario puro | `backend/tests/test_crest_audit.py` | Acción por transición; `None` cuando no hay cambio | RF-45, RF-46, RNF-7 |
| Unitario con dobles | `backend/tests/test_crest_resolver.py` | Un solo lote por respuesta con fotos y escudos juntos, deduplicación, clave eliminada de la fila, política `null` vs `error`, una sola entrada de registro, sin transacción abierta (`session.in_transaction()` falso) | RF-44, RNF-4…RNF-6 |
| Endpoint con dobles | `backend/tests/test_crest_endpoints.py` | `httpx.ASGITransport` + `get_db`/`get_auth_context` sustituidos + `FakeStorage`: 200/204, códigos de 403/404/422/500/503, `logo_url` en `null` tras la carga, ninguna llamada al almacenamiento en 403/404/422, respuesta sin `crest_object_key`, `Origin` no permitido → 403 antes del manejador, multipart con campo `file` | RF-2, RF-12…RF-14, RF-20…RF-27, RF-38…RF-44, RNF-11, RNF-15 |
| Endpoint con dobles | `backend/tests/test_crest_surfaces.py` | `GET /tournaments/{id}/teams` y `GET /matches/{id}/operation`: `crest_url` firmado tras cerrar la transacción, un solo lote, 503 del Workspace, `logo_url` intacta hasta la primera carga y `null` después, ausencia de claves internas | RF-15, RF-16, RF-44, RNF-4 |
| Endpoint con dobles | `backend/tests/test_crest_public.py` | Detalle, clasificación, partidos y alineaciones: campos exactos, `null` sin imagen y con firma fallida (200, una sola entrada de registro), `logo_url` y `crest_object_key` ausentes, solo lectura de `v_public_tournament_teams` | RF-47…RF-49, RF-51, RF-52, RNF-13 |
| Opt-in PostgreSQL | `backend/tests/test_migration_025.py` | Forma de `teams.crest_object_key`; privilegios de `bracket_app` (hereda el grant de tabla); RLS (otra organización no ve la fila); la vista solo devuelve torneos visibles (borrador, sin versión publicada y organización inactiva fuera); cadena limpia vs. migrada | RF-38, RF-47, RF-49, RF-27 |
| Opt-in PostgreSQL | `backend/tests/test_crest_service.py` | Ciclo cargar → listar → reemplazar → eliminar con almacenamiento simulado: `logo_url` retirada en la primera carga, no restituida al eliminar, auditoría por cambio efectivo, fallo de subida deja la imagen anterior intacta, fallo de borrado deja huérfano y responde correctamente, dos cargas concurrentes dejan una referencia y ningún archivo referenciado borrado, eliminación sin imagen no llama al almacenamiento | RF-1, RF-5…RF-8, RF-12…RF-15, RF-45, RF-46 |
| Frontend | `frontend/tests/team-crest.test.ts` (`node --test`) | Iniciales (código de 2+, código de 1, nombre), precedencia por superficie, mapeo de códigos a claves y código desconocido | RF-4, RF-17, RF-18, RF-57 |
| Frontend | `frontend/tests/labels.test.ts` (existente) | Barrido de claves nuevas y paridad es/en | RNF-9 |

**No se automatiza** (comprobación manual documentada, criterio C de la spec):
la navegación real con teclado y el anuncio del lector de pantalla (RNF-8), la
carga de una imagen real en un navegador con su decodificación (RF-35, RF-37) y la
firma real contra SeaweedFS. Se declara como no ejecutado cuando no se haga.

Jobs de CI aplicables (`ci.yml`): `backend` (`pytest -q`, `compileall`), `frontend`
(`pnpm test`, `pnpm run typecheck`, `pnpm run build`), `infrastructure`
(`sh -n infra/postgres/migrate.sh`, `docker compose config -q`), `security`
(sin dependencias nuevas) y `e2e` (debe quedar en verde, aunque **no** cubre
escudos y no se declara como evidencia de esta funcionalidad).

## 16. Trazabilidad RF → partes y tareas

| RF | Parte del plan | Tarea |
|---|---|---|
| RF-1, RF-8 | §6.2 (clave por equipo con `uuid4`), §8 (columna en `teams`) | T7, T9 |
| RF-2, RF-3 | §7.1 (orden de validación), §9 (consulta de inscripción) | T6, T11 |
| RF-4, RF-17, RF-18 | §6.6, §10 (frontend) | T14, T16 |
| RF-5, RF-6, RF-7, RF-9, RF-10, RF-11 | §6.2/6.3, §7.1/7.2, §11 | T2, T5, T7, T8 |
| RF-12, RF-13, RF-14, RF-19 | §6.2, §6.3, §10 | T7, T8, T15 |
| RF-15, RF-16 | §7.2 | T12, T16 |
| RF-20…RF-27 | §7.1, §9 | T6, T11 |
| RF-28…RF-37 | §6.1 | T3 |
| RF-38…RF-44 | §6.2…§6.5, §8 | T1, T6, T7, T9, T12, T13 |
| RF-45, RF-46 | §13 | T4, T7, T8 |
| RF-47…RF-54 | §7.3, §11 | T1, T12, T13, T16 |
| RF-55, RF-56, RF-57 | §10 | T2, T14, T15 |
| RNF-1, RNF-2 | §6.1, §12 | T3 |
| RNF-3 | §6.1 | T3, T17 (documentación del límite) |
| RNF-4 | §6.2, §9 | T5, T6, T9 |
| RNF-5, RNF-6 | §6.4, §9 | T5, T13 |
| RNF-7 | §13 | T4 |
| RNF-8, RNF-9 | §10 | T14, T15, T16 |
| RNF-10 | §7.1…7.3 (todo aditivo) | T10, T12, T13 |
| RNF-11 | §7.1, §15 | T11 |
| RNF-12 | §15 | T18 |
| RNF-13, RNF-14, RNF-15 | §11, §12, §6.2, §9 | T8, T9, T11, T13 |

## 17. Verificación de la constitución

| Principio o criterio | Aplica | Cómo se cumple |
|----------------------|--------|----------------|
| §2.1 El aislamiento lo garantiza la base de datos | Sí | `teams` ya tiene RLS y `FORCE RLS`; la columna nueva la hereda (§8). La vista pública nueva es la única puerta de lectura y filtra por visibilidad pública. Las pruebas opt-in comprueban que otra organización no ve la fila. |
| §2.2 La aplicación no se salta RLS | Sí | El rol sigue siendo `bracket_app` sin `BYPASSRLS`; no se añade `SECURITY DEFINER` ni `GRANT` sobre `teams` (D-2, §8). |
| §2.3 Lo publicado es inmutable | Sí | El escudo no toca versiones, estructura ni resultados: la escritura solo actualiza `teams.crest_object_key`/`logo_url` fuera del ámbito de los triggers de estructura (RF-53). |
| §2.4 Historial de esquema append-only | Sí | Migración **025** nueva; no se edita ninguna aplicada. |
| §2.5 Lo público es una proyección mínima | Sí | §11: solo `crest_url`, sin documentos, fechas de nacimiento ni edad; `logo_url` no se publica; el consentimiento de fotos queda intacto (RF-50, RF-51). |
| §2.6 Ningún secreto por defecto fuera de desarrollo | Sí | §12: cero variables nuevas; `.env.example` no cambia. |
| §2.7 Administración global separada y auditada | Sí | Sin rutas nuevas en `/admin`; el escudo se audita en `administrative_audit_logs` (§13), no en `platform_audit_logs` (no es acción de plataforma). |
| §2.8 Nada se da por terminado sin verificación | Sí | T18 ejecuta los jobs aplicables y declara las pruebas opt-in no ejecutadas si no se corren. |
| §2.9 El código de desarrollo no llega a producción | Sí | No se añaden seeds ni scripts de desarrollo; no hay datos demo nuevos. |
| §3.1 `set_rls_context()` en la transacción | Sí | §9: en cada transacción, antes de cualquier consulta tenant. |
| §3.1 Migración nueva numerada | Sí | 025 (§8). |
| §3.2 Módulo propio + router en `main.py` | Sí | `backend/app/modules/crests/` registrado en `main.py` (§4.2, §9). |
| §3.2 Sustituciones/reglas como configuración | No aplica | No hay regla deportiva nueva. |
| §3.3 Frontend con `useApi.ts` | Sí | §10: todas las llamadas pasan por `useApi().request`. |
| §3.4 Defaults solo en `.env.example` | Sí | No hay defaults nuevos. |
| §3.5 Versiones de referencia | Sí | No cambian Python 3.14, Node 24 ni pnpm 12.12.1. |
| §4 Todos los cambios: CI aplicable | Sí | §15: `backend`, `frontend`, `infrastructure`, `security`; `e2e` en verde pero no evidencia. |
| §4 Todos: sin secretos ni datos personales | Sí | §11, §12, §13. |
| §4 Todos: documentación actualizada | Sí | §14 (`README.md`, `AGENTS.md`). |
| §4 Todos: pruebas del comportamiento nuevo | Sí | §15. |
| §4 Base de datos: nueva migración con el siguiente número | Sí | 025, tras la 024 reservada por el PR #10 (§2). |
| §4 Base de datos: RLS y políticas en tablas tenant nuevas | No aplica | No hay tabla nueva; la columna hereda política (§8). |
| §4 Base de datos: volumen limpio y migrado | Sí | §8 y `test_migration_025.py`. |
| §4 Base de datos: `sh -n infra/postgres/migrate.sh` | Sí | T18 (no se modifica el script). |
| §4 API: consultas tenant con `set_rls_context()` | Sí | §9. |
| §4 API: endpoints públicos sin campos sensibles | Sí | §11. |
| §4 API: router registrado en `main.py` | Sí | §9. |
| §4 API: `pytest -q` y `compileall` | Sí | T18. |
| §4 Frontend: HTTP por `useApi.ts` | Sí | §10. |
| §4 Frontend: `pnpm test`, `typecheck`, `build` | Sí | T18. |
| §4 Infraestructura: `docker compose config -q` | Sí | T18 (no cambian compose ni `.env`). |
| §4 Dependencias: lockfiles y auditorías | No aplica | Sin dependencias nuevas. |

## 18. Riesgos, límites declarados y lo que no se automatiza

- **Huérfanos** sin recolección ni cota si un borrado falla o la confirmación es
  ambigua (RF-40, RF-41). Se documenta; se corrigen a mano.
- **Animación y truncamiento no garantizados:** solo se detectan las marcas del
  contenedor; un archivo truncado con cabecera válida se acepta y se sirve
  (RF-34, RF-35). Se documenta en `README.md`/`AGENTS.md`.
- **Metadatos no eliminados:** se sirven tal cual, porque no se decodifica (RF-37).
- **Enlaces ya entregados:** dejan de resolver al borrar el objeto, salvo huérfano
  o caché externa; el sistema no revoca antes de la caducidad (RF-52).
- **`logo_url` en el Workspace** sigue exponiendo la IP del personal a un tercero
  mientras no haya escudo; nunca en público (riesgo aceptado en la spec).
- **Sin refresco en otras vistas** (RF-54): no hay eventos de escudo.
- **No automatizado:** teclado/lector de pantalla, imagen real en navegador y firma
  real contra SeaweedFS.

## 19. Puntos que requieren confirmación del usuario

Ninguno bloqueante: la spec no deja dudas abiertas y todas las decisiones de este
plan están dentro de sus requisitos. Se señalan dos elecciones que el usuario puede
querer revisar antes de implementar:

1. **D-7** (añadir `teams` al detalle público). Es la única interpretación que hace
   visible un escudo en un torneo eliminatorio sin clasificación ni partidos. Si se
   prefiere no ampliar `PublicTournamentResponse`, se elimina ese campo y el escudo
   se limita a clasificación, partidos y alineaciones.
2. **D-3** (módulo `crests` propio). Si se prefiere minimizar archivos, puede vivir
   en `modules/tournaments/`; el plan cambiaría solo las rutas de importación y la
   ubicación de los tests.
