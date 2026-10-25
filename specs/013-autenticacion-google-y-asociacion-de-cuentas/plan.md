# Plan 013 — Autenticación con Google y asociación de cuentas

**Spec:** `specs/013-autenticacion-google-y-asociacion-de-cuentas/spec.md` (aprobada).
**Estado del plan:** listo para tareas. No se implementa nada en esta fase.
**Migración nueva:** `infra/postgres/migrations/024_google_identity_uniqueness.sql`.

---

## 1. Alcance técnico y principios de diseño

Un **único** camino de Google: redirección con código de autorización, canje en el servidor y sesión entregada solo por la cookie existente. El camino anterior (`POST /auth/google` con un `access_token` presentado por el navegador) se **retira** con un rechazo estable.

Cinco invariantes gobiernan el diseño:

1. **La prueba de identidad nunca viaja por el navegador.** El navegador solo ve la dirección de autorización del proveedor; el código se canjea en el servidor y jamás se reenvía al cliente.
2. **El estado de un solo uso vive fuera de la transacción de datos.** Redis (ya dependencia de rate limit y outbox) guarda `estado → {flujo, destino, usuario, caducidad}` con TTL ≤ 600 s y consumo atómico; la base de datos no se toca hasta que la identidad está verificada.
3. **La identidad única la garantiza el almacenamiento.** La 024 añade `UNIQUE (user_id, provider)`; ninguna decisión se apoya en «comprobar y luego escribir».
4. **Autenticar no autoriza.** Ni el callback ni la pantalla de organización escriben membresías, roles ni organizaciones por defecto (salvo la organización explícita del paso opcional, con la función existente `create_organization_with_owner`).
5. **Lo que se escribe se decide en una función pura.** El reloj entra como parámetro en todas las piezas con lógica temporal; ninguna decisión lee `datetime.now()` dentro de la lógica de negocio (solo los adaptadores de borde: router y cliente del proveedor).

---

## 2. Requisitos → piezas (trazabilidad)

| RF / RNF | Pieza principal |
|---|---|
| RF-1 | `GET /auth/google/status`, guardas en `start` y `callback`, `Settings.google_oauth_enabled` |
| RF-2 | `google_provider.authorization_url()`, scope mínimo, sin tokens al navegador |
| RF-3 | Retiro de `POST /auth/google` (410 + `code`) y borrado de `GoogleLoginRequest` |
| RF-4 | `GOOGLE_REDIRECT_URI` fijo; `callback` solo lee `code`/`state`/`error` |
| RF-5 | `google_provider.exchange_code()` + `google_claims.parse_identity_claims()` |
| RF-6 | `google_state` (Redis, `GETDEL`, TTL 600 s, cookie de enlace de navegador) |
| RF-7 | Rama `error=access_denied` del callback (`GOOGLE_CANCELLED`) |
| RF-8 | `parse_identity_claims` (correo verificado, correo y sujeto presentes) |
| RF-9 | `google_claims.validate_return_destination` (inicio y retorno), destino por defecto |
| RF-10, RF-27, RF-28, RF-29 | `google_accounts.resolve_login`, `create_user_session`, `auth` store (`restoreSession`) |
| RF-11, RF-16 | `google_accounts.decide_existing_account` / `decide_linked_account` (`ACCOUNT_DISABLED`) |
| RF-12 | `google_claims.sanitize_display_name` + alta atómica cuenta+identidad |
| RF-13, RF-22, RNF-11 | Migración 024 + segundo pase por `IntegrityError` |
| RF-14, RF-18, RF-19, RF-20, RF-21 | `google_accounts.link_identity` (sin UPDATE de correo, sin fusiones) |
| RF-23, RF-24, RF-25 | `POST /organizations` + página `/organization` |
| RF-26 | Nada escribe membresías/roles en el camino de Google (prueba explícita) |
| RF-30 | Sin cambios en `POST /auth/login` (ya responde 401 genérico con `password_hash` nulo) |
| RF-31 | Catálogo cerrado en `useI18n.ts` + `?error=<CODE>` / `?notice=<CODE>` |
| RF-32, RF-33 | `/login`, `/account/google`, estados de espera y anuncios `aria-live` |
| RNF-1 | `enforce_rate_limit` (bucket `google` y `google-identity`) |
| RNF-2, RNF-3 | `google_provider` con presupuesto de 10 s y llamadas de 5 s, sin reintentos |
| RNF-4 | Tope de 8 KiB y lectura de solo cuatro campos |
| RNF-5 | Nada de código/estado en logs, `Referer` ni almacenamiento; middleware de log saneado |
| RNF-6, RNF-7 | `set_auth_cookie` / `clear_auth_cookie` y secretos solo en el servidor |
| RNF-8 | Una transacción por operación; la sesión se emite al final |
| RNF-9, RNF-10 | Contrato aditivo, retiro documentado, paridad es/en y teclado |

---

## 3. Base de datos — migración 024

### 3.1 Contenido

`infra/postgres/migrations/024_google_identity_uniqueness.sql` (aditiva, sin *backfill*, sin rollback: *forward-fix*).

1. **Pre-chequeo que aborta.** En la misma transacción, antes de cualquier DDL:

   ```sql
   DO $$
   DECLARE v_duplicates BIGINT;
   BEGIN
       SELECT count(*) INTO v_duplicates FROM (
           SELECT user_id, provider
           FROM public.auth_identities
           GROUP BY user_id, provider
           HAVING count(*) > 1
       ) duplicated;
       IF v_duplicates > 0 THEN
           RAISE EXCEPTION
               'auth_identities incumple la identidad única: % cuentas con más de una identidad del mismo proveedor. No se corrige automáticamente (RNF-11); revisión manual.',
               v_duplicates;
       END IF;
   END
   $$;
   ```

   Nunca borra, fusiona ni reescribe filas: un incumplimiento histórico detiene el despliegue y se revisa a mano (RNF-11, caso límite 4).

2. **Restricción.**

   ```sql
   ALTER TABLE public.auth_identities
       ADD CONSTRAINT uq_auth_identity_user_provider UNIQUE (user_id, provider);
   ```

   `uq_auth_provider_subject` (ya existente) garantiza «una identidad pertenece a exactamente una cuenta»; la nueva garantiza «una cuenta tiene como máximo una identidad por proveedor». Juntas cierran RF-13/RF-22.

3. **Sin grants nuevos y sin RLS.** `auth_identities` y `users` son tablas **de plataforma**, no de tenant: no llevan RLS (principio 1 se refiere a tablas propiedad de un tenant) y el rol `bracket_app` ya tiene `SELECT (user_id, provider, provider_subject)` e `INSERT (user_id, provider, provider_subject)` sobre `auth_identities` (`init/01_schema.sql` y 001), y `SELECT (id, email, password_hash, full_name, is_active)` + `INSERT (email, password_hash, full_name)` sobre `users` (001). El camino nuevo no necesita `UPDATE` ni `DELETE`: la vinculación es un `INSERT`, el correo almacenado nunca se reescribe (RF-20) y la desvinculación está fuera de alcance. **No se toca `init/01`**: el volumen limpio ejecuta `init/00-03` y después 001…024, y termina con el mismo esquema que una base migrada.

### 3.2 Verificación

- **Base ya migrada (023 → 024):** `MIGRATION_TARGET=024 docker compose run --rm db-migrate`, tras `pg_dump` verificado. Pre-chequeo de duplicados con la consulta del punto 1 sobre la base real (solo el conteo).
- **Volumen limpio (`init` → 001…024):** cubierto por el arnés `throwaway_database(admin_url, last=24)`.
- **Igualdad de cadenas:** el test compara catálogo (constraint presente, tipo y columnas) entre la cadena limpia y la migrada.
- **Orden de despliegue:** **024 antes del código**. El código nuevo funciona sin la restricción, pero sin ella dos intentos simultáneos podrían dejar dos identidades en una cuenta: la restricción es la garantía, no una defensa redundante.

