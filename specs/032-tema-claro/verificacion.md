# Verificación 032 — PR C, aceptación local

Fecha: 2026-11-11. Base `origin/main=aedbb92740def2a334c5499d454b1162aa6811c3`, después de #53/#54; rama `devin/1794431684-spec-032-aceptacion`.

**T1–T9 implementadas. T10 sigue pendiente de CI del PR C y aprobación del usuario.** No se declara cerrada la spec ni se abre PR. El resultado local no sustituye el gate del evento pull_request. Las 21 public-polish se conservan, no se repitieron localmente en C; su ejecución conjunta y el recuento del job quedan pendientes.

## 1. Alcance y TDD

- Sin cambios de app, Nuxt, backend, API, permisos, reglas ni campos públicos en C. `frontend/app` coincide con main y byte a byte con el runtime de capturas. Axe 4.10.3 es únicamente devDependency; no se añade dependencia PNG.
- T7 rojo: módulo comparador ausente; luego dos tests de igualdad, un píxel fuera/dentro de R, R vacía, dimensiones/canales inválidos y R alterada. Verde sin tolerancias.
- T8 rojo: guardia de selección CI falló antes de incorporar los nuevos archivos al testMatch. Luego selección/cookies/SSR/estado y regresión de artefactos compactos verdes. Se mantienen los proyectos y veredictos existentes, sin retries.
- T9: el primer fixture directo llegó al 404 SSR y axe encontró falta de h1; se corrigió el arnés, no la app. Las rutas Playwright solo controlan cliente: navegar tras hidratar hacia el fixture propio. La foto lazy 404 exigía esperar sus iniciales; se desplaza una fila estable, no una imagen que desaparece. No se excluyen nodos/reglas para resolver estos fallos.

## 2. Aceptación persistente y CI

`theme-public.spec.ts`: doce escenarios; `theme-workspace.spec.ts`: tres. Se añaden a public/workspace sin retirar realtime, las 21 public-polish ni operation-flow. `playwright test --list` imprime `Total: 41 tests in 8 files` (selección, no resultado CI).

Cobertura a 1440×900, 390×844 y 800×900:

- Selector nativo, nombre accesible, ES/EN, teclado, IDs únicos y valores dark/light/system.
- Cookie anual: Path=/, SameSite=Lax y expiración dentro del margen temporal de cinco segundos. Lectura/SSR sin Set-Cookie de tema; visita inicial no crea preferencia. Inválida da oscuro sin crear ni reparar cookie, no elimina una cookie entrante inválida. Bloqueo lanza SecurityError al escribir: el estado reactivo sigue funcionando sin persistencia.
- Recarga y reapertura del contexto con estado recuperable; Sistema sigue los cambios de media. No se observan peticiones API añadidas por seleccionar tema.
- Formulario y nodo original, foco, scroll, filtro de fase y modal/segmento sobreviven; el hueco transparente del flotante deja pasar el clic. Workspace conserva usuario/cookie y ruta tras recargar; solicitudes SSR concurrentes opuestas permanecen aisladas.
- SSR inicial claro comprueba data-theme, theme-color y ausencia de escrituras. addInitScript observa rAF y PerformanceObserver paint antes de navegar; los módulos de hidratación se retienen hasta tener ≥30 muestras claras y first-contentful-paint. CPU ×1/×4; ninguna muestra opuesta antes ni durante hidratación, token canvas claro y cero warnings de divergencia. No basta con esperar mounted.
- Último artefacto: CPU×1 **54 frames, 6 con app creada, 0 oscuros**; CPU×4 **60 frames, 7 con app creada, 0 oscuros**. La app creada es la señal del muestreo; además se espera isHydrating=false y dos rAF antes de detenerlo. JSON `theme-initial-{frames,paints}-cpu-*.json`.

Fixtures públicos 032 derivados de contratos públicos, IDs/nombre propios, sin escrituras de negocio. Cada contexto se cierra y elimina sus rutas/datos en memoria. Workspace usa lista vacía propia, query de paginación interceptada y navegación CSR para no heredar la lista SSR real. Esto no sustituye la revisión local de Workspace con datos reales (§4).

