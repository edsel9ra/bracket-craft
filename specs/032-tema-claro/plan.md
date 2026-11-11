# Plan 032 — Tema claro opcional

Fecha: 2026-11-11. **Plan y tareas aprobados por el usuario; fases cerradas.** PR A (T1–T3) autorizado; PR B/C aún no implementados. Spec/clarificación aprobadas (D1–D4 A). No backend, API, permisos, datos de negocio, dependencias ni política CSP nuevos.

## 1. Alcance e interfaz

- Tres preferencias: `dark`, `light`, `system`; ausencia o valor inválido equivale a oscuro, incluso con sistema claro. Sistema es una elección explícita, no el default.
- Selector junto al idioma en el flotante público, cabecera desktop y menú móvil del Workspace; el shell de administración participa. Acceso/invitaciones/cuenta/organización/errores reciben el tema global y el selector que corresponde a su shell.
- Todas las superficies reciben tema claro, salvo el césped como isla verde de contraste propio. No cambiar tipografía Archivo, escalas 029, geometría ni contenido. Solo R del selector puede diferir en oscuro.
- **Endpoints/modelos/campos nuevos: cero.** La elección no llama a la API. `useApi.ts` sigue siendo la única vía HTTP, sin cambios en sus contratos. No se modifican cookies de sesión/organización/CSRF, permisos, reglas, outbox, resultados ni matriz pública. La cookie de apariencia es estado UI opcional, no una identidad ni una escritura de negocio.
- No se amplían proyecciones públicas: siguen excluidos documentos, nacimiento, edad, logo heredado en público, claves de almacenamiento y datos administrativos; fotos solo conforme al consentimiento vigente y formación solo publicada. El tema no decide acceso.

## 2. Archivos y responsabilidades previstas

Rutas relativas a `frontend/`, salvo documentación. Nombres nuevos propuestos, no archivos creados por este plan; cada archivo nuevo tendrá menos de 600 líneas.

| Archivo/símbolo | Responsabilidad |
|---|---|
| `app/utils/theme.ts` | `normalizeTheme`, descriptores de head/color-scheme/metadatos; constantes de cookie y fallback. Funciones puras. |
| `app/composables/useTheme.ts` | Estado por solicitud/cliente, lectura de cookie y acción explícita de elección; sin globals mutables ni red. |
| `app/app.vue`, `nuxt.config.ts` | Aplicar head antes de SSR; eliminar únicamente el theme-color estático que duplicaría el dinámico. No tocar cabeceras/routeRules. |
| `app/assets/css/tokens.css`, `app/utils/designTokens.ts` | Paletas dark/light y espejo de variables, con 23 roles actuales y roles de isla separados. Oscuro actual conservado. |
| `app/assets/css/main.css` | Resolución CSS del tema, color-scheme y ajustes claros de estados compartidos. |
| `app/components/ThemeSwitcher.vue` | Selector etiquetado, i18n, IDs únicos y teclado. Sin estado de apariencia duplicado. |
| `app/components/WorkspaceShell.vue`, `app/app.vue` | Solo colocar el selector en ubicaciones aprobadas, sin desplazar idioma u otros controles. |
| `app/composables/useI18n.ts` | Claves ES/EN de apariencia, Claro/Oscuro/Sistema. No cambiar textos existentes. |
| `app/components/TeamCrest.vue`, `public/PublicPlayerStatsTable.vue` | Iniciales claras legibles; conservar imágenes y su contrato. |
| `app/components/ui/Button.vue`, `ui/ConfirmDialog.vue`, `public/PublicLineupModal.vue` | Disabled, backdrops y elevación exclusivamente claros. |
| `RulesEditor.vue`, asistentes, `components/match/operation.css`, páginas con opacidad disabled | Ajustes claros localizados donde el contenedor atenúe texto; no normalización general de estilos. |
| `app/components/public/{MatchPitch,TeamPitch}.vue` | Roles propios dentro del terreno; geometría y alternativa textual intactas. |
| `public/PublicBracketConnections.vue`, `ui/HorizontalScroll.vue` | Verificar adaptación por tokens, conservando currentColor, relaciones, foco y overflow. Cambiar solo si el render claro lo exige. |
| `tests/theme*.test.ts`, `tests/design-{contrast,scales}.test.ts` | Casos puros, espejo doble, 29 pares oscuros conservados + 158 claros y control de literales. |
| `e2e/theme-{public,workspace}.spec.ts`, helpers separados | SSR/primer pintado, persistencia, navegación, teclado y aislamiento; integración CI. |
| `e2e/theme-audit.config.ts`, `e2e/theme-audit.spec.ts`, helpers | Auditoría manual reproducible de píxeles/axe en ambos temas, fuera del veredicto realtime. |
| `playwright.config.ts` | Solo ampliar testMatch de public/workspace; conservar dependencias, reporter, retries=0, realtime y operation-flow. |
| `docs/manual-usuario.md`, `docs/inspeccion-accesibilidad.md`, `AGENTS.md`, `MEMORY.md`, spec/tasks/verificación | Actualizar al verificar/cerrar, no anticipar resultados. |