---

## 4. Backend — archivos y responsabilidades

Módulo: `backend/app/modules/identity/` (la funcionalidad es identidad, no un dominio nuevo; no se crea un módulo aparte). La organización opcional vive en el módulo existente `organizations`.

| Archivo | Estado | Responsabilidad | RF |
|---|---|---|---|
| `infra/postgres/migrations/024_google_identity_uniqueness.sql` | nuevo | Pre-chequeo + `uq_auth_identity_user_provider` | RF-13, RF-22, RNF-11 |
| `app/modules/identity/google_claims.py` | nuevo (puro) | Validación del destino, nombre para mostrar, prueba de identidad | RF-5, RF-8, RF-9, RF-12, RNF-4 |
| `app/modules/identity/google_state.py` | nuevo (I/O Redis) | Estado de un solo uso: alta, consumo atómico, descarte, clave derivada | RF-6, RF-9, RNF-5 |
| `app/modules/identity/google_provider.py` | nuevo (I/O HTTP) | URL de autorización y canje del código con presupuesto y tope de tamaño | RF-2, RF-5, RNF-2, RNF-4 |
| `app/modules/identity/account_rules.py` | nuevo (puro) | Matriz de decisión de cuenta (existente, desactivada, solo-Google, alta) | RF-11, RF-12, RF-15, RF-16, RF-17 |
| `app/modules/identity/google_accounts.py` | nuevo (I/O BD) | Resolución de login, alta atómica, segundo pase por conflicto, vinculación | RF-10…RF-22, RF-27 |
| `app/modules/identity/errors.py` | nuevo | `GoogleAuthError` (HTTPException con `code` aditivo) | RF-31, RNF-9 |
| `app/modules/identity/schemas.py` | modificado | Quita `GoogleLoginRequest`; añade `GoogleStartRequest/Response`, `GoogleStatusResponse`, `SessionResponse`, `GoogleLinkStatusResponse` | RF-3, RF-31 |
| `app/modules/identity/router.py` | modificado | `status`, `start`, `callback`, `session`, `link`, retiro del camino anterior; reutiliza `set_auth_cookie`, `clear_auth_cookie`, `create_user_session` | RF-1…RF-10, RF-27…RF-33 |
| `app/modules/organizations/router.py` | modificado | `POST /organizations` (organización opcional con dueño) | RF-23, RF-24, RF-25 |
| `app/modules/organizations/schemas.py` | modificado | `OrganizationCreateRequest`; reutiliza `OrganizationSummaryResponse` como respuesta | RF-23, RF-24 |
| `app/modules/organizations/errors.py` | nuevo | `OrganizationSlugTaken` (409 con `code: ORGANIZATION_SLUG_TAKEN`) | RF-24 |
| `app/core/access_log.py` | nuevo | Log de acceso saneado: método, ruta **sin consulta**, estado | RNF-5 |
| `app/core/config.py` | modificado | `google_redirect_uri` + validación; `google_oauth_enabled` sigue igual | RF-1, RF-4 |
| `app/main.py` | modificado | Middleware de log saneado y registro del handler de `OrganizationSlugTaken`/`GoogleAuthError` | RNF-5, RF-24 |

**Registro de routers:** no se añade ninguno; `identity_router` y `organizations_router` ya están registrados en `app/main.py` con prefijo `/api/v1`. El plan lo comprueba explícitamente porque la constitución §4 lo exige cuando hay router nuevo: no aplica.

**RLS:** el callback llama a `set_rls_context(db, None, user_id)` **dentro** de la transacción y antes de `list_user_organizations()`; `users`/`auth_identities` no son tenant. La creación de organización reutiliza `create_organization_with_owner` (`SECURITY DEFINER`, ya usada por `/auth/register`) y fija el contexto con el usuario de la sesión antes de comprobar si ya tiene organizaciones.

---

## 5. Funciones puras

Todas reciben el instante como parámetro (`now`, `deadline`) y no leen reloj, entorno, red ni base de datos.

### 5.1 `google_claims.py`

```python
GOOGLE_ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})
MAX_IDENTITY_RESPONSE_BYTES = 8 * 1024
MAX_SUBJECT_LENGTH = 255          # auth_identities.provider_subject VARCHAR(255)
MAX_DISPLAY_NAME_LENGTH = 100     # users.full_name VARCHAR(100)
MAX_RETURN_DESTINATION_LENGTH = 512
DEFAULT_DISPLAY_NAME = "Cuenta de Bracket Craft"

@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    name: str | None

def validate_return_destination(value: str | None, *, max_length: int = 512) -> str | None
def sanitize_display_name(name: str | None, email: str) -> str
def parse_identity_claims(raw: bytes, *, client_id: str, now: datetime,
                          issuers: frozenset[str] = GOOGLE_ISSUERS,
                          max_bytes: int = MAX_IDENTITY_RESPONSE_BYTES) -> GoogleIdentity
```

`validate_return_destination`: descarta (devuelve `None`) si no es `str`, si supera 512 caracteres, si no empieza por `/`, si empieza por `//`, si contiene `\` o caracteres de control, o si al decodificar una vez aparece esquema u host. No rechaza con error: RF-9 manda aplicar el destino por defecto.

`sanitize_display_name`: `strip()` y recorte a 100; si queda vacío, la parte del correo anterior a `@` recortada a 100; si también queda vacía, `DEFAULT_DISPLAY_NAME`. Nunca lanza (RF-12: el alta nunca falla por el nombre).

`parse_identity_claims` (falta cualquier comprobación → `GoogleIdentityInvalid`):
1. `len(raw) > 8192` → rechazo (RNF-4).
2. JSON mal formado o sin `id_token` de tipo `str` → rechazo.
3. `jwt.decode(id_token, options={"verify_signature": False}, algorithms=["RS256"])`: la firma no se valida porque el token llega **directamente** del endpoint de token de Google, autenticado con `client_secret` y sobre TLS; es la excepción que la propia especificación OIDC (§3.1.3.7, nota) admite y evita una segunda llamada de red (JWKS) dentro del presupuesto de 10 s. Sin firma no se acepta un `id_token` que venga del navegador: el único productor es el canje del servidor.
4. `iss ∈ GOOGLE_ISSUERS`, `aud == client_id`, `exp > now`, `sub` no vacío y ≤ 255.
5. `email` no vacío y ≤ 255, `email_verified is True` (RF-8).
6. `name` opcional (`str` o ausente). Cualquier otro claim se descarta y no se registra.

### 5.2 `account_rules.py`

```python
class LoginOutcome(StrEnum):
    CREATE = "create"
    LINKED = "linked"
    DISABLED = "ACCOUNT_DISABLED"
    PASSWORD_ACCOUNT = "ACCOUNT_EXISTS_PASSWORD"
    GOOGLE_ONLY_ACCOUNT = "ACCOUNT_EXISTS_GOOGLE_ONLY"
    INCONSISTENT = "GOOGLE_IDENTITY_INVALID"

def decide_linked_account(*, is_active: bool) -> LoginOutcome
def decide_existing_account(*, is_active: bool, has_password: bool, matches: int) -> LoginOutcome
def decide_link(*, account_subject: str | None, presented_subject: str,
                identity_owner_id: UUID | None, account_id: UUID,
                email_matches: bool) -> LinkOutcome
