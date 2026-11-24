# Plan — Spec 043: Compartir y SEO (F14)

Estado: aprobado por el usuario el 2026-11-23 («Apruebo el plan, las tareas y la excepción. Empieza con T1»), incluida la excepción §3.3 del sitemap.

## 1. Alcance y dependencias

- Sin migraciones, tablas, permisos, RLS, outbox ni Socket.IO nuevos. Las lecturas nuevas usan las vistas públicas existentes (`v_public_tournaments`, `v_public_matches`, `v_match_live_public_selection`) con el mismo `set_rls_context(org_del_torneo, None)` que la cronología (037).
- Una dependencia nueva de backend: **Pillow 13.0.0** (desviación registrada en T1: la 12.3.0 aprobada tiene avisos de seguridad en `pip-audit` corregidos en la 13.0.0), para dibujar PNG. Una fuente vendorizada: Archivo variable (OFL) en TTF, la misma familia que ya sirve el frontend.
- Sin dependencias nuevas de frontend.
- Variable nueva de frontend `NUXT_PUBLIC_SITE_URL` (origen público, RF-012). En Compose reutiliza `FRONTEND_BASE_URL`, que producción ya exige con `:?` (caso límite «origen sin configurar»).
- Dos PR de implementación: **bloque A** backend (T1–T3) y **bloque B** frontend, E2E y documentación (T4–T9).

## 2. Archivos y responsabilidades

### Backend

| Archivo | Responsabilidad | RF |
|---|---|---|
| `backend/app/modules/tournaments/share_image.py` (nuevo) | Funciones puras de composición: `tournament_card(name, season, status, lang)`, `result_card(tournament_name, home, away, home_score, away_score, home_pen, away_pen, lang)`, `brand_card(lang)` → `bytes` PNG 1200×630. `fit_text(text, font, max_width)` recorta con «…». Etiquetas ES/EN cerradas (estado del torneo, «Resultado final», «Penaltis»). Colores tomados de los tokens de marca oscuros (contraste ≥ 4.5:1 comprobado en test). | RF-003, RF-004, RF-014, RNF-003 |
| `backend/app/modules/tournaments/share_policy.py` (nuevo) | Pura: `is_shareable_result(row) -> bool` = `status in {"finished", "administrative_resolution"}` y ambos equipos presentes. | RF-004, RF-005 |
| `backend/app/assets/fonts/Archivo[wdth,wght].ttf`, `OFL.txt` (nuevos) | Fuente vendorizada con su licencia. | RNF-003 |
| `backend/app/assets/share/brand-fallback.png` (nuevo) | Imagen de marca generada una vez por `brand_card("es")` y versionada; se sirve si falla el render. | RNF-002 |
| `backend/app/modules/tournaments/routes/public.py` | Cuatro lecturas (detalle en §3). Reutiliza la consulta de `public_matches` extrayendo la unión a un helper con filtro opcional por `match_id`, sin cambiar su salida. | RF-005, RF-006, RF-013 |
| `backend/requirements.txt` | `pillow==13.0.0`. | — |

### Frontend

| Archivo | Responsabilidad | RF |
|---|---|---|
| `frontend/nuxt.config.ts` | `runtimeConfig.public.siteUrl` (`NUXT_PUBLIC_SITE_URL`, default `http://localhost:3000` como las otras URL). | RF-012 |
| `frontend/app/utils/publicSeo.ts` (nuevo) | Puras: `absoluteUrl(siteUrl, path)`, `apiAssetUrl(siteUrl, apiBase, path)` (`new URL(apiBase, siteUrl)`, admite base relativa o absoluta), `tournamentHead(...)`, `resultHead(...)`, `homeHead(...)`, `playerHead(...)` → listas de `meta`/`link` (OpenGraph, `twitter:card=summary_large_image`, canonical, `og:image:width/height/alt`, `robots` en jugador). `isShareableResult(match)` espejo de la política backend. `parseMatchQuery(value)` valida UUID. | RF-001, RF-002, RF-006–RF-008, RF-012, RF-014 |
| `frontend/app/utils/publicShare.ts` (nuevo) | Pura: `shareStrategy(capabilities)` → `native` / `clipboard` / `manual`; `shareText(...)`. | RF-011 |
| `frontend/app/components/public/PublicShareButton.vue` (nuevo) | Botón «Compartir»: `navigator.share` → `navigator.clipboard.writeText` → campo de solo lectura seleccionado para copia manual; región `aria-live="polite"` con el resultado; cancelar la hoja nativa no muestra error. | RF-011, RNF-005 |
| `frontend/app/pages/index.vue` | `useHead` con `homeHead`. | RF-002 |
| `frontend/app/pages/tournaments/[id].vue` | `useHead` con `tournamentHead` o, si `?match=` es válido y compartible, `resultHead`. El `useAsyncData` existente añade, solo cuando hay `?match=` válido, la lectura del partido (SSR). Tras hidratar abre la cronología de ese partido con el flujo `openTimeline` existente (foco devuelto al encabezado si no hay disparador). Cerrar el diálogo elimina `match` de la URL con `router.replace`. Botón «Compartir» en la cabecera y en el diálogo de cronología. | RF-001, RF-006, RF-007, RF-011 |
| `frontend/app/pages/players/[id].vue` | `useHead` con `playerHead` (nombre + `tournaments[0]`, que la 038 ya ordena del más reciente al más antiguo con `_recent_first`); `robots: noindex, nofollow`; botón «Compartir». | RF-008, RF-011 |
| `frontend/server/routes/sitemap.xml.ts`, `frontend/server/routes/robots.txt.ts` (nuevos) | Rutas Nitro. El sitemap pagina `GET {apiInternalBase}/tournaments/public?limit=200&offset=…` hasta una página incompleta (tope de seguridad 50 páginas). Cabeceras `Content-Type` correctas y `Cache-Control: public, max-age=600`. | RF-009, RF-010, RNF-001 |
| `frontend/server/utils/seoDocuments.ts` (nuevo) | Puras: `buildSitemap(siteUrl, tournaments)` (XML escapado; sin `<lastmod>` porque la consulta pública no expone fecha de modificación y RF-013 prohíbe añadir campos), `buildRobots(siteUrl)` con `Disallow` para `/workspace`, `/admin`, `/login`, `/auth`, `/account`, `/organization`, `/password`, `/invitations`, `/forbidden`. | RF-009, RF-010 |
| `frontend/app/composables/useI18n.ts` | Claves ES/EN nuevas (`share.*`, `seo.*`). | RF-014 |
| `docker-compose.yml`, `docker-compose.production.yml`, `.env.example` | `NUXT_PUBLIC_SITE_URL` del servicio `web` = `${FRONTEND_BASE_URL:-http://localhost:3000}` / `${FRONTEND_BASE_URL:?FRONTEND_BASE_URL must be set}`. | RF-012 |