## 3. Preferencia, SSR y cambio reactivo

Cookie propuesta `bc_theme`: valores `dark|light|system`, `path=/`, `maxAge=31536000`, SameSite=Lax, Secure fuera de desarrollo, sin Domain y accesible a cliente para la elección. No HttpOnly: no es credencial. Ausencia representada por null, no por escribir `dark` como default.

- Leer/normalizar no escribe, no repara valores inválidos, no refresca la duración ni emite Set-Cookie de apariencia al visitar. Solo `setTheme` llamado por una elección explícita modifica la cookie. Elegir Oscuro por primera vez también es una elección persistible.
- `useState` de Nuxt por solicitud y payload de hidratación, nunca variable mutable de módulo. La única persistencia es cookie: `useCookie` readonly sin default para leer y escritura síncrona explícita mediante document.cookie dentro de setTheme, atrapando excepciones. Esto evita escrituras automáticas del lector/refresh y permite recuperar un bloqueo real del setter sin depender de un watcher asíncrono. Si falla, el estado reactivo permite seguir navegando y una visita nueva vuelve al oscuro. No fallback localStorage silencioso.
- `app.vue` obtiene la preferencia antes de renderizar y ejecuta `useHead` reactivo: `<html data-theme="dark|light|system">`. Los componentes consumen el mismo estado; no cambian clases del body en mounted ni usan un script anti-FOUC adicional.
- Root sin preferencia o `dark`: valores oscuros originales. `light`: overrides claros. `system`: mismos overrides mediante `prefers-color-scheme: light`, con fallback CSS oscuro. El atributo y la etiqueta Sistema son idénticos en SSR/cliente: no se serializa una suposición del servidor sobre matchMedia.
- `color-scheme` es dark/light para elecciones explícitas; para Sistema se resuelve por la misma media query antes del pintado. Los cambios del sistema solo afectan la preferencia Sistema.
- Head: theme-color oscuro `#0c0f0c`, claro `#f5f7ef`; en Sistema, metadatos con media por esquema y claves diferenciadas para evitar deduplicación accidental. Quitar el meta fijo anterior, no añadir dos metas activos incompatibles. Probar el resultado en el motor soportado y el fallback oscuro.
- Cambiar preferencia actualiza estado/head/CSS, sin router.push, reload, key de NuxtPage, remount de formularios o fetch. No observar el sistema para sobrescribir una elección explícita.
- CSP existente no tiene script-src ni default-src, pero esta solución no necesita inline anti-parpadeo ni modificaciones de política. No introducir caché HTML compartida; si ya existiera al implementar, no puede reutilizar una preferencia entre visitantes.

### Pseudocódigo puro y adaptador

```text
normalizeTheme(raw):
  if raw in {dark, light, system}: return raw
  return dark

describeTheme(preference):
  p = normalizeTheme(preference)
  return htmlAttribute(p), cssResolution(p), browserThemeMetadata(p)

initialize(requestCookie, requestScopedState):
  state = normalizeTheme(requestCookie)  // no escritura, mismo payload al hidratar
  head = describeTheme(state)

choose(next, state, cookieAdapter):
  if next not in {dark, light, system}: return false
  state = next
  cookieAdapter.write(next, annualOptions)  // solo desde la acción del usuario
  return true
```

Funciones de paleta, composición, descriptores y comparación reciben todos sus datos; no leen DOM, matchMedia, red ni reloj. Si una comprobación de expiración necesita fecha, recibe `now` explícito. Los efectos (cookie/head/DOM/medición) quedan en adaptadores con limpieza al desmontar.

## 4. Paletas, contraste y piezas especiales