```

`decide_existing_account(matches=2+)` → `INCONSISTENT` (caso límite 4: datos inconsistentes, sin elegir cuenta). `decide_link` ordena: `account_subject` no nulo e igual a `presented_subject` → `IDEMPOTENT`; `account_subject` no nulo y distinto → `GOOGLE_ALREADY_LINKED`; `identity_owner_id` no nulo y distinto de `account_id` → `LINK_IDENTITY_TAKEN`; `email_matches` falso → `LINK_EMAIL_MISMATCH`; si no, `LINK`.

### 5.3 `google_state.py` (superficie pura + adaptador)

```python
@dataclass(frozen=True)
class GoogleAttempt:
    flow: Literal["login", "link"]
    destination: str | None
    user_id: str | None
    expires_at: datetime

def new_state() -> str                       # secrets.token_urlsafe(48)
def state_cache_key(state: str) -> str       # "bracket-craft:oauth:state:" + sha256(state).hexdigest()
def attempt_is_valid(attempt: GoogleAttempt, *, now: datetime) -> bool
async def save_attempt(redis, state, attempt) -> None      # SET con TTL 600
async def consume_attempt(redis, state) -> GoogleAttempt | None   # GETDEL atómico
async def discard_attempt(redis, state) -> None            # DEL best-effort
```

La clave se deriva con SHA-256: Redis nunca guarda el valor reutilizable del estado (RNF-5). `attempt_is_valid` comprueba además `expires_at > now`, aunque el TTL ya lo garantice (defensa en profundidad con reloj inyectado).

### 5.4 `google_provider.py` (borde I/O)

```python
PROVIDER_TIMEOUT_SECONDS = 5.0
ATTEMPT_BUDGET_SECONDS = 10.0
AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
SCOPE = "openid email profile"

def authorization_url(settings, *, state: str) -> str
def remaining_seconds(deadline: float, now: float) -> float      # puro
async def exchange_code(settings, *, code: str, deadline: float, client) -> bytes
```

`exchange_code`: `timeout=min(PROVIDER_TIMEOUT_SECONDS, remaining_seconds(deadline, monotonic()))`, lee como máximo 8192+1 bytes con `client.stream(...).aiter_bytes()` (aborta al superar el tope), y **no reintenta** («no hay reintentos automáticos más allá de uno» admite cero). Errores de red, `timeout` o `5xx` → `GoogleUnavailable`; `4xx` (incluido `invalid_grant` por código reutilizado) → `GoogleIdentityInvalid`.

### 5.5 Frontend puro: `app/utils/googleAuth.ts`

```ts
export const GOOGLE_ERROR_CODES = [...] as const;
export function googleStartRequest(flow: 'login' | 'link', redirect: unknown): { flow: string; redirect: string | null };
export function googleErrorKey(code: unknown): string;      // 'google.error.<CODE>' | 'google.error.unknown'
export function googleNoticeKey(code: unknown): string;     // 'google.notice.<CODE>' | ''
export function googleCallbackDestination(next: unknown): string;  // safeInternalRedirect(next, '/workspace')
```

---

## 6. Pseudocódigo

### 6.1 Inicio del flujo (`POST /auth/google/start`)

```
rate_limit(bucket="google", limit=auth_login_rate_limit, window=60)   # por IP
si NO settings.google_oauth_enabled:
    raise GoogleAuthError(503, "GOOGLE_UNAVAILABLE")                 # RF-1
user_id = get_optional_current_user_id()     # depende de la cookie; nunca obliga en flow="login"
si body.flow == "link":
    si user_id es None: raise 401 "Autenticación requerida"
    si la cuenta ya tiene identidad google: raise (409, "GOOGLE_ALREADY_LINKED")  # RF-14
destination = validate_return_destination(body.redirect)             # None si no es válido
state = new_state()
previous = cookie("bc_oauth_state")                                  # intento anterior
si previous: discard_attempt(previous)                               # RF-6: un intento nuevo invalida el anterior
save_attempt(state, GoogleAttempt(flow, destination, user_id, now + 600 s))
response.set_cookie("bc_oauth_state", state, HttpOnly, Lax, Path="/api/v1/auth/google",
                    Max-Age=600, Secure=cookie_secure)               # enlace al navegador (RF-6)
return 200 {"authorization_url": authorization_url(state)}           # Cache-Control: no-store
```

El destino **no** entra en la URL del proveedor: solo vive en Redis (RF-9, RNF-5).

### 6.2 Retorno (`GET /auth/google/callback`)

```
deadline = monotonic() + 10 s                                        # RNF-2
cookie_state = cookie("bc_oauth_state")                              # se borra siempre al salir
response.delete_cookie("bc_oauth_state", path="/api/v1/auth/google")
rate_limit(bucket="google", limit=auth_login_rate_limit, window=60)   # por IP
si NO google_oauth_enabled:                    redirect_frontend(error="GOOGLE_UNAVAILABLE")   # RF-1
si query.error:
    si query.state y cookie_state == query.state:                    # estado del navegador
        attempt_error = consume_attempt(query.state)                 # GETDEL: también en cancelación
        si Redis no responde: redirect_frontend(error="GOOGLE_UNAVAILABLE")
        si attempt_error y attempt_error.flow == "link":
            redirect_frontend(path="/account/google", error="GOOGLE_CANCELLED")   # RF-7, RF-33
    si query.state y (falta cookie_state o no coincide): discard_attempt(query.state)  # best-effort
    redirect_frontend(path="/login", error="GOOGLE_CANCELLED")       # RF-7: login, estado inválido o sin intento
si query.state falta o state_is_well_formed(state) es falso
   o cookie_state != query.state:              redirect(error="GOOGLE_STATE_INVALID")          # RF-6
attempt = consume_attempt(query.state)                               # GETDEL: un solo uso
si attempt is None o not attempt_is_valid(attempt, now): redirect(error="GOOGLE_STATE_INVALID")
si query.code falta:                           redirect(error="GOOGLE_IDENTITY_INVALID")      # datos inconsistentes
# A partir de aquí no se contacta al proveedor si Google está deshabilitado (ya comprobado arriba).
raw = exchange_code(code, deadline)                                  # GoogleUnavailable | GoogleIdentityInvalid
identity = parse_identity_claims(raw, client_id=google_audience, now=now)
rate_limit(bucket="google-identity", limit=auth_login_rate_limit, window=60,
           account_identifier=identity.subject)                      # RNF-1, tras conocer la identidad
si attempt.flow == "login":  resultado = resolve_login(identity, attempt, deadline)
si attempt.flow == "link":   resultado = link_identity(identity, attempt.user_id)

según resultado:
    SESSION(user_id, organization_id, token):
        si hay cookie de sesión previa: revocar ESA sesión (mismo navegador, RF-27; nunca otras)
        set_auth_cookie(token)
        destino = attempt.destination si válido, si no ("/organization" si organization_id is None
                                                          si no "/workspace")                   # RF-9, RF-23
        redirect_frontend(path="/auth/callback", next=destino)
    LINKED:
        redirect_frontend(path="/account/google", notice="GOOGLE_LINK_SUCCESS")                # RF-33
    ERROR(code):
        si attempt.flow == "link": redirect_frontend(path="/account/google", error=code)       # RF-18/19/14
        si no:                     redirect_frontend(path="/login", error=code)                # RF-7/11/15/16/17