## 3. Interfaz

### API (prefijo `/api/v1/tournaments`)

| Método y ruta | Respuesta |
|---|---|
| `GET /public/share-image?lang=es\|en` | PNG de marca. Declarada antes de `/public/{tournament_id}`. |
| `GET /public/{tournament_id}/share-image?lang=es\|en` | PNG del torneo; torneo no visible → 404 «Torneo público no encontrado». |
| `GET /public/{tournament_id}/matches/{match_id}` | `PublicMatchStateResponse` (mismo modelo y claves que la lista, incluida la proyección de 14 claves del suspendido); inexistente u otro torneo → mismo 404 que la cronología. |
| `GET /public/{tournament_id}/matches/{match_id}/share-image?lang=es\|en` | PNG del resultado; no compartible, inexistente, suspendido u otro torneo → el mismo 404. |

- `lang` es un `Literal["es","en"]` (422 si no); ningún parámetro se dibuja.
- Imágenes: `Content-Type: image/png`, `Cache-Control: public, max-age=600`, sin cookies. Si el render lanza excepción se registra sin datos del torneo y se devuelve `brand-fallback.png` con 200 (RNF-002). Los 404 no usan la imagen de respaldo.
- El render es CPU; se ejecuta con `run_in_threadpool` fuera de la transacción (los datos se leen antes y se cierra la lectura, como las fotos de la 038).

### Metadatos generados (torneo)

```
<title>{nombre} | Bracket Craft
<link rel=canonical href={site}/tournaments/{id}>
og:type=website, og:site_name=Bracket Craft, og:locale=es_ES|en_US
og:title, og:description, og:url (=canonical)
og:image={api}/tournaments/public/{id}/share-image?lang={lang}, og:image:width=1200, og:image:height=630, og:image:alt
twitter:card=summary_large_image, twitter:title, twitter:description, twitter:image, twitter:image:alt
```
Resultado: título «{local} {g}–{g} {visitante} · {torneo}», canonical `{site}/tournaments/{id}?match={mid}`, imagen del partido. Jugador: imagen de marca y `robots=noindex, nofollow`.

### Pantallas

- Botón «Compartir» con el sistema de botones existente (`components/ui/`), nombre accesible «Compartir torneo», «Compartir resultado» o «Compartir ficha».

## 4. Decisiones

| Decisión | Alternativa descartada | Motivo |
|---|---|---|
| Render PNG en backend con Pillow | Nitro con `satori` + `@resvg/resvg-js` | El backend ya conoce la proyección pública y la política de compartibles; Pillow es una dependencia madura con ruedas para Python 3.14. satori+resvg añadiría dos dependencias, una nativa, y duplicaría las lecturas en el SSR. |
| Imagen servida desde la API con URL absoluta derivada de `apiBase` + `siteUrl` | Proxy de la imagen por Nitro en el origen del sitio | Evita un salto extra; `NUXT_PUBLIC_API_BASE` ya es configuración explícita (no la cabecera `Host`). |
| Sitemap y `robots.txt` como rutas Nitro en el origen del sitio | Generarlos en la API | Deben vivir en el origen público para que los buscadores los acepten sin configuración del proxy. |
| Lectura de un partido por id | Filtrar la lista paginada en el SSR | La lista puede tener cientos de partidos; el endpoint reutiliza la misma consulta y modelo, sin campos nuevos. |
| Sin `<lastmod>` | Añadir `updated_at` a la proyección pública | RF-013: solo campos ya públicos; la spec lo admite («cuando exista»). |
| Fuente Archivo TTF vendorizada | Fuentes del sistema del contenedor | Resultado determinista e idéntico en CI y producción. Limitación: los caracteres sin glifo en Archivo (p. ej. CJK) se dibujan con el glifo de sustitución sin romper la imagen. |