- Mantener `PALETTE` como alias compatible de `PALETTE_DARK`, con los 23 valores oscuros actuales idénticos; añadir `PALETTE_LIGHT` conforme a la tabla de auditoría y descriptores por tema. Mantener también compatibilidad de `CSS_TOKENS` para consumidores oscuros; exponer mapas por tema para comprobar todos los overrides. Los roles adicionales de isla tienen espejo propio, no redefinen el export oscuro heredado.
- El test actual parsea todas las declaraciones en un solo objeto: al añadir scopes claros perdería contexto. Cambiarlo a comparación **por scope/tema**, verificando claves, valores, ausencia de overrides no registrados y conservación literal de la paleta oscura; no sustituirlo por una comprobación parcial.
- Ampliar el guardián de tokens a ambos conjuntos autorizados y hsl/hsla, sin permitir literales fuera de tokens ni añadir exclusiones genéricas. Los alias de isla también se registran; su versión oscura reproduce exactamente los colores originales.
- Convertir la matriz numerada de auditoría en datos de prueba trazables (IDs 1–158). Recalcular cada ratio, no copiar el ratio como veredicto: 40 textos base, 80 tintes 8/10%, 6 botones, 5 iniciales, 9 textos de isla, 10 bordes, 2 líneas opacas y 6 compuestas. **140 textos ≥4.5:1, 18 señales ≥3:1**, además de los 29 pares oscuros existentes. Añadir cualquier par efectivo nuevo sin retirar los originales.
- Usar luminancia sRGB existente; composición alfa sobre fondo conocido y cuantización del cálculo compatibles con la auditoría. Tests de extremos, entrada inválida y valores frontera. Los degradados requieren evaluar sus zonas desfavorables y medir el render final: los 158 pares no son una exención.
- Iniciales TeamCrest/estadísticas: avatar-ink claro `#182218` sobre highlight 6% compuesto, no blanco heredado. Imágenes originales sin filtros/inversión ni cambios de URL. Césped conserva avatares propios.
- Disabled claro: evitar opacidad del contenedor que baje el texto; mantener tinta/muted opacos, fondo/borde con semántica deshabilitada y atributos/interacción actuales. Revisar también busy, fieldset, file-picker y acciones de RulesEditor/login/organización/admin/plantillas/Workspace. No cambiar esos estilos en oscuro.
- Backdrops claros: usar velo basado en shadow con alfa explícito y no multiplicar accidentalmente alfa por la opacidad vieja; dialog/panel/texto permanecen claros. Conservar el backdrop oscuro byte a byte en sus reglas efectivas y mantener trap/Escape/retorno de foco.
- Campo: césped `#315b35/#38673b`, líneas `#ecffce` y player `#172218`; isla clara con tinta `#f4f0e7`, acento `#d4f36a`, visitante `#ffd18a` (mínimo 4.648:1). En oscuro mantener el ámbar original `#ffcb7a`. Limitar roles de isla al rectángulo del terreno: encabezado, banco, modal y textual usan claro. No variar coordenadas, tamaños, alineación o contenido.
- Bracket sigue SVG decorativo currentColor/muted y texto de relación existente; scrollbar, pista/sticky, selección, autofill y controles nativos deben seguir el tema. Ajustes de elevación/tintes, si hacen falta, solo dentro del scope claro.

## 5. Selector y región R

- Reutilizar el modelo de select nativo etiquetado del idioma: tres opciones ES/EN, label visible donde quepa y nombre accesible siempre; ID único por instancia (cabecera y menú móvil coexisten en DOM). Flechas/Enter/Escape/Tab según control nativo, sin key handlers globales ni cambios de foco al aplicar.
- Ubicaciones: público junto al flotante existente; Workspace/admin junto al idioma de cabecera y del menú desplegado. Solo una instancia visible por ubicación activa. La selección sobrevive al cambio de idioma.
- **No basta insertar un hijo flex/grid**: podría desplazar organización, idioma, cuenta o cambiar altura de menú. Anclar el nuevo control en espacio disponible junto al idioma, con variante compacta si procede, sin reservar espacio ni alterar métricas del contenido existente. No reutilizar la variante inline del idioma público si cambia su aspecto.
- R cumple la definición de spec: caja de control/etiqueta más halo máximo 8 px, cerrada/foco ≤192×80 px; desplegada ≤192×200 px cuando se compare ese estado. Coordenadas enteras y estado documentados por viewport/fixture antes de calcular el diff; PNG anotado sin editar, JSON de rectángulo y límites. Popups nativos fuera del bitmap de página se ejercitan por teclado; no se inventa un rectángulo DOM para ellos ni se usa su ausencia como prueba visual de ese popup.
- R no contiene idioma ni otro control preexistente; no es toda la cabecera, la fila de controles o el flotante antiguo. Instancias ocultas aportan R vacío. Verificar cajas del idioma/organización/cuenta/contenido contra la referencia, además de los píxeles.
- **Riesgo geométrico explícito:** el header usa flex y el menú móvil grid; puede no haber hueco sin mover elementos. Si no cabe un selector accesible dentro de estos límites, se detiene esa integración y se consulta un ajuste de diseño; no se amplía R ni se introduce un desplazamiento no autorizado. No se declara resuelto por no haber renderizado aún el control.