```

`redirect_frontend` construye `${settings.frontend_base_url}{path}?error=|notice=|<CODE>[&next=<destino>]` con el código del catálogo y **sin** ningún dato de la cuenta; siempre `302` y `Cache-Control: no-store`. Un fallo del proveedor nunca deja cookie, cuenta, identidad ni sesión (el `302` es la única escritura de la respuesta).

### 6.3 Resolución de cuenta (una transacción)

```
resolve_login(identity, attempt):
  intento = 1
  mientras intento <= 2:
    try:
      async with db.begin():
        linked = SELECT ai.user_id, u.is_active
                 FROM auth_identities ai JOIN users u ON u.id = ai.user_id
                 WHERE ai.provider='google' AND ai.provider_subject=:sub
        si linked:
            si not linked.is_active: raise LoginRejected("ACCOUNT_DISABLED")        # RF-11
            user_id = linked.user_id
        si no:
            rows = SELECT id, is_active, password_hash FROM users WHERE LOWER(email)=LOWER(:email)
            si len(rows) == 0 → CREATE
            si no → decisión = decide_existing_account(is_active=rows[0].is_active,
                                                       has_password=rows[0].password_hash is not None,
                                                       matches=len(rows))
            ACCOUNT_DISABLED / ACCOUNT_EXISTS_PASSWORD / ACCOUNT_EXISTS_GOOGLE_ONLY /
            INCONSISTENT (→ GOOGLE_IDENTITY_INVALID) → raise LoginRejected(code)     # RF-15, RF-16, RF-17
            CREATE:
                full_name = sanitize_display_name(identity.name, identity.email)
                INSERT INTO users (email, password_hash, full_name) VALUES (LOWER(:email), NULL, :full_name)
                INSERT INTO auth_identities (user_id, provider, provider_subject) VALUES (:uid,'google',:sub)
                user_id = uid
        set_rls_context(db, None, user_id)
        organizaciones = SELECT id FROM list_user_organizations()
        organization_id = ordered_organizations(organizaciones)[0].id si hay
        token = create_user_session(db, user_id)
      return SESSION(user_id, organization_id, token)
    except IntegrityError:                     # RF-13, RF-22, RNF-11
        si intento == 2: return ERROR("GOOGLE_IDENTITY_INVALID")
        intento = 2                            # segundo pase: resuelve sobre lo ya creado
```

El segundo pase repite exactamente la misma consulta y, por tanto, resuelve los tres desenlaces posibles del conflicto: identidad ya creada por el intento ganador (sesión para esa cuenta, caso 9), correo ya creado sin contraseña (caso 10 → `ACCOUNT_EXISTS_GOOGLE_ONLY`) o correo ya creado con contraseña (`ACCOUNT_EXISTS_PASSWORD`). Si el segundo pase vuelve a chocar, falla cerrado con `GOOGLE_IDENTITY_INVALID` (RNF-11).

### 6.4 Vinculación (una transacción)

```
link_identity(identity, session_user_id):
  async with db.begin():
    cuenta = SELECT id, email FROM users WHERE id=:session_user_id AND is_active
    si no existe (o está desactivada): 302 a /account/google?error=GOOGLE_IDENTITY_INVALID (la sesión ya no es válida; no se escribe nada; §7.3)
    propia = SELECT provider_subject FROM auth_identities WHERE user_id=:uid AND provider='google'
    ajena  = SELECT user_id FROM auth_identities WHERE provider='google' AND provider_subject=:sub
    segun decide_link(account_subject=propia, presented_subject=:sub, identity_owner_id=ajena,
                      account_id=uid, email_matches=LOWER(email_cuenta)==LOWER(identity.email)):
        IDEMPOTENT       → return LINKED                                     # sin escribir (RF-14)
        GOOGLE_ALREADY_LINKED → raise LoginRejected("GOOGLE_ALREADY_LINKED")  # RF-14
        LINK_IDENTITY_TAKEN   → raise LoginRejected("LINK_IDENTITY_TAKEN")    # RF-19
        LINK_EMAIL_MISMATCH   → raise LoginRejected("LINK_EMAIL_MISMATCH")    # RF-18
        LINK: INSERT INTO auth_identities (user_id, provider, provider_subject) VALUES (:uid,'google',:sub)
  # Sin UPDATE de users.email, sin DELETE, sin tocar user_sessions: la sesión en uso no cambia (RF-18, RF-20, RF-21)
  return LINKED
```

### 6.5 Estado (ciclo de vida)

```
new_state()               → 48 bytes aleatorios urlsafe (impredecible)
save_attempt()            → SET bracket-craft:oauth:state:<sha256(state)> {json} EX 600
consume_attempt()         → GETDEL <clave>   (atómico: dos retornos simultáneos, uno solo gana)
discard_attempt()         → DEL <clave>      (best-effort en un inicio nuevo y en cancelación con estado ausente o ajeno)
cancelación con estado    → consume_attempt() (GETDEL; enruta según flow y nunca permite reutilizar el intento)
validación en el retorno  → cookie == query == clave existente && expires_at > now
```

Caducidad ≤ 10 min garantizada dos veces (TTL de Redis y `expires_at` del registro).

### 6.6 Organización opcional (`POST /organizations`)

```
para = get_current_user_id()                        # 401 sin sesión
async with db.begin():
    set_rls_context(db, None, para)
    si list_user_organizations() no está vacía: raise 409 (RF-25; sin `code`, no está en el catálogo)
    org_id = SELECT create_organization_with_owner(:name, :slug, :para)      # atómico (RF-24)
except IntegrityError:                              # uq_organizations_slug_ci
    raise OrganizationSlugTaken                     # 409 {detail, code: ORGANIZATION_SLUG_TAKEN}