JSON de axe/frames compactos en `frontend/e2e-report/theme-*.json` mediante el escritor de artefactos existente, que el job ya publica. Sin HTML completo, tokens, cookies, cabeceras, auth state, trace ni video; capturas automáticas Playwright desactivadas. `.auth/` permanece ignorado y no se publica.

## 3. RGBA exacto local, no CI

Arnés versionado: `theme-capture.spec.ts`, `themeRgbaManifest.ts`, `theme-audit.spec.ts`, `themeRgba.ts` y `theme-audit.config.ts`. Manifiesto de captura registra clave/ruta/superficie/locale/viewport/browser y R **antes** del PNG/diff. El generador rechaza manifiestos vacíos/incompatibles y escribe exclusivamente un archivo nuevo (`wx`); el comparador valida SHA-256 del manifiesto y de ambos PNG, dimensiones/canales y R congelada. Cuenta cambios dentro/fuera y delta máximo fuera, incluyendo alfa. Las cajas CSS se redondean hacia fuera a píxeles; nunca se derivan de los píxeles diferentes.

Perfil: Chromium 156 de Playwright 1.64.1, proceso independiente por caso, software/sRGB, disable-gpu/disable-gpu-rasterization/disable-partial-raster, force-color-profile=srgb, factor nativo 2 y DPR emulado 1, UTC, reduced motion, fuentes locales listas, dos rAF, scroll 0 y sin animaciones/transiciones/caret. Esperar también que terminen las clases Vue enter/leave; ocultar solo DevTools, no nodos de app. No se altera R ni se toleran deltas de 1.

Matriz: portada/detalle/Workspace/operación × ES/EN × tres tamaños, más menús Workspace/operación abiertos a 390 (28 pares). R pública = grupo flotante; Workspace escritorio/tableta = fila de preferencias; móvil abierto = menú completo; móvil cerrado = null, comparación de toda la imagen.

```text
28 pares: inside=0, outside=0, maxDeltaOutside=0 en todos
1 passed (1.6s)
THEME_RGBA_SHA256=b9391b2e25349e445be562c1b0385d8d4d77bba90c4ed1717350b725488a4725
```

PNG/manifiestos finales: `/home/ubuntu/ui-audit/032-before/stable/` y `032-after/stable/`; casos congelados y salida: `032-pr/rgba-stable.{json,log}`, mapas anotados `032-pr/diff-*.png` (R cian; diferencias vacías). C no cambia inputs de aplicación respecto de main; las dos capturas usan ese mismo runtime, no dos builds distintas. Se conservan los controles previos de PR B (18 comparaciones main/main y rama/rama completas a 0; 14 main/rama a 0 fuera de R) y PR A; véanse `verificacion-pr-{a,b}.md`. No se sobrescriben esas referencias.

**Intento descartado conservado:** `032-{before,after}/final/` y `032-pr/rgba.log`. Workspace ES 800 difirió 502380 píxeles, delta 232: una captura mostraba tarjetas en disposición transitoria y otra el grid final. El mock privado no incluía `?limit=50&offset=0` (ver `stores/tournaments.ts`) y la navegación directa heredaba datos reales SSR. Se corrige solo el arnés: fixture privado con query, navegación cliente con vacío verificado y espera de clases de transición. No se atribuye definitivamente cada transición observada a un único evento de sesión. Las R se conservaron y la matriz completa nueva queda a 0.

**No se acredita determinismo entre ejecuciones del runner CI. Por ello RGBA no entra en el job; se mantiene reproducible y sin tolerancias.**

### Reproducción

Desde frontend, mismo runtime, fixtures y sesión de desarrollo local en ambos extremos. Instalar con pnpm frozen-lockfile. Si el host carece de Chromium, usar la imagen oficial con red host y montar el repo y el directorio de evidencias a las mismas rutas absolutas. HOME debe ser escribible por el UID del runner.