## 6. Verificación de 0 píxeles

1. Referencia frontend inmutable: base auditada `8993a393c4d64229bd5a16dce6d5157c37d4455c`, en worktree/stack de referencia separado; candidato con mismo backend/fixtures. Registrar hash del árbol frontend. Si hay cambios upstream antes de implementar, distinguirlos y acordar referencia antes de medir, no rebaselinar por fallos del tema.
2. Mismo Chromium/versión, SO, escala de dispositivo, fuentes cargadas, viewport, reloj, datos y estado de interacción. Fijar respuestas y actualizaciones dinámicas de forma idéntica en ambos; detener animaciones en ambos, no enmascarar marcadores, fechas o regiones fuera de R.
3. Matriz de 1440×900, 390×844 y 800×900, ES/EN, oscuro sin cookie y explícito; menú móvil cerrado/abierto, cuenta, tablas con scroll/sticky, formularios/errores, diálogos, bracket y formaciones. Comparar viewport y superficies desplazadas representativas; 0 es por captura, no media global.
4. Capturar PNG original de ambos, manifiesto R previamente acotado y diferencia anotada. Decodificar ambos a RGBA sRGB mediante Canvas en una página aislada del mismo Chromium; comparar bytes de cada píxel fuera de R con función pura. No añadir dependencia PNG ni importar módulos internos de Playwright. No comparar bytes del PNG comprimido como si fueran píxeles.
5. Exigir `differentPixelsOutsideR === 0`, dimensiones iguales, región dentro de límites y cajas antiguas sin cambios. No usar tolerancia de antialias para llamar 0 a diferencias pequeñas. Una prueba del comparador modifica un píxel fuera de R y debe fallar; un cambio solo dentro de R no falla; región fuera de límites/vacía inválida y tamaños distintos producen error.
6. Las regiones se validan contra control real y límites prefijados, no se calculan a partir del diff. Evidencia bajo `/home/ubuntu/ui-audit/032-{before,after,pr}/`, fuera de Git; sin actualizaciones automáticas de referencias para conseguir verde.

## 7. E2E, axe y gates

### Cambio de tema y ausencia de parpadeo

- `theme-public.spec.ts` comparte public con realtime/public-polish y usa storageState vacío; `theme-workspace.spec.ts` comparte workspace con realtime autenticado. Solo ampliar sus testMatch: no añadir un proyecto que el veredicto realtime ignore ni editar runModel/escenarios existentes. Reporter ya acumula todos los tests del proyecto; validar su lista y cantidades nuevas en logs de CI.
- Primera visita sin cookie (sistemas claro y oscuro) siempre oscura; comprobar que no se escribe `bc_theme`. Preferencias desconocidas no se reparan al leer. Elegir Claro/Oscuro/Sistema escribe solo valor permitido, path/SameSite/Secure y duración anual; recarga, navegación y reapertura de contexto con cookie recuperan la elección. Caso bloqueado funciona en memoria y nueva visita vuelve a oscuro.
- Leer solo atributos/metadatos de la respuesta SSR, sin guardar HTML privado completo. Con cookie explícita, bloquear temporalmente los módulos de hidratación y comprobar fondo/color-scheme/head correctos antes de activarlos; después liberar scripts y comprobar que no cambia a otro tema ni hay avisos de hidratación.
- Instrumentación de test con addInitScript antes de navegar: observar primer paint y muestrear atributo/fondo/color-scheme por requestAnimationFrame desde CSS lista hasta después de hidratar. Registrar muestras/tiempos y capturas de primer pintado; ningún frame observado puede resolver al tema opuesto. Fallar si falta observación inicial: un assert tras mounted no demuestra ausencia de FOUC. Repetir con CPU/red ralentizadas y enlace profundo.
- Sistema: emular media antes de navegar, comprobar resolución CSS previa a hidratación y cambio posterior; preferencia explícita no sigue la media. Dos contextos/solicitudes concurrentes con elecciones opuestas no comparten estado.
- Cambiar con formulario modificado/diálogo/scroll/filtro: mismo contenido/foco/estado, sin requests extra por el tema. Conservar los 21 public-polish y operation-flow sin omisiones, y conservar el veredicto realtime.
- Persistir solo métricas, nombres de prueba y valores de presentación; trace/video apagados, sin cookies, cabeceras, tokens, HTML autenticado o `.auth/state.json` en artefactos. No hay fixtures nuevos en backend salvo que una auditoría local justificada los necesite; si los hay, registrar IDs y retirarlos.