return 201 {id, name, slug, organization_user_id}   # misma forma que el listado
```

---

## 7. Interfaz (contratos exactos)

Base: `/api/v1`. Todas las respuestas llevan `Cache-Control: no-store`. Ninguna respuesta incluye tokens del proveedor, correo, nombre ni identificadores de Google.

### 7.1 `GET /auth/google/status`

| | |
|---|---|
| Sesión | no |
| 200 | `{"enabled": true\|false}` |

Solo el booleano: la pantalla de acceso decide si muestra la opción (RF-1) y ningún secreto ni `client_id` llega al navegador.

### 7.2 `POST /auth/google/start`

| | |
|---|---|
| Sesión | opcional; **obligatoria** con `flow="link"` |
| Cuerpo | `{"flow": "login"\|"link"}` (por defecto `login`), `{"redirect": string \| null}` |
| 200 | `{"authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?..."}` + `Set-Cookie: bc_oauth_state=…; HttpOnly; SameSite=Lax; Path=/api/v1/auth/google; Max-Age=600` (+ `Secure` fuera de desarrollo) |
| 401 | `{"detail": "Autenticación requerida"}` (solo `flow="link"` sin sesión) |
| 409 | `{"detail": "…", "code": "GOOGLE_ALREADY_LINKED"}` (solo `flow="link"` con identidad ya vinculada) |
| 429 | `{"detail": "…", "code": "RATE_LIMITED"}` + `Retry-After: 60` |
| 503 | `{"detail": "…", "code": "GOOGLE_UNAVAILABLE"}` (Google deshabilitado o Redis no disponible) |
| 422 | Validación del cuerpo (tipos y `flow` fuera del enum; el detalle no repite la entrada) |

`redirect` inválido **no** es 422: se normaliza a `null` y el retorno usa el destino por defecto (RF-9). El cuerpo CSRF lo aporta `useApi` (ruta `/api/v1/auth/`, escritura).

### 7.3 `GET /auth/google/callback?code&state` (y `?error=access_denied`)

| | |
|---|---|
| Sesión | no |
| Éxito (login) | `302 Location: {frontend}/auth/callback?next=<destino>` + `Set-Cookie: bc_access_token=…` (HttpOnly, SameSite, `Secure` fuera de desarrollo, `Path=/`) + `Set-Cookie: bc_oauth_state=; Max-Age=0; Path=/api/v1/auth/google` |
| Éxito (vinculación) | `302 Location: {frontend}/account/google?notice=GOOGLE_LINK_SUCCESS` (cookie de sesión intacta) |
| Error de inicio | `302 Location: {frontend}/login?error=<CODE>` |
| Error de vinculación | `302 Location: {frontend}/account/google?error=<CODE>` |

Solo se leen `code`, `state` y `error`; el resto de parámetros se ignora (RF-4). Nunca devuelve cuerpo ni datos de la cuenta, y el `Referer` de la redirección al frontend no transporta el código (va en la ruta del proveedor y muere en esta respuesta).

### 7.4 `GET /auth/session`

| | |
|---|---|
| Sesión | obligatoria |
| 200 | `{"user_id": "<uuid>", "organization_id": "<uuid>"\|null}` |
| 401 | `{"detail": "Token inválido"\|"Autenticación requerida"}` |

Requerido por el retorno del flujo: la cookie de sesión vive en el origen de la API y el cliente necesita reconstruir su estado (`bc_user_id`) antes de navegar al destino. Devuelve la **primera** organización del orden estable; el cliente aplica después su organización recordada (RF-10).

### 7.5 `GET /auth/google/link`

| | |
|---|---|
| Sesión | obligatoria |
| 200 | `{"linked": true\|false}` |

Único dato de la vinculación que se expone al propio interesado: no devuelve sujeto, correo ni fecha (RF-33, privacidad).

### 7.6 `POST /auth/google` (retirado)

| | |
|---|---|
| Cuerpo | cualquiera (no se valida ni se lee) |
| 410 | `{"detail": "…", "code": "GOOGLE_IDENTITY_INVALID"}` |

Sin sesión, sin llamada al proveedor, sin escritura y sin rate limit que consuma cupo del flujo nuevo. El código es el del catálogo («prueba no válida»): un cliente antiguo recibe un rechazo estable y no una sesión (RF-3, RNF-9). Ver §12, decisión D-6.

### 7.7 `POST /organizations`

| | |
|---|---|
| Sesión | obligatoria (no exige `X-Organization-ID`) |
| Cuerpo | `{"name": 2..100, "slug": 2..100 con ^[a-z0-9-]+$}` |
| 201 | `{"id", "name", "slug", "organization_user_id"}` |
| 401 | sin sesión |
| 409 | `{"detail": "…"}` si la cuenta ya tiene una organización (RF-25, sin `code`) |
| 409 | `{"detail": "…", "code": "ORGANIZATION_SLUG_TAKEN"}` si el identificador está ocupado (RF-24) |
| 422 | validación del cuerpo |

### 7.8 Rutas del frontend

| Ruta | Middleware | Contenido |
|---|---|---|
| `/login` (existente) | ninguno | Botón «Continuar con Google» si `status.enabled`; espera (`aria-busy`, `aria-live`), `?error=`, `?redirect=`; enlace a `/organization` si hay sesión sin organización |
| `/auth/callback` (nueva) | ninguno | Reconstruye la sesión (`GET /auth/session`), `saveSession`, `loadOrganizations`, `navigateTo(destino, { replace: true })`; sin `next` válido → `/workspace` |
| `/account/google` (nueva) | `session` | Estado de vinculación, botón, espera, `?notice=`, `?error=` |
| `/organization` (nueva) | `session` | Alta opcional con nombre e identificador; `?next=`; «Ahora no» conserva la sesión y muestra el aviso |
| — (nueva) `app/middleware/session.ts` | — | Exige `auth.userId`; si falta, `/login?redirect=<ruta>` |

`WorkspaceShell.vue` añade «Cuenta de Google» al menú de cuenta (enlace a `/account/google`).

---

## 8. Frontend — archivos y responsabilidades

| Archivo | Estado | Responsabilidad | RF |
|---|---|---|---|
| `app/utils/googleAuth.ts` | nuevo (puro) | Cuerpo del inicio, mapa de códigos→claves, destino del retorno | RF-9, RF-31 |
| `tests/google-auth.test.ts` | nuevo | Pruebas puras + paridad de catálogo del vocabulario de códigos | RF-31, RNF-10 |
| `app/composables/useI18n.ts` | modificado | 12 mensajes del catálogo + textos de pantalla, en `es` y `en` | RF-31, RNF-10 |
| `app/stores/auth.ts` | modificado | `restoreSession()`, `startGoogleAuthorization()`, `linkGoogle()`, `createOrganization()` | RF-10, RF-23, RF-33 |
| `app/pages/login.vue` | modificado | Opción de Google, espera, mensajes, `redirect` | RF-1, RF-7, RF-32 |
| `app/pages/auth/callback.vue` | nuevo | Rehidratación de sesión y navegación con `replace` | RF-9, RF-10 |
| `app/pages/account/google.vue` | nuevo | Pantalla de vinculación | RF-18, RF-33, RF-32 |
| `app/pages/organization.vue` | nuevo | Organización opcional | RF-23, RF-24, RF-25 |
| `app/middleware/session.ts` | nuevo | Sesión sin organización | RF-23 |
| `app/components/WorkspaceShell.vue` | modificado | Entrada de menú a la pantalla de vinculación | RF-33 |
| `app/composables/useApi.ts` | **sin cambios** | Todas las llamadas nuevas usan `request()` (incluido el `POST /auth/google/start`, que devuelve la URL del proveedor y evita navegar contra la API) | §3.3 |

**i18n.** Claves bajo `google.*` con el catálogo cerrado: `google.error.GOOGLE_UNAVAILABLE`, `…_CANCELLED`, `…_STATE_INVALID`, `…_IDENTITY_INVALID`, `…ACCOUNT_DISABLED`, `…ACCOUNT_EXISTS_PASSWORD`, `…ACCOUNT_EXISTS_GOOGLE_ONLY`, `…GOOGLE_ALREADY_LINKED`, `…LINK_EMAIL_MISMATCH`, `…LINK_IDENTITY_TAKEN`, `…RATE_LIMITED`, `…ORGANIZATION_SLUG_TAKEN`, `google.notice.GOOGLE_LINK_SUCCESS`, más `google.continue`, `google.waiting`, `google.error.unknown`, `google.link.*` y `organization.*`. Paridad estricta es/en; el barrido de `utils/i18nCatalog.ts` detecta cualquier clave usada y ausente, y la prueba pura recorre `GOOGLE_ERROR_CODES` contra los dos catálogos (el vocabulario generado cubre las claves dinámicas).

**Accesibilidad (RNF-10).** El botón de Google es un `<button type="button">` dentro del formulario existente; al pulsarlo pasa a `disabled` con `aria-busy="true"` y el texto de espera, y el contenedor de mensajes es `role="status"`/`aria-live="polite"` (errores `role="alert"`). La pantalla de organización usa el mismo patrón que los asistentes de la 012 (título enfocado, error asociado con `aria-invalid`/`aria-describedby`), y el enlace de vinculación es alcanzable con teclado desde el menú de cuenta.

---

## 9. Exposición pública

- **Ninguna superficie pública cambia.** `/`, `/tournaments/{id}` y `/api/v1/tournaments/public*` no se tocan; no hay campos nuevos ni proyecciones nuevas.
- `GET /auth/google/status`, `GET /auth/session`, `GET /auth/google/link`, `POST /auth/google/start` y el retorno son superficies de identidad autenticadas o de configuración, no datos de organización.
- `GET /auth/session` devuelve `user_id` y `organization_id` **solo de la propia sesión**; no expone correo, nombre, identidad ni vinculación.
- La única revelación de existencia de cuenta es el mensaje `ACCOUNT_EXISTS_PASSWORD` / `ACCOUNT_EXISTS_GOOGLE_ONLY`, limitada a quien controla la cuenta de Google con ese correo verificado: riesgo aceptado en la spec.
- `v_public_tournament_players` y las vistas públicas no se modifican (constitución §2.5).

---

## 10. Configuración y secretos

| Variable | Servicio | Default de desarrollo | Nota |
|---|---|---|---|
| `GOOGLE_CLIENT_ID` | `api` | vacío | ya existe |
| `GOOGLE_CLIENT_SECRET` | `api` | vacío | ya existe; **nunca** llega al navegador ni a logs (RNF-7) |
| `GOOGLE_AUDIENCE` | `api` | vacío | ya existe; se sigue validando `== client_id` y es el `aud` aceptado |

**Nueva:** `GOOGLE_REDIRECT_URI` (`api`), con su valor de desarrollo **solo** en `.env.example`:

```
# Dirección de retorno fija registrada en Google Cloud Console. Ruta exacta:
# {API pública}/api/v1/auth/google/callback
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/google/callback
```

- `Settings.google_redirect_uri: str | None = None`, normalizada por el validador `blank_optional_string_to_none` que ya trata `""` como ausente (Compose inyecta `${GOOGLE_REDIRECT_URI:-}`).
- Si `google_oauth_enabled` y falta `google_redirect_uri` → `ValueError` al arrancar (falla cerrada; RF-4 exige una dirección fija **configurada**). Si está presente, debe ser una URL absoluta `http(s)`; nada más (no se exige `https` en desarrollo).
- `docker-compose.yml` (`api`): `GOOGLE_REDIRECT_URI: ${GOOGLE_REDIRECT_URI:-}`; el overlay de producción la hereda sin cambios.
- `infra/scripts/check_env_contract.py` (`API_ENV`) y `backend/tests/test_env_contract.py`: añaden la variable al mapa y a las listas de contrato.
- Límites de intentos: se reutiliza `AUTH_LOGIN_RATE_LIMIT` (10 por 60 s, ya configurable y documentada) para los buckets `google` y `google-identity`. Los tiempos del proveedor (5 s/10 s) y el TTL del estado (600 s) son constantes del módulo: no se añaden variables que nadie pidió.
- **Ningún secreto nuevo por defecto.** `GOOGLE_CLIENT_SECRET` sigue vacío en `.env.example` y fuera de desarrollo se exige externamente; el validador de producción no cambia.

---

## 11. Documentación

| Documento | Cambio |
|---|---|
| `README.md` | Sección «Acceso con Google»: flujo de redirección, catálogo de códigos, pantalla de vinculación, organización opcional, **retiro de `POST /auth/google`** (cambio de contrato observable), migración 024 con su runbook y orden 024 → código. Se quita el punto «Preparación de Google OAuth mediante `auth_identities`» del alcance inicial. |
| `AGENTS.md` | Sustituye «email/password; Google OAuth preparado mediante `auth_identities`» por el flujo real; documenta los endpoints, el estado en Redis, el log de acceso saneado, la restricción 024 y el orden de despliegue; añade la comprobación manual contra Google real. |
| `docs/runbook-despliegue-019-023.md` | Sin cambios (su alcance termina en 023); el runbook de la 024 vive en README/AGENTS porque la migración es aditiva y de una sola sentencia. |

---

## 12. Decisiones justificadas

| # | Decisión | Alternativa descartada | Motivo |
|---|---|---|---|
| D-1 | **Estado de un solo uso en Redis**, clave `sha256(state)`, TTL 600 s, consumo `GETDEL`, destino y flujo en el mismo registro | Tabla nueva `oauth_states` en PostgreSQL | Redis ya es dependencia obligatoria (rate limit, outbox), el TTL es nativo, `GETDEL` da el consumo atómico que RNF-5 exige y no añade una tabla de plataforma con limpieza, RLS innecesaria ni escrituras antes de verificar la identidad. Una tabla exigiría barrido de caducados y abriría una transacción en el camino previo a la validación. |
| D-2 | **Enlace al navegador con cookie `bc_oauth_state`** (`HttpOnly`, `SameSite=Lax`, `Path=/api/v1/auth/google`, `Max-Age=600`) comparada con el `state` de la consulta | Guardar un hash de IP + `User-Agent` | IP y `User-Agent` no identifican un navegador (NAT, proxies, actualizaciones) y `User-Agent` es un dato personal que no se necesita. La cookie es exactamente «el navegador que inició el intento» y no persiste nada. `SameSite=Lax` (no `None`) porque el retorno es una navegación de nivel superior; con `Strict` la cookie no llegaría y el flujo fallaría siempre. |
| D-3 | **El inicio del flujo es `POST` + `useApi`, y la navegación al proveedor es del navegador** | `GET /auth/google/start` como navegación directa | El `POST` permite mostrar el error de límite de intentos con su `Retry-After` en la propia pantalla (RNF-1), mantiene el estado de espera de RF-32 y cumple «toda llamada usa `useApi.ts`». La cookie de estado se fija en la respuesta del `fetch` con `credentials: include`, que es de primera parte cuando la API comparte dominio registrable; una navegación `GET` directa a la API solo sería mejor si API y web estuvieran en sitios distintos, escenario que el proyecto no tiene (mismo `localhost` o subdominios del mismo dominio). |
| D-4 | **Retorno a `/auth/callback` del frontend, que rehidrata y navega con `replace`** | Redirigir directamente al destino y dejar que el middleware `auth` hidrate | La cookie de sesión vive en el origen de la API y no viaja al servidor de Nuxt, así que el renderizado en servidor del destino no puede resolver la sesión y expulsaría a `/login`. Una página puente lo resuelve en el cliente, sin exponer tokens y manteniendo el destino final en la barra de direcciones como una sola redirección del servidor. |
| D-5 | **`GET /auth/session`** devuelve `user_id` y `organization_id` de la cookie | Devolver el usuario en la redirección (query) | Habría que poner datos de sesión en la URL: exactamente lo que RNF-6 prohíbe. |
| D-6 | **Retiro con `410` y `code: GOOGLE_IDENTITY_INVALID`** | 404 por borrado de ruta; nuevo código `GOOGLE_FLOW_REQUIRED` | RF-3 exige un rechazo **con código estable** y RNF-9 conserva el contrato aditivo; 404 no lleva código y la spec cierra el catálogo, así que se usa el código existente cuyo significado es literalmente «prueba no válida». Ver §15 (requiere confirmación). |
| D-7 | **Códigos de error por consulta (`?error=`, `?notice=`)** con el catálogo cerrado | Cuerpo JSON con la página de error | El retorno es una navegación; el código estable en la consulta es observable, traducible y no contiene datos. Solo se aceptan códigos conocidos (`GOOGLE_ERROR_CODES`); uno desconocido cae en `google.error.unknown`. |
| D-8 | **`POST /organizations` en el módulo `organizations`** con `create_organization_with_owner` | Reutilizar `POST /auth/register` o crear la organización en el callback | No existe endpoint de alta de organización y el registro obliga a correo y contraseña (imposible para una cuenta solo-Google). Crearla en el callback contradeciría RF-23 (el paso es opcional y explícito). |
| D-9 | **Firma del `id_token` no verificada** (llega del endpoint de token por TLS, autenticado con `client_secret`) | Verificar contra el JWKS de Google | La especificación OIDC admite el canal directo como validación del emisor; descargar el JWKS añade una llamada de red y un cliente síncrono que bloquearía el bucle de eventos, dentro de un presupuesto de 10 s. Un `id_token` presentado por el navegador nunca se acepta, así que no hay superficie para el ataque que la firma mitigaría. |
| D-10 | **Conflicto de unicidad resuelto con `IntegrityError` + segundo pase** | `INSERT … ON CONFLICT DO NOTHING` seguido de `SELECT` | `ON CONFLICT` sobre el índice funcional `uq_users_email_ci` no es portable ni distingue «identidad ganadora» de «correo ganador»; el segundo pase reutiliza exactamente la misma consulta y cubre los tres desenlaces de RF-22 con una sola rama. |
| D-11 | **Log de acceso saneado**: `uvicorn --no-access-log` + middleware que registra método, ruta sin consulta y estado | Mantener el log por defecto | El log por defecto escribe la línea de petición completa con `?code=…&state=…`: incumple RNF-5 y el criterio 8. Se conserva la observabilidad (método, ruta, estado) perdiendo solo la consulta, que ningún consumidor del proyecto lee. Ver §15. |
| D-12 | **Sin reintentos al proveedor** (el máximo permitido es uno) | Un reintento automático | Un reintento consume el código de autorización (que es de un solo uso) y no puede recuperar un `invalid_grant`; añade latencia sin mejorar el resultado. RNF-2 admite cero. |
| D-13 | **Sesión anterior del mismo navegador revocada en el login con Google** | Solo sobrescribir la cookie | RF-27 dice «sustituye la sesión anterior del mismo navegador, no la reutiliza ni la prolonga»; revocar el `jti` presentado es la lectura literal y no afecta a otros dispositivos. En la vinculación **no** se toca la sesión (RF-18). |
| D-14 | **`GOOGLE_REDIRECT_URI` obligatoria cuando Google está configurado** | Derivar la URL del `Host` de la petición | Derivarla abre *host header injection* y rompe el registro fijo en Google Console que RF-4 exige. |

---

## 13. Estrategia de tests

El proveedor externo **se simula** en todas las pruebas automatizadas (RNF-12): se sustituyen `google_provider.exchange_code`/`authorization_url` y el cliente Redis del estado, nunca se llama a Google. La comprobación real es manual (§13.5).

### 13.1 Unitarias puras (sin base ni red)

| Archivo | Cubre |
|---|---|
| `backend/tests/test_google_claims.py` | RF-5, RF-8, RF-9, RF-12, RNF-4: destino (válido, `//`, esquema, 513 caracteres, control, `None`, decodificación), nombre (recorte, vacío, local part, neutro), prueba de identidad (emisor, audiencia, caducidad, sujeto, correo verificado, campos ausentes, JSON roto, 8193 bytes, sujeto > 255) |
| `backend/tests/test_google_account_rules.py` | RF-11, RF-14…RF-19: matriz completa de `decide_existing_account` y `decide_link`, incluido el desenlace idempotente |
| `backend/tests/test_google_state.py` | RF-6, RF-9, RNF-5: `new_state` impredecible y longitud, clave con SHA-256 (el valor crudo no aparece), `save_attempt` con TTL, `consume_attempt` una sola vez con `FakeRedis`, caducidad con reloj inyectado, `discard_attempt` |
| `backend/tests/test_google_provider.py` | RF-2, RF-5, RNF-2, RNF-4: parámetros exactos de la URL (scope mínimo, `redirect_uri`, `state`), `remaining_seconds`, tope de 8 KiB (corta al superar), timeout y error de red → `GoogleUnavailable`, `invalid_grant` → `GoogleIdentityInvalid` |
| `backend/tests/test_access_log.py` | RNF-5: una petición con consulta produce una línea sin la consulta; el método y el estado se conservan |