```sh
export THEME_CAPTURE_URL=http://localhost:3000
# Partido programado demo; sustituir por ID local válido, nunca crear datos en producción.
export THEME_OPERATION_PATH=/workspace/matches/107ed672-3299-4121-81ca-6dfb44299156
THEME_CAPTURE_OUTPUT=/home/ubuntu/ui-audit/032-before/nueva pnpm exec playwright test --config e2e/theme-audit.config.ts --grep @capture
THEME_CAPTURE_OUTPUT=/home/ubuntu/ui-audit/032-after/nueva pnpm exec playwright test --config e2e/theme-audit.config.ts --grep @capture
node --experimental-strip-types e2e/themeRgbaManifest.ts /home/ubuntu/ui-audit/032-before/nueva /home/ubuntu/ui-audit/032-after/nueva /home/ubuntu/ui-audit/032-pr/nueva.json
# Conservar el digest impreso antes del diff; no recalcularlo para aceptar una referencia modificada.
export THEME_RGBA_MANIFEST=/home/ubuntu/ui-audit/032-pr/nueva.json
export THEME_RGBA_SHA256='digest-impreso'
pnpm exec playwright test --config e2e/theme-audit.config.ts --grep @visual
```

## 4. Axe y revisión visual

Axe-core **4.10.3**, sin exclusiones de aplicación:

| Matriz | Ejecuciones | Resultado |
|---|---:|---|
| CI persistente: portada, detalle, estadísticas, campo/modal y Workspace; ambos temas, tres tamaños | 30 | 0 violaciones |
| Local real: listado Workspace, miembros, configuración, calendario, plantillas, operación programada/en vivo/cerrada; ambos temas, tres tamaños | 48 | 0 violaciones; overflow=False |
| Admin de plataforma y alta de organización sin organización; claro, tres tamaños | 6 | 0 violaciones; overflow=False |

Total representativo: **84 ejecuciones, 0 violaciones**; no se suman las repeticiones de depuración. Datos: `032-c-pr/private-surfaces/results.json`, `roles-review.json` y logs E2E. Las repeticiones posteriores de Workspace verifican además el vacío cliente controlado. Se conservan los 29 pares oscuros y 158 claros unitarios, CSS compilado y composiciones efectivas de PR B. Axe no sustituye esa cobertura: `--color-line` sigue decorativo; textos T≥4.5 y señales esenciales ≥3 en los roles auditados.

Revisión renderizada de tarjetas, tablas, iniciales, disabled, etiquetas/estado, campo verde y overlays de la matriz anterior, sin cambiar app. Login se ejercita en SSR/primer pintado; referencia visual amplia de acceso y público conservada en B. No se reclaman todos los errores HTTP, combinaciones de permisos, estados hover de todos los controles, invitaciones ni dispositivos físicos/lectores de pantalla. Las incompletas de axe se registran, no se convierten en aprobaciones universales de contraste.

Las dos vistas antes inaccesibles por permisos **sí renderizan en C**, no se cuentan redirecciones:

- `/admin`: cuenta sintética con fila platform_admins/role_code=platform_admin; encabezado y tarjetas de administración reales.
- `/organization`: cuenta sintética sin membresía; formulario de nombre/identificador y acciones Crear/Ahora no reales.
- Capturas revisadas: `/home/ubuntu/ui-audit/032-c-pr/admin-light.png` y `organization-light.png`, más variantes 390/800. Ocho superficies privadas con comparativas oscuras/claras en `private-surfaces/`; ningún overflow de documento.

## 5. Gates y limpieza

Node 24.22.2, pnpm 12.12.1. Salidas locales (logs `032-c-pr/`):

```text
pnpm test (test-final.log)
ℹ tests 902
ℹ pass 901
ℹ fail 0
ℹ skipped 1

pnpm run typecheck (typecheck.log)
$ nuxt prepare && vue-tsc --noEmit
◆ Types generated in .nuxt.

pnpm run lint (lint.log)
$ nuxt prepare && eslint .
◆ Types generated in .nuxt.

pnpm run build (build.log)
◆ ✨ Build complete in 8.94s!

pnpm run typecheck:e2e (typecheck-e2e.log)
$ tsc -p e2e/tsconfig.json

nueva aceptación (theme-complete.log)
16 passed (1.1m)
artefactos JSON, subgrupo afectado (theme-json-evidence.log)
9 passed (34.1s)
FCP/sesión reforzados (theme-paints-session.log)
6 passed (14.2s)
fixture Workspace propio, subgrupo afectado (theme-workspace-own.log)
5 passed (18.5s)
muestreo hasta hidratar/artefactos definitivos (theme-artifacts-final.log)
3 passed (5.7s)

operation-flow (ejecución combinada anterior)
✓ [operation-flow] operación y cierre: reglas, avisos, bloqueos y retiro lógico (36.3s)
```