### Axe y contraste renderizado

- Configuración de auditoría separada, no seleccionada por el testMatch CI realtime: `theme-audit.config.ts` ejecuta visual y axe manualmente. Reutilizar Playwright existente y el axe-core de auditoría con versión fijada; no añadir dependencia de runtime por el informe.
- Ambos temas, tres viewports y ES/EN del selector; enumerar rutas públicas, login/callback/invitación, cuenta/organización/forbidden, Workspace listado/alta/reglas/equipos/fases/plantillas/calendario/operación, admin y errores soportados. Usar fixtures locales autorizados de todos los estados alcanzables; no dar por auditada una vista que redirige por falta de permiso.
- Incluir tablas con sticky/scroll, vacío/carga/error, disabled/validación, ConfirmDialog y formación gráfica/textual. Oscuro no tiene nuevas violaciones; claro cero violaciones de aplicación. Solo separar DevTools externo; no excluir reglas o nodos de aplicación.
- Contraste de colores efectivos en textos/foco/contornos de cada estado, incluyendo gradientes, iniciales y ambos céspedes. Los 158 pares son un mínimo, no sustituyen el render ni el tratamiento de incomplete de axe.

### Comandos previstos (no ejecutados en esta fase)

Node 24 y pnpm 12.12.1; desde frontend:

```sh
pnpm test
pnpm run typecheck
pnpm run lint
pnpm run build
pnpm run typecheck:e2e
pnpm exec playwright test e2e/theme-public.spec.ts --project public --no-deps
pnpm exec playwright test e2e/theme-workspace.spec.ts --project workspace
pnpm exec playwright test e2e/public-polish.spec.ts --project public --no-deps
pnpm exec playwright test --project operation-flow
pnpm exec playwright test --config e2e/theme-audit.config.ts
```

Mantener backend/frontend/infrastructure/security/e2e de CI verdes y revisión humana antes de cerrar. El E2E de CI requiere PR o push main; un push a rama no lo sustituye. No abrir ni fusionar PR sin encargo. No editar CI salvo necesidad demostrada y autorización de alcance; testMatch permite integrar los nuevos E2E con el job actual.

## 8. Decisiones y alternativas descartadas

| Decisión | Elegida / motivo | Alternativa descartada |
|---|---|---|
| D1 A | Oscuro por defecto: preserva primera visita actual. Sistema disponible solo al elegir. | Seguir al sistema sin elección: cambiaría la experiencia inicial. |
| D2 A | Junto al idioma, excepción única R medida y 0 píxeles fuera. | Preferencias solo por URL/cuenta: peor descubrimiento o excluiría anónimos. Se rechaza también ampliar la máscara a barras completas. |
| D3 A | Cookie anual UI solo al elegir, SSR y cliente coherentes. | localStorage/mounted o script anti-FOUC: segunda ruta de resolución y riesgo de flash. Solo memoria no persiste. |
| D4 A | Todas las vistas, isla verde solo del terreno con etiquetas propias. | Cobertura parcial con saltos oscuros o reinterpretar todo el terreno sin necesidad. |
| Espejo doble | Mantener export oscuro compatible y comprobar scopes de ambos temas. | Sustituir la PALETTE antigua o debilitar el test que detecta overrides. |
| Cero píxeles | RGBA exacto con R limitada y comparación de cajas antiguas. | Umbral porcentual, rebaseline o máscara derivada de fallos. |
| Seguridad | Sin scripts de inicialización extra, ni red/identidad para preferencias. | Relajar CSP, añadir endpoint o guardar tema en cuenta. |

