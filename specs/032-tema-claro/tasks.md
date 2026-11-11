# Tareas 032 — Tema claro opcional

Fecha: 2026-11-11. **Propuestas para revisión**, no implementación autorizada. Spec y D1–D4 aprobadas por el usuario; las diez tareas siguen pendientes. Node 24/pnpm 12.12.1. Todos los comandos siguientes son previstos, no resultados ejecutados; nombres nuevos corresponden a archivos definidos por el plan.

## PR A — Paletas y resolución SSR (T1–T3)

- [ ] **T1. Preferencia pura y descriptores de tema.** RF-002/003/005/006/013/014/015. 25 min.
  - Hecho cuando: tests primero en rojo y luego verdes para ausencia/null/inválido, dark/light/system, metadatos y fallback oscuro; lógica pura sin reloj/DOM/red, constante anual y sin escritura al normalizar. Referencia frontend `8993a393` y su hash de árbol registrados para T7; ninguna aprobación de implementación se infiere del plan.
  - Comando: `cd frontend && pnpm test`.

- [ ] **T2. Paletas y espejo de dos temas, contraste completo.** RF-008/009/012; RNF-001/003. Depende de T1. 30 min.
  - Hecho cuando: test rojo previo; PALETTE oscura compatible e idéntica, nueva clara y roles de isla espejados por scope; 29 pares oscuros existentes y los 158 claros identificados se recalculan con umbrales intactos. Guardián contempla hex/rgb/hsl, sin nuevos literales fuera de tokens ni exclusiones genéricas; CSS claro no altera reglas efectivas oscuras. Inputs inválidos/composición y scope faltante o extra fallan.
  - Comando: `cd frontend && pnpm test && pnpm run typecheck`.

- [ ] **T3. Integrar cookie anual, head SSR y aplicación reactiva.** RF-002–006/013–015; RNF-004/005. Depende de T2. 30 min.
  - Hecho cuando: test rojo previo; cookie bc_theme solo al elegir, default null sin Set-Cookie de apariencia al visitar/normalizar; SameSite/path/Secure/maxAge definidos. SSR entrega html data-theme y head correctos, sin estado mutable entre solicitudes; CSS resuelve Sistema sin depender de mounted. color-scheme/theme-color coherentes; sin meta fijo duplicado, fetch, script anti-FOUC o cambio CSP. Bloqueo de persistencia mantiene estado UI sin romper navegación.
  - Comando: `cd frontend && pnpm test && pnpm run typecheck && pnpm run lint && pnpm run build`.

## PR B — Selector y superficies claras (T4–T6)

- [ ] **T4. Selector accesible ES/EN y ubicación limitada a R.** RF-001/004/007/009; RNF-001/003. Depende de T3. 30 min.
  - Hecho cuando: pruebas rojas antes del control; select etiquetado/IDs únicos/teclado en flotante público, cabecera y menú móvil Workspace/admin; mismo estado reactivo y sin cambio de ruta/foco. Nuevo control y halo caben en R (192×80, desplegado 192×200 si se compara); no refluye ni oculta idioma, organización, cuenta o contenido. Registrar cajas/R a 1440/390/800 y ES/EN. Si no cabe, parar: no ampliar región ni aprobar desplazamientos implícitos. Validación visual final en T7/T9.
  - Comando: `cd frontend && pnpm test && pnpm run typecheck && pnpm run lint`.

- [ ] **T5. Iniciales, disabled, backdrops y superficies compartidas claras.** RF-008/010/011; RNF-001/002. Depende de T4. 30 min.
  - Hecho cuando: test rojo previo; claro usa iniciales oscuras legibles, texto disabled opaco y velos/diálogos claros sin alfa duplicada; imágenes/URLs sin inversión y acceso/foco/Escape intactos. Revisados todos los consumidores con opacidad, incluidas reglas/asistentes/operación/admin/plantillas. Hover/autofill/selección/tablas/sticky/pistas siguen el tema; ningún ajuste de estos estados afecta oscuro. Render real en T9.
  - Comando: `cd frontend && pnpm test && pnpm run typecheck && pnpm run lint`.

- [ ] **T6. Isla verde y gráficos sin cambios deportivos.** RF-008/009/010/012. Depende de T5. 25 min.
  - Hecho cuando: test rojo previo; MatchPitch/TeamPitch conservan césped/geometría y usan roles claros propios, visitante #ffd18a solo en claro y ámbar original en oscuro. Contenedor/banco/textual claros; mismo contenido y segmento, sin pérdida de nombres ni fotos. SVG de bracket conserva currentColor, pares, rondas y geometría. Pares de césped y trazos alfa pasan; no cambiar referencias para ocultar diferencias.
  - Comando: `cd frontend && pnpm test && pnpm run typecheck`.