Cada subgrupo se repite por cambios en sus inputs, no para ocultar flakes. Las primeras ejecuciones de tema fallaron por navegación SSR/fixture, imagen lazy y selector aún no visible; se conservan los logs. La ejecución combinada no se presenta globalmente verde: operation-flow sí pasó y su artefacto declara passed/30 transiciones, los fallos de tema se corrigieron después.

Retirados por IDs acotados: dos usuarios temporales y el rol admin/sus sesiones; un torneo de operation-flow, dos equipos propios y dos jugadores propios, incluidos datos derivados. Sin borrar fixtures ajenos ni modificar datos demo. Salidas `roles-cleanup.log` y `operation-cleanup.log`:

```text
temporary_users | temporary_admins | temporary_sessions
              0 |                0 |                  0
temporary_tournaments | temporary_teams | temporary_players
                    0 |               0 |                 0
```

Se corrigió el entorno local del navegador: HOME=/home/pwuser no escribible por el UID ubuntu producía `Fontconfig error: No writable cache directories`; HOME escribible en `032-c-pr/browser-home`, sin cambiar CI. No se silenció el aviso ni se añadieron permisos globales.

## 6. Cobertura RF y cierre

| Requisito | Evidencia |
|---|---|
| RF-001 | Selector nativo/etiqueta/ES-EN/teclado/IDs, T4 y aceptación tres tamaños |
| RF-002 | Default/inválida oscuros, elección explícita; SSR concurrente y T1–T3 |
| RF-003 | Sistema/media sin recarga, público/modal y Workspace |
| RF-004 | Identidad/formulario/foco/scroll/fase/modal/segmento y cero API extra |
| RF-005 | Cookie/SSR, FCP y frames antes/durante hidratación CPU×1/×4 |
| RF-006 | Año/path/SameSite, recarga/reapertura, excepción de escritura y fallback |
| RF-007 | LY-1, geometría B, controles por teclado y tres tamaños; roles admin reales |
| RF-008 | 158 pares claros, CSS compilado y 84 axe; límites de estados en §4 |
| RF-009 | 28 RGBA completos C, históricos A/B sin ampliar R; escala y semántica intactas |
| RF-010 | Público/Workspace/operación y roles locales; matriz/alcance visual en §4 |
| RF-011 | Fixture foto 404→iniciales y tests de superficies; bytes/URLs no modificados |
| RF-012 | Campo/modal y segmento, gráficos/bracket B; reglas/posiciones sin cambios |
| RF-013 | color-scheme/theme-color SSR y después de cambiar/hidratar |
| RF-014 | Preferencia anónima, peticiones aisladas y sesión Workspace conservada |
| RF-015 | Sin escritura por visita/inválida; cookie solo enum UI, sin backend |

Criterios de finalización 1–5: materializados con la cobertura acotada anterior; criterio 6 **pendiente de CI y aprobación humana**. RNF-001/002 respaldados por RGBA/axe/contraste; RNF-003 por fuentes/movimiento/foco; RNF-004/005 sin app/backend/CSP ni anti-FOUC nuevo; RNF-006 pendiente del gate global. No se certifican combinaciones no ejecutadas.

### Constitución §4

| Criterio | Resultado |
|---|---|
| Cambio comprobado, sin debilitar suites | TDD y cinco gates locales; selección 41 conservada; CI pendiente |
| Frontend tests/typecheck/build y useApi | Cinco gates; sin app ni nuevas llamadas de negocio |
| Seguridad/privacidad | Sin secretos/headers/cookies/HTML privado en Git/JSON; preferencias UI opcionales |
| Dependencias/lockfiles | axe 4.10.3 solo desarrollo, lock actualizado; security CI pendiente |
| Documentación observable | Spec/tasks/verificación, MEMORY, AGENTS, manual e informe sincronizados |
| BD/RLS/backend/infra | Sin cambios de código/esquema/migración/despliegue; fixtures solo desarrollo, retirados |
| Revisión y cierre | T10 sin marcar; falta CI y aprobación del usuario. Sin excepción constitucional |