## 9. Cobertura de requisitos

| Requisitos | Pieza / evidencia prevista |
|---|---|
| RF-001/007 | Selector ES/EN, teclado, IDs y ubicaciones; cajas/R, no solapes. |
| RF-002/003 | Funciones puras/default, CSS media, E2E de preferencia explícita/Sistema. |
| RF-004 | Estado reactivo sin remount/red; E2E de formulario/foco/filtros/scroll. |
| RF-005/006 | Cookie/SSR, primer paint con hidratación retenida, persistencia y bloqueo. |
| RF-008 | 29 pares oscuros + 158 claros y adicionales efectivos; axe/render de todos los estados. |
| RF-009, RNF-001 | Capturas RGBA 0 fuera de R y cajas de idioma/resto idénticas, escalas intactas. |
| RF-010 | Matriz completa de vistas, tablas/controles/diálogos en ambos temas. |
| RF-011 | Imágenes sin filtros/cambio de bytes; iniciales medibles con foto ausente/fallida. |
| RF-012 | Campo/isla y SVG con mismos datos/geometría/relaciones/textual. |
| RF-013 | html/head/CSS y metadatos coherentes antes/después de hidratación. |
| RF-014/015 | Sin sesión/red; dos solicitudes/contextos, solo elección escribe cookie. |
| RNF-002/003 | Axe por vista/tamaño/tema, teclado/reduced-motion y ninguna fuente o escala nueva. |
| RNF-004/005/006 | Contratos y CSP intactos, suites CI conservadas y evidencia honesta. |

## 10. Verificación de constitución

Sin excepciones constitucionales. La región R es una precisión de aceptación visual aprobada por el usuario, no una exención de seguridad, accesibilidad o CI. La tabla describe verificaciones futuras, no resultados de esta entrega documental.

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento tenant en BD | Se preserva | No tablas/consultas nuevas; preferencia local no contiene tenant. |
| §2.2 Sin BYPASSRLS | Se preserva | Sin cambios de roles/conexiones/backend. |
| §2.3 Publicado inmutable | Se preserva | Apariencia no modifica resultados, versiones, rank ni relaciones. |
| §2.4 Historial append-only | No cambio | Ninguna migración ni edición de esquema. |
| §2.5 Público mínimo | Sí | 0 campos/endpoints nuevos; imágenes y formación mantienen consentimiento/publicación. |
| §2.6 Sin secretos default productivos | Sí | Cookie UI sin identidad; no variables/secretos nuevos, ni cambios de defaults. |
| §2.7 Admin separada/auditada | Se preserva | Tema no concede acceso ni añade acciones administrativas. |
| §2.8 Nada terminado sin verificar | Sí | TDD, píxeles, 158 pares, axe/E2E/CI y revisión humana antes del cierre. |
| §2.9 Desarrollo fuera de producción | Sí | Fixtures y capturas locales/ignoradas; no seeds ni datos demo nuevos en app. |
| §3.3 HTTP por useApi / público sin sesión | Sí | Preferencia sin fetch; API y guards intactos, visitante anónimo cubierto. |
| §4 CI correspondiente | Sí | Cinco jobs aplicables conservados; nuevos E2E incluidos por testMatch; esperar CI de PR. |
| §4 Sin secretos/datos nuevos | Sí | Solo valor UI opcional; no exportar cookies/headers/auth a evidencias. |
| §4 Documentación observable | Sí | Manual, accesibilidad, AGENTS, MEMORY y verificación al implementar. |
| §4 Pruebas del comportamiento | Sí | Normales/ausencia/inválido/error/bloqueado; SSR, pixel diff, contraste y teclado. |
| §4 BD: migración, RLS, limpio/migrado, sh -n | No | Sin cambios de esquema/scripts de migración. |
| §4 Backend: contexto, routers, pytest/compileall | No cambio específico | No módulos/modelos/rutas; backend CI sigue requerido y público mínimo intacto. |
| §4 Frontend: useApi, tests/typecheck/build | Sí | Cinco gates frontend indicados y E2E; no omitir lint ni typecheck:e2e. |
| §4 Infra/deploy: compose/defaults | No cambio específico | Sin compose/proxy/despliegue; infrastructure CI se conserva. |
| §4 Dependencias/lockfiles/auditoría | No cambio | Usar Playwright/Canvas y utilidades existentes, sin dependencia PNG ni runtime nueva; security CI se conserva. |