## PR C — Regresión y aceptación (T7–T10)

- [ ] **T7. Comparador visual exacto y referencia oscura.** RF-007/009; RNF-001. Depende de T6. 30 min activos; capturas aparte.
  - Hecho cuando: test primero rojo con un píxel alterado fuera de R; comparación RGBA exacta con 0 fuera y validación de dimensiones/límites de R, sin tolerancia de antialias. Baseline de la revisión fijada, motor/fixture/fuentes/reloj iguales; manifiesto R prefijado y cajas antiguas intactas. Todas las vistas/estados acordados, ES/EN, 1440×900/390×844/800×900, PNG originales/diff anotado en `/home/ubuntu/ui-audit/032-{before,after,pr}/`. Cambio solo dentro de R es válido; máscara expandida u ocultando controles, imágenes de tamaños distintos o referencia alterada fallan. No se declara verde sin las capturas.
  - Comando: `cd frontend && pnpm test && pnpm exec playwright test --config e2e/theme-audit.config.ts --grep @visual`.

- [ ] **T8. E2E de elección, persistencia y primer pintado.** RF-001–007/013–015; RNF-004/005/006. Depende de T7. 30 min.
  - Hecho cuando: escenarios inicialmente rojos y luego verdes anónimos y Workspace, storageState apropiado, trace/video apagados. Verificar cookie anual solo tras elegir, recarga/reapertura, inválida/bloqueada, Sistema y cambios de media, solicitudes concurrentes opuestas. SSR con hidratación retenida y observación primer paint/rAF, también ralentizado: ninguna muestra inicial de tema opuesto, sin warnings ni llamadas API extra; no basta esperar mounted. Formulario/foco/scroll/filtro y diálogos sobreviven. Integrar testMatch en public/workspace sin reemplazar realtime/21 public-polish/operation-flow ni modificar veredictos.
  - Comando: `cd frontend && pnpm run typecheck:e2e && pnpm exec playwright test e2e/theme-public.spec.ts --project public --no-deps && pnpm exec playwright test e2e/theme-workspace.spec.ts --project workspace`.

- [ ] **T9. Axe y contraste efectivo de todas las vistas en ambos temas.** RF-001/007–013; RNF-002/003. Depende de T8. 30 min activos; auditoría automatizada aparte.
  - Hecho cuando: matriz de rutas/roles/estados alcanzables y tres tamaños documentada; claro 0 violaciones de app y oscuro ninguna nueva, sin excluir reglas/nodos. Campo/gráficos, todas las estadísticas, sticky, vacíos/errores, disabled, overlays y teclado revisados; contraste efectivo de textos ≥4.5 y señales ≥3, además de los 158 pares. Cada vista debe renderizar, no redirigir por permisos. JSON de axe con versión y capturas claras/oscuras revisadas; límites reales declarados, sin certificar dispositivos/lectores no usados.
  - Comando: `cd frontend && pnpm exec playwright test --config e2e/theme-audit.config.ts --grep @axe`.

- [ ] **T10. Gates, documentación, limpieza y cierre aprobado.** RF-001–015; RNF-001–006. Depende de T9. 30 min activos; espera CI aparte.
  - Hecho cuando: cinco gates frontend y nuevos E2E, 21 public-polish, operation-flow y CI aplicables verdes, cantidades de nuevos E2E verificadas en logs del job. RF por RF, criterios de finalización/constitución §4 y evidencia documentados; manual/accesibilidad/AGENTS/MEMORY actualizados. Datos temporales retirados por IDs si se crearon, sin cookies/headers/auth en artefactos. Revisión humana y aprobación antes de marcar implementada; si falta un gate o revisión, T10 sigue sin marcar. No abrir ni fusionar PR sin encargo.
  - Comando: `cd frontend && pnpm test && pnpm run typecheck && pnpm run lint && pnpm run build && pnpm run typecheck:e2e && pnpm exec playwright test e2e/public-polish.spec.ts --project public --no-deps && pnpm exec playwright test --project operation-flow`.
  - Además: ejecutar los comandos T7–T9, `git diff --check` y esperar CI con git_pr_checks wait_mode=all cuando exista PR.

## Reglas de entrega

- Orden PR A → B → C; agrupación propuesta, no autorización para implementarla o abrirlos. En cada tarea de código: tests rojos primero, cambio mínimo, checks y solo entonces checkbox. Suites existentes siempre conservadas.
- Los gates de CI y revisión humana no se sustituyen por capturas locales; no dar por ejecutadas las comprobaciones propuestas aquí. PR A/B no declaran cerrada la aceptación global de C.
- R es una excepción visual de spec aprobada, no una excepción constitucional ni permiso para cambiar lenguaje, controles, contenido o API. Si la geometría requiere otra excepción, pedirla antes de proceder.