## 5. Exposición pública

- Imagen de torneo: `name`, `season`, `status` (ya en `PublicTournamentSummaryResponse`).
- Imagen de resultado: nombre del torneo, `home_team_name`, `away_team_name`, `home_score`, `away_score`, `home_penalties`, `away_penalties` (ya en `PublicMatchResponse`). Sin escudos ni fotos.
- Metadatos de jugador: `first_name`, `last_name`, `tournaments[0].tournament_name` (ya en la ficha 038). Sin `photo_url`.
- Ninguno incluye documentos ni fechas de nacimiento; las fotos quedan fuera aunque haya consentimiento.

## 6. Estrategia de tests

- **Backend puro** (`test_share_image.py`, `test_share_policy.py`): PNG válido 1200×630; recorte con «…» de nombres largos, acentos y CJK sin excepción; etiquetas ES/EN; penaltis solo si existen; contraste ≥ 4.5:1; política de compartibles por estado y equipos.
- **Backend con BD** (`test_public_share.py`, `RUN_DATABASE_TESTS=1`): 200 + PNG + caché para torneo visible y resultado final/walkover; 404 idéntico para torneo oculto, versión no publicada, partido de otro torneo, programado, en juego, suspendido y con equipo sin definir; endpoint de partido igual a la fila de la lista (incluido el suspendido de 14 claves); fallo simulado del render → respaldo 200; `lang` inválido → 422; aislamiento entre organizaciones.
- **Frontend unit** (`public-seo.test.ts`, `public-share.test.ts`, `seo-documents.test.ts`): metadatos exactos, URL absolutas con `apiBase` absoluta y relativa, `noindex` en jugador y ausencia de foto, `?match=` inválido → metadatos de torneo, XML escapado y sin `lastmod`, `robots` con todas las rutas privadas, estrategia de compartir.
- **E2E** (`e2e/public-seo.spec.ts`, proyecto `public`, pila real con datos demo): HTML del SSR con `request.get` (sin JavaScript) para inicio, torneo y enlace de partido; `/sitemap.xml` con los torneos públicos demo y sin fichas; `/robots.txt`; el enlace de partido abre la cronología; «Compartir» por teclado con portapapeles concedido y con copia manual; axe sin violaciones en ambos temas a 1440 y 390 px.

## 7. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1–2.2 RLS y sin `BYPASSRLS` | Sí | Lecturas con `set_rls_context(org del torneo visible, None)` como la 037; sin rol nuevo. |
| §2.3 Lo publicado es inmutable | Sí | Solo lecturas. |
| §2.4 Esquema append-only | No | Sin migraciones. |
| §2.5 Proyección mínima | Sí | §5: solo campos ya públicos; sin fotos, documentos ni fechas de nacimiento; suspendido sin imagen. |
| §2.6 Sin secretos por defecto | Sí | `NUXT_PUBLIC_SITE_URL` no es secreto; producción exige `FRONTEND_BASE_URL` con `:?`. |
| §2.7 Administración separada | No | Sin cambios en `/admin`. |
| §2.8 Verificación | Sí | §6 y CI 7/7 antes de cerrar cada bloque. |
| §2.9 Código de desarrollo fuera de producción | Sí | El E2E usa los datos demo solo en la pila de desarrollo. |
| §3.2 Módulo y router | Sí | Rutas en el router público existente, ya registrado en `main.py`. |
| §3.3 `useApi.ts` en llamadas HTTP | Sí, con excepción acotada | Las páginas usan `useApi`. **Excepción (§5.1):** `server/routes/sitemap.xml.ts` llama a la API con `$fetch` porque `useApi` es un composable de Vue no disponible en rutas Nitro; la lectura es anónima, sin cookies, organización ni CSRF, y usa `apiInternalBase`. Responsable: autor del bloque B; permanente; requiere tu aprobación explícita como revisor. |
| §3.4 Defaults solo en `.env.example`; auditorías | Sí | Default de desarrollo en `.env.example` y Compose de desarrollo; `pip-audit` y Trivy con Pillow. |
| §4 Todos los cambios | Sí | Tests nuevos; README, AGENTS, manual e informe actualizados. |
| §4 API/backend | Sí | Endpoints públicos sin campos sensibles; `pytest -q` y `compileall`. |
| §4 Frontend | Sí | `pnpm test`, `typecheck`, `lint`, `build`. |
| §4 Infraestructura | Sí | `docker compose config -q` en ambos perfiles. |
| §4 Dependencias | Sí | `requirements.txt` fijado; `pip-audit` limpio. |