### 13.2 Endpoint (ASGITransport + dobles; mismo patrón que `test_organizations_order.py`)

`backend/tests/test_google_auth.py` — sesión simulada, base falsa (`MappingResult`/`EmptyDatabase`) y estado simulado:

- RF-1: `status` en ambos estados; `start` y `callback` con Google deshabilitado → 503/`GOOGLE_UNAVAILABLE`, sin tocar el proveedor ni la base.
- RF-2: la URL devuelta no contiene tokens ni el `client_secret`.
- RF-3: `POST /auth/google` → 410 con `code`, sin `Set-Cookie`, sin escritura.
- RF-4: parámetros extra ignorados; `code` ausente → `GOOGLE_IDENTITY_INVALID`.
- RF-6: sin cookie, cookie distinta, estado repetido, caducado, cookie de otro navegador, inicio nuevo que invalida el anterior.
- RF-7: `?error=access_denied` → `GOOGLE_CANCELLED`.
- RNF-1: `Retry-After` y `code: RATE_LIMITED` en `start`; bucket `google-identity` invocado con el sujeto (hasheado) tras el canje.
- RF-31/RNF-6: `Set-Cookie` con `HttpOnly`, `SameSite`, `Path` correctos; ninguna respuesta (cuerpo o `Location`) contiene correo, nombre, sujeto, `code` ni `state`; el cuerpo de `start` solo lleva `authorization_url`.
- RF-9/RF-23: destinos válidos, ausente, inválido, y organización vacía → `/organization`.
- RF-27: la sesión previa del mismo navegador se revoca; la vinculación no revoca nada.
- RF-33: `?notice=GOOGLE_LINK_SUCCESS`, `?error=GOOGLE_ALREADY_LINKED` y `GET /auth/google/link`.
- RF-25/RF-24: `POST /organizations` 201/409/422/401 con base falsa.

`backend/tests/test_auth_session.py` (puede vivir en el mismo archivo): `GET /auth/session` 200/401 y `no-store`.

### 13.3 Opt-in con PostgreSQL (`RUN_DATABASE_TESTS=1` + `DATABASE_ADMIN_URL`)

| Archivo | Cubre |
|---|---|
| `backend/tests/test_migration_024.py` | RF-13, RNF-11, criterio 10: cadena limpia (`init` + 001…024) y migrada (023 → 024); pre-chequeo que aborta con duplicados sembrados (023, antes de la restricción); `UNIQUE (user_id, provider)` rechaza la segunda identidad de la misma cuenta y sigue admitiendo la misma identidad en cuentas distintas; catálogo idéntico entre cadenas |
| `backend/tests/test_google_accounts_db.py` | RF-10, RF-12, RF-13, RF-14, RF-16, RF-18…RF-22, RF-26, RF-27: alta con nombre recortado/derivado/neutro, correo en mayúsculas, cuenta desactivada con y sin identidad, cuenta con contraseña (`ACCOUNT_EXISTS_PASSWORD`), cuenta solo-Google (`ACCOUNT_EXISTS_GOOGLE_ONLY`), `GOOGLE_ALREADY_LINKED`, `LINK_IDENTITY_TAKEN`, `LINK_EMAIL_MISMATCH`, caso idempotente, cambio de correo del proveedor que no reescribe nada, **ninguna** fila de membresía/rol creada por el login, organización activa = primera del orden estable |
| `backend/tests/test_google_concurrency_db.py` | RF-13, RF-22, RNF-11 (casos 9 y 10): dos conexiones simultáneas con la misma identidad → una cuenta y una identidad; con el mismo correo y distinto sujeto → una cuenta y `ACCOUNT_EXISTS_GOOGLE_ONLY`. Patrón de `test_concurrency_006.py` (rol dedicado, bases desechables) |
| `backend/tests/test_organizations_create_db.py` | RF-24, RF-25, RF-26: alta con dueño (membresía + rol `owner`), 409 con identificador ocupado sin perder la sesión, 409 con organización previa, y una cuenta con organización que no puede crear otra |

### 13.4 Frontend (`cd frontend && pnpm test`)

`tests/google-auth.test.ts`: cuerpo del inicio (`flow`, `redirect` inválido → `null`), mapa de códigos → claves, `googleCallbackDestination` (rechaza `//host`, esquema, control) y **paridad**: cada código de `GOOGLE_ERROR_CODES` tiene clave en `es` y `en` (lectura de `composables/useI18n.ts` con `catalogKeys`, como `tests/labels.test.ts`). El barrido de `utils/i18nCatalog.ts` cubre el resto de claves usadas en las páginas nuevas.

### 13.5 Prueba manual declarada (criterio 11)

Con un cliente OAuth **real** de Google (tipo «Aplicación web») y `GOOGLE_REDIRECT_URI` registrada:

1. Alta con una cuenta de Google nueva → `/organization` → crear organización → Workspace.
2. Cierre de sesión y nueva entrada → misma cuenta, sin duplicados (`SELECT count(*) FROM users WHERE LOWER(email)=…`).
3. Entrada con Google usando el correo de una cuenta local con contraseña → `ACCOUNT_EXISTS_PASSWORD`; entrar con contraseña y vincular desde `/account/google` → `GOOGLE_LINK_SUCCESS`.
4. Cancelar el consentimiento → `GOOGLE_CANCELLED`; esperar 11 minutos y reutilizar el retorno → `GOOGLE_STATE_INVALID`.
5. Entrada desde `/invitations/{token}` → vuelve a la invitación y se acepta.

El resultado (fecha, entorno, códigos observados, sin correos ni identificadores) se registra en el README. **El job `e2e` no es evidencia**: no cubre Google.

---

## 14. Orden de implementación y despliegue

1. **024** (aditiva) → `MIGRATION_TARGET=024`.
2. **Código nuevo** (depende de la restricción para RF-13; funciona con el esquema anterior, pero sin la garantía).
3. **Frontend** (solo necesita la API nueva).
4. `GOOGLE_REDIRECT_URI` en el gestor de secretos y en la consola de Google **antes** de habilitar el flujo; sin ella la configuración no arranca.
5. El flujo anterior deja de existir en el mismo despliegue: la documentación se publica junto (RNF-9).

---

## 15. Riesgos y decisiones pendientes de confirmación

1. **D-6** — código estable del retiro (`410` + `GOOGLE_IDENTITY_INVALID`) frente a un código nuevo fuera del catálogo. Si el usuario prefiere un código propio, exige cambiar la spec (el catálogo es cerrado).
2. **D-11** — desactivar el log de acceso de Uvicorn y sustituirlo por uno saneado es un cambio operativo que la spec no nombra pero RNF-5 y el criterio 8 sí exigen.
3. **RF-25 y «ya vinculada» en el inicio** — se responde **409** con `detail` (RF-25, sin `code`) y **409** con `code: GOOGLE_ALREADY_LINKED` (vinculación). No hay código de catálogo para el primero.
4. **`POST /organizations`** — endpoint nuevo no nombrado en la spec pero imprescindible para RF-23/RF-24; se propone `POST /api/v1/organizations` con la forma del listado.

---

## 16. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento por RLS | Sí | No se crea ninguna tabla de tenant; `users`/`auth_identities` son de plataforma (sin RLS, como hoy). Toda consulta de organización usa `set_rls_context` en su transacción (`list_user_organizations`, `create_organization_with_owner`). |
| §2.2 La aplicación no salta RLS | Sí | No se cambian roles ni privilegios; `validate_application_role` sigue vigente y la 024 no concede privilegios. |
| §2.3 Lo publicado es inmutable | Sí (no se toca) | El flujo de identidad no escribe torneos, versiones, actas ni resultados. |
| §2.4 Historial de esquema append-only | Sí | Una sola migración nueva (024); no se edita ninguna aplicada; el pre-chequeo aborta en vez de corregir datos. |
| §2.5 Lo público es una proyección mínima | Sí | Sin cambios en vistas ni endpoints públicos; ningún campo nuevo expone correo, nombre de cuenta ni vinculación. |
| §2.6 Ningún secreto por defecto fuera de desarrollo | Sí | `GOOGLE_CLIENT_SECRET` sigue vacío en `.env.example`; `GOOGLE_REDIRECT_URI` no es secreto y su valor de desarrollo vive solo ahí; el validador de producción no se relaja. |
| §2.7 Administración global separada y auditada | Sí | No se tocan `/admin` ni `platform_audit_logs`; una cuenta desactivada sigue sin poder entrar (RF-11/RF-16). |
| §2.8 Nada se da por terminado sin verificación | Sí | T27–T30 ejecutan los jobs y la comprobación manual se declara; lo no ejecutado se informa. |
| §2.9 El código de desarrollo no llega a producción | Sí | No se toca `scripts.seed_demo` ni se añaden datos demo; la prueba manual usa una cuenta real solo en desarrollo. |
| §4 todos: CI correspondiente | Sí | `backend`, `frontend`, `infrastructure` y `security` (T27–T29); `e2e` se ejecuta en cada PR pero **no** se usa como evidencia de Google. |
| §4 todos: sin secretos ni datos personales en el repo | Sí | Tests con correos `.test`, sujetos ficticios y logs sin correo/nombre/sujeto; el catálogo no admite tokens ni identificadores. |
| §4 todos: documentación afectada | Sí | README y AGENTS (T26), incluido el retiro del contrato anterior (RNF-9). |
| §4 todos: pruebas del comportamiento nuevo | Sí | 13.1–13.4; lo que necesita Google real se declara manual (RNF-12). |
| §4 BD: nueva migración, sin editar aplicadas | Sí | 024 (T1); ninguna otra migración se toca. |
| §4 BD: RLS y políticas en tablas tenant nuevas | No aplica | No hay tablas nuevas. |
| §4 BD: volumen limpio y migrado | Sí | `test_migration_024.py` (cadena `init`+001…024 y 023→024, catálogo idéntico). |
| §4 BD: `sh -n infra/postgres/migrate.sh` | Sí | T29. |
| §4 API: consultas tenant con `set_rls_context` | Sí | `resolve_login` y `POST /organizations` fijan el contexto dentro de la transacción antes de `list_user_organizations()`. |
| §4 API: endpoints públicos sin campos sensibles | Sí | §9; ni correo, ni nombre, ni identidad, ni vinculación. |
| §4 API: router nuevo registrado en `app/main.py` | No aplica | Los routers `identity` y `organizations` ya están registrados; se verifica en T17/T26 que no hace falta uno nuevo. |
| §4 API: `pytest -q` y `compileall` | Sí | T27. |
| §4 Frontend: llamadas por `useApi.ts` | Sí | Todas las llamadas nuevas usan `request()`; el único destino de navegación es el proveedor (D-3). |
| §4 Frontend: `pnpm test`, `typecheck`, `build` | Sí | T28. |
| §4 Infra: `docker compose config -q` | Sí | T29, con `GOOGLE_REDIRECT_URI` en desarrollo y en el merge de producción. |
| §4 Infra: sin defaults de desarrollo en producción | Sí | `.env.example` sigue siendo la única fuente de defaults; producción exige secretos externos. |
| §4 Dependencias: lockfiles y auditorías | No aplica (sin dependencias nuevas) | `pip-audit`, `audit_frontend.py` y Trivy se ejecutan igualmente en T29; no se añaden paquetes (PyJWT, httpx y redis ya están). |

**No hay ningún principio innegociable en riesgo; las decisiones D-6 y D-11 se presentan para confirmación explícita antes de implementar.**
