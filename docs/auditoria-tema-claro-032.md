# Auditoría de tema claro — spec 032

Fecha: 2026-11-11. Auditoría estática, no implementación. Base `origin/main` `8993a393c4d64229bd5a16dce6d5157c37d4455c`, después de fusionar #52. Alcance: archivos versionados del frontend; se excluyen dependencias, compilados, cachés y capturas. No se ejecutaron navegador, axe ni suites de aplicación: no se declara conformidad visual del tema inexistente.

## 1. Inventario y método

- `tokens.css`: **23 roles de color, 20 valores hex únicos**, dentro de 69 propiedades totales. `PALETTE` en `designTokens.ts`: 23 entradas, mismas claves/valores, igualdad comprobada.
- **64 archivos .vue/.css: 60 Vue + 4 CSS.** 23 ocurrencias hex en tokens.css; fuera: **0 hex, 0 rgb/rgba, 0 hsl/hsla**, en cada archivo del anexo. Ningún literal de estos tipos necesita migrarse ahora.
- Se inspeccionó el archivo completo, incluidos plantilla/script/style e inline, con longitudes hex 3/4/6/8 y funciones rgb/rgba/hsl/hsla. No se cuentan `transparent`, `currentColor`, `none` ni referencias a variables como colores literales. No se pretende analizar CSS futuro o descargado.
- En los TS de app y configuración, fuera del espejo, hay un literal adicional: `frontend/nuxt.config.ts:12`, `theme-color: #0c0f0c`. Es metadato, no deuda en Vue/CSS; debe seguir el fondo resuelto de cada tema, conservando su valor oscuro.
- Resultados detallados y cálculo reproducible local: `/home/ubuntu/ui-audit/032-code/{audit.py,audit.json}`. Este informe conserva también todos los pares calculados y el inventario por archivo.

## 2. Superficies, sombras, imágenes y SVG

El inventario detecta **81 líneas en 31 archivos** con sombras, degradados o SVG: 56 líneas con sombra en 29 archivos y 38 con degradado en 23. Son líneas que usan esos efectos, no 56/38 colores o expresiones independientes; una línea puede contener varios efectos y aparecer en ambas categorías. Sus colores proceden de tokens, pero su composición no queda resuelta cambiando solo valores hex.

- `assets/css/main.css`: sombra profunda negra al 34%, sombras de acento, radial lima al 8% y canvas/canvas-raised; la versión clara requiere elevación más contenida sin tocar la rama oscura.
- `ui/ConfirmDialog.vue`: backdrop con superficie/85% de opacidad; `PublicLineupModal.vue`: degradado semitransparente y sombra negra 50%. Revisar backdrop, panel y contenido juntos en claro.
- `ui/HorizontalScroll.vue`: degradado de sombra negra 55% a la derecha, solo si hay overflow; no confundirlo con un borde o señal esencial de contraste.
- Paneles de acceso, cuenta, organización, admin, Workspace, operación y asistentes: fondos de superficie al 90–99%, halos de acento y sombras al 12–16% (véase inventario).
- **Campo de juego:** MatchPitch y TeamPitch ya usan pitch-grass/stripe/line/player. Césped #315b35/#38673b, trazos #ecffce al 55/62/85%, sombra interior 20%, drop-shadow de jugadores 35%. No es una imagen plana ni SVG: se dibuja con CSS. El cambio global a tinta oscura haría ilegibles sus etiquetas sobre césped; se propone conservar el campo como isla gráfica verde con colores propios para texto en claro, no toda la pantalla oscura.
- La primera propuesta de isla copiaba el ámbar oscuro #ffcb7a: sobre la franja #38673b daba **4.438:1**, insuficiente para texto pequeño. Se revisó **solo la propuesta clara** a #ffd18a, que da **4.648:1** en la misma franja. Esto no demuestra una infracción renderizada del oscuro actual (hay posición y drop-shadow no medidos) ni autoriza modificarlo.
- **Bracket SVG:** un SVG inline en `PublicBracketConnections.vue`; aria-hidden, fill none, stroke currentColor, color muted. No tiene color literal; el muted claro da al menos 6.021:1 frente a superficies base. No cambiar geometría ni relaciones.
- **Escudos y fotos:** TeamCrest renderiza URL de API (crest y logo heredado solo Workspace), no genera SVG de color fijo. Iniciales y fotos de estadísticas usan avatar-ink, highlight al 6% y borde al 18%. Mantener el blanco actual para avatar-ink en claro NO funciona: se propone tinta #182218; el césped usa sus propios avatares. No invertir/recolorear imágenes externas, ni cambiar URL/bytes/consentimiento/alternativas textuales.
- No hay archivos SVG/PNG/JPG/JPEG/WebP/GIF versionados en frontend. Esto no inventaría el contenido binario de escudos/fotos servidos por la API: no se descargaron ni auditaron imágenes de usuarios.

## 3. SSR, preferencias y seguridad

- Nuxt 4, SSR por defecto: `nuxt.config.ts` no desactiva SSR, no prerenderiza ni introduce caché compartida por routeRules; solo fija cabeceras. `app.vue` monta NuxtPage y el selector de idioma en rutas no Workspace/admin. La carga inicial puede entregar HTML antes de hidratarlo.
- Hoy `main.css:5` fuerza `color-scheme: dark`; `nuxt.config.ts:12` fija theme-color oscuro. No hay selector ni preferencia de tema.
- Modelo existente: `LanguageSwitcher.vue` usa select nativo etiquetado, actualiza html lang con useHead y llama a useI18n. Cookie `bc_locale`: default es, SameSite=Lax, Secure fuera de dev, duración un año y normalización de valores inválidos. Público: **flotante inferior derecho**, no cabecera; WorkspaceShell: inline en cabecera desktop y menú móvil. El admin usa el mismo shell.
- Una cookie de apariencia opcional, normalizada y sin identidad, puede leerse por solicitud en SSR para que HTML, CSS y controles nativos coincidan con el primer pintado. No requiere tabla, endpoint o cuenta, no debe convertirse en dependencia de sesión ni crearse al visitar anónimamente sin elegir. No sincroniza dispositivos ni justifica un estado mutable global de servidor. Si se añade caché HTML después, debe respetar la preferencia y no mezclar solicitudes.
- localStorage solo existe en cliente: aplicar tema en mounted produce un primer pintado incorrecto para preferencias distintas del SSR; leerlo antes de pintar con script puede evitarlo, pero introduce otra ruta de inicialización y riesgo de divergencia en hidratación. Al estar bloqueado, la app debe seguir funcionando.
- Seguir al sistema: el servidor normalmente no conoce prefers-color-scheme. Cookie con valor Sistema no le comunica el resultado al servidor; se necesita una resolución CSS antes del primer pintado, con etiqueta Sistema estable, y no renderizar texto/markup diferente por una consulta disponible solo en cliente. No se presuponen Client Hints ni cambios de servidor.
- CSP comprobada en `app/utils/securityHeaders.ts`, aplicada por `nuxt.config.ts` a /**: **`frame-ancestors 'none'; object-src 'none'; base-uri 'self'`**. No hay script-src **ni default-src**; la ausencia de ambos implica que esta política no bloquearía un script inline anti-FOUC. No hay que añadir unsafe-inline ni relajar cabeceras. Esto NO significa que sea necesaria o preferible esa solución; un proxy de despliegue puede añadir otra política, no inspeccionada en esta auditoría. DevTools no representa producción.
- Cambiar tema no debe recargar rutas, perder foco, cerrar diálogos, resetear formularios/filtros ni efectuar llamadas API adicionales.

## 4. Propuesta de diseño, todavía no aprobada

Dirección: **papel de acta, tinta verde de señalización y césped conservado**. No invertir el oscuro ni cambiar marca, tipografía Archivo, jerarquía, espacios, radios, layout o escalas de la 029. Base clara ligeramente verdosa, cinco niveles existentes, verde bosque para acciones y ámbar/rojo oscuro para semántica legible. Sin fuentes, ilustraciones o animaciones nuevas.

Se revisó el primer planteamiento (invertir paleta, conservar todo texto de avatares/campo): perdía contraste. La propuesta revisada separa avatares de superficie e isla del césped y aclara solo el ámbar de esta isla. Los nuevos roles de isla y ajustes de opacidad se limitarían a claro. La paleta no implica autorización para implementar.

Layout de preferencia a decidir, sin rediseñar la navegación:

```text
Público:   contenido intacto       [Idioma] [Apariencia?] (ubicación actual flotante)
Workspace: marca | navegación | organización | idioma | apariencia? | cuenta
Móvil:     menú existente -> idioma / apariencia? (sin desplazar el contenido)
```

**Conflicto real:** un selector nuevo visible modifica píxeles aunque todos los tokens oscuros se conserven. El requisito del usuario de 0 píxeles oscuros se mantiene literal; NO se introduce una máscara/excepción silenciosa. D2 debe resolver si autoriza exclusivamente el nuevo control o exige acceso separado sin alterar vistas existentes. No se inicia plan/implementación antes de resolverlo.

### Paleta por rol actual

| Rol | Oscuro actual (intocable) | Claro propuesto |
|---|---|---|
| ink | `#f4f0e7` | `#182218` |
| muted | `#a6aa9f` | `#4c594a` |
| surface | `#151814` | `#fafbf5` |
| surface-raised | `#20251e` | `#f0f3e8` |
| surface-bright | `#293325` | `#e4ead9` |
| line | `#3b4538` | `#707d67` |
| accent | `#d4f36a` | `#355619` |
| accent-ink | `#17200f` | `#ffffff` |
| danger | `#ffb0a8` | `#9c2929` |
| warning | `#ffcb7a` | `#785000` |
| success | `#d4f36a` | `#355619` |
| home | `#d4f36a` | `#355619` |
| away | `#ffcb7a` | `#785000` |
| canvas | `#0c0f0c` | `#f5f7ef` |
| canvas-raised | `#111611` | `#edf1e4` |
| shadow | `#000000` | `#000000` |
| highlight | `#ffffff` | `#ffffff` |
| pitch-grass | `#315b35` | `#315b35` |
| pitch-stripe | `#38673b` | `#38673b` |
| pitch-line | `#ecffce` | `#ecffce` |
| pitch-player | `#172218` | `#172218` |
| avatar-ink | `#f5f7fb` | `#182218` |
| danger-border | `#a45b5b` | `#a45b5b` |

Isla clara del campo: tinta #f4f0e7, acento #d4f36a, visitante #ffd18a; césped/trazos/player de la tabla. Sus etiquetas no heredan ink/accent/warning claros globales. No son cambios al tema oscuro.

### Contraste: método y alcance

Luminancia relativa sRGB WCAG: linealizar cada canal con umbral 0.04045, ponderar 0.2126/0.7152/0.0722 y dividir (Lmayor+0.05)/(Lmenor+0.05). Se comparan valores sin redondear; tabla a tres decimales. Para mezclas se compone en sRGB sobre el fondo indicado, a 8 bits. Límites: **4.5:1 para todos los textos propuestos**, incluso pequeños; **3:1 para contornos, foco y señales gráficas esenciales**. Colores decorativos (sombras/highlight) no son tinta ni límites esenciales.

**158 pares calculados, 0 fallos: 140 de texto y 18 de controles/gráficos.** Texto mínimo 4.648:1 (isla del campo), texto de superficies base mínimo 5.794:1; texto sobre tintes al 8/10% mínimo 4.996:1. Control mínimo 3.116:1 (trazo del campo al 55% sobre franja). Botones sólidos con texto blanco: mínimo 7.128:1. Iniciales oscuras sobre highlight6% compuesto: mínimo 13.484:1.

Esta es una matriz de **roles destino**, no prueba de que reemplazar tokens deje ya accesible toda la app. Opacidad global de botones/fieldset deshabilitados, degradados, hover, selectores nativos, autofill, foco sobre botones y mezcla de capas deben verificarse renderizados en implementación. En claro se propone que el texto deshabilitado use ink/muted opacos (sin rebajar todo el elemento) y no se reutilice avatar-ink oscuro sobre fondos claros. Deben ampliarse los pares si aparece otro fondo efectivo. No se certifican contrastes de texto incrustado en imágenes de terceros.

### Test existente y huecos

`frontend/tests/design-contrast.test.ts` comprueba espejo, 29 pares de `CONTRAST_PAIRS` (24 textos sobre tres superficies, cuatro botones y un par de componente), cálculo de contraste y nearestStep. No incluye modo claro, canvas/canvas-raised, fondos compuestos, campos, imágenes, disabled ni todos los componentes reales. `design-scales.test.ts` prohíbe literales hex/rgb en Vue/CSS, sin migraciones pendientes; su regex **no cubre hsl/hsla**, aunque este inventario sí y encontró cero. No se modificó ninguno de los tests.

## 5. Inventario por archivo (.vue/.css versionados)

Rutas relativas a frontend. La columna final excluye los valores canónicos de tokens.css. Todos los archivos y todas las cuentas, también los ceros, se enumeran:

| Archivo | Hex | RGB/RGBA | HSL/HSLA | Fuera de tokens |
|---|---:|---:|---:|---:|
| `app/app.vue` | 0 | 0 | 0 | 0 |
| `app/assets/css/fonts.css` | 0 | 0 | 0 | 0 |
| `app/assets/css/main.css` | 0 | 0 | 0 | 0 |
| `app/assets/css/tokens.css` | 23 | 0 | 0 | 0 (23 canónicos) |
| `app/components/FormatWarning.vue` | 0 | 0 | 0 | 0 |
| `app/components/LanguageSwitcher.vue` | 0 | 0 | 0 | 0 |
| `app/components/RulesEditor.vue` | 0 | 0 | 0 | 0 |
| `app/components/StageTeamsWizard.vue` | 0 | 0 | 0 | 0 |
| `app/components/TeamCrest.vue` | 0 | 0 | 0 | 0 |
| `app/components/TeamsWizard.vue` | 0 | 0 | 0 | 0 |
| `app/components/WorkspaceShell.vue` | 0 | 0 | 0 | 0 |
| `app/components/match/MatchActionBar.vue` | 0 | 0 | 0 | 0 |
| `app/components/match/MatchBar.vue` | 0 | 0 | 0 | 0 |
| `app/components/match/MatchCloseSection.vue` | 0 | 0 | 0 | 0 |
| `app/components/match/MatchEventsSection.vue` | 0 | 0 | 0 | 0 |
| `app/components/match/MatchFieldSection.vue` | 0 | 0 | 0 | 0 |
| `app/components/match/MatchLineupSection.vue` | 0 | 0 | 0 | 0 |
| `app/components/match/MatchOperationHeader.vue` | 0 | 0 | 0 | 0 |
| `app/components/match/MatchResolutionPanel.vue` | 0 | 0 | 0 | 0 |
| `app/components/match/MatchRosterLinks.vue` | 0 | 0 | 0 | 0 |
| `app/components/match/MatchSectionNav.vue` | 0 | 0 | 0 | 0 |
| `app/components/match/operation.css` | 0 | 0 | 0 | 0 |
| `app/components/public/MatchPitch.vue` | 0 | 0 | 0 | 0 |
| `app/components/public/PublicBracket.vue` | 0 | 0 | 0 | 0 |
| `app/components/public/PublicBracketConnections.vue` | 0 | 0 | 0 | 0 |
| `app/components/public/PublicLineupModal.vue` | 0 | 0 | 0 | 0 |
| `app/components/public/PublicPlayerStatsTable.vue` | 0 | 0 | 0 | 0 |
| `app/components/public/PublicStandingsTable.vue` | 0 | 0 | 0 | 0 |
| `app/components/public/PublicTeamStatsTable.vue` | 0 | 0 | 0 | 0 |
| `app/components/public/TeamPitch.vue` | 0 | 0 | 0 | 0 |
| `app/components/rules/RulesWizard.vue` | 0 | 0 | 0 | 0 |
| `app/components/ui/Button.vue` | 0 | 0 | 0 | 0 |
| `app/components/ui/ConfirmDialog.vue` | 0 | 0 | 0 | 0 |
| `app/components/ui/DataTable.vue` | 0 | 0 | 0 | 0 |
| `app/components/ui/FieldError.vue` | 0 | 0 | 0 | 0 |
| `app/components/ui/FormField.vue` | 0 | 0 | 0 | 0 |
| `app/components/ui/HorizontalScroll.vue` | 0 | 0 | 0 | 0 |
| `app/components/ui/PageHeader.vue` | 0 | 0 | 0 | 0 |
| `app/components/ui/StateMessage.vue` | 0 | 0 | 0 | 0 |
| `app/components/ui/StatusPill.vue` | 0 | 0 | 0 | 0 |
| `app/components/ui/Surface.vue` | 0 | 0 | 0 | 0 |
| `app/components/ui/Tabs.vue` | 0 | 0 | 0 | 0 |
| `app/components/wizard/WizardShell.vue` | 0 | 0 | 0 | 0 |
| `app/components/wizard/WizardSteps.vue` | 0 | 0 | 0 | 0 |
| `app/components/workspace/setup/SetupChecklist.vue` | 0 | 0 | 0 | 0 |
| `app/components/workspace/setup/SetupHeader.vue` | 0 | 0 | 0 | 0 |
| `app/components/workspace/setup/SetupRules.vue` | 0 | 0 | 0 | 0 |
| `app/components/workspace/setup/SetupStages.vue` | 0 | 0 | 0 | 0 |
| `app/components/workspace/setup/SetupTeams.vue` | 0 | 0 | 0 | 0 |
| `app/pages/account/google.vue` | 0 | 0 | 0 | 0 |
| `app/pages/admin/index.vue` | 0 | 0 | 0 | 0 |
| `app/pages/auth/callback.vue` | 0 | 0 | 0 | 0 |
| `app/pages/forbidden.vue` | 0 | 0 | 0 | 0 |
| `app/pages/index.vue` | 0 | 0 | 0 | 0 |
| `app/pages/invitations/[token].vue` | 0 | 0 | 0 | 0 |
| `app/pages/login.vue` | 0 | 0 | 0 | 0 |
| `app/pages/organization.vue` | 0 | 0 | 0 | 0 |
| `app/pages/tournaments/[id].vue` | 0 | 0 | 0 | 0 |
| `app/pages/workspace/index.vue` | 0 | 0 | 0 | 0 |
| `app/pages/workspace/matches/[id].vue` | 0 | 0 | 0 | 0 |
| `app/pages/workspace/members.vue` | 0 | 0 | 0 | 0 |
| `app/pages/workspace/tournaments/[id]/calendar.vue` | 0 | 0 | 0 | 0 |
| `app/pages/workspace/tournaments/[id]/index.vue` | 0 | 0 | 0 | 0 |
| `app/pages/workspace/tournaments/[id]/rosters.vue` | 0 | 0 | 0 | 0 |

## 6. Inventario de efectos por archivo

Líneas de fuente, no colores nuevos. Sombra incluye referencias a tokens shadow; degradado incluye linear/radial/repeating-linear. El total de ambas columnas se solapa.

| Archivo relativo a frontend | Líneas con sombra | Líneas con degradado | Líneas inspeccionadas |
|---|---:|---:|---|
| `app/assets/css/main.css` | 3 | 2 | 118, 119, 141, 158, 285 |
| `app/components/LanguageSwitcher.vue` | 3 | 0 | 22, 23, 26 |
| `app/components/RulesEditor.vue` | 1 | 0 | 588 |
| `app/components/TeamsWizard.vue` | 1 | 0 | 694 |
| `app/components/WorkspaceShell.vue` | 2 | 1 | 322, 335, 358 |
| `app/components/match/operation.css` | 3 | 2 | 1, 21, 51, 94 |
| `app/components/public/MatchPitch.vue` | 2 | 1 | 118, 129 |
| `app/components/public/PublicBracketConnections.vue` | 0 | 0 | 8, 15 |
| `app/components/public/PublicLineupModal.vue` | 1 | 1 | 257 |
| `app/components/public/PublicPlayerStatsTable.vue` | 1 | 0 | 136 |
| `app/components/public/PublicStandingsTable.vue` | 1 | 0 | 64 |
| `app/components/public/PublicTeamStatsTable.vue` | 1 | 0 | 94 |
| `app/components/public/TeamPitch.vue` | 2 | 1 | 75, 86 |
| `app/components/ui/HorizontalScroll.vue` | 1 | 1 | 48 |
| `app/components/wizard/WizardSteps.vue` | 1 | 0 | 134 |
| `app/components/workspace/setup/SetupRules.vue` | 1 | 1 | 78 |
| `app/components/workspace/setup/SetupTeams.vue` | 1 | 1 | 92 |
| `app/pages/account/google.vue` | 1 | 2 | 113, 120, 121 |
| `app/pages/admin/index.vue` | 3 | 3 | 274, 278, 283, 290, 292 |
| `app/pages/auth/callback.vue` | 1 | 2 | 60, 67, 68 |
| `app/pages/forbidden.vue` | 1 | 1 | 41, 42 |
| `app/pages/index.vue` | 4 | 2 | 110, 115, 140, 142, 143 |
| `app/pages/invitations/[token].vue` | 2 | 2 | 137, 138, 150 |
| `app/pages/login.vue` | 2 | 2 | 233, 237, 251 |
| `app/pages/organization.vue` | 2 | 2 | 170, 177, 178, 195 |
| `app/pages/tournaments/[id].vue` | 4 | 2 | 823, 831, 847, 871, 879 |
| `app/pages/workspace/index.vue` | 4 | 3 | 278, 280, 281, 291, 300, 301 |
| `app/pages/workspace/members.vue` | 2 | 2 | 363, 366, 371 |
| `app/pages/workspace/tournaments/[id]/calendar.vue` | 3 | 2 | 548, 554, 555, 580 |
| `app/pages/workspace/tournaments/[id]/index.vue` | 2 | 1 | 107, 114, 119 |
| `app/pages/workspace/tournaments/[id]/rosters.vue` | 0 | 1 | 653 |

## 7. Matriz completa de contraste propuesto

`island.*` significa los tres colores propios del campo claro descritos arriba. Porcentajes indican composición sobre el fondo de la derecha; no se verifica una mezcla contra transparente sin fondo. Foco/acción usan accent frente a las cinco superficies (filas de texto de accent, mayores que 3:1); el contorno necesita separación visible sobre botón del mismo color, no color contra sí mismo.

| # | Uso | Frente | Fondo | Ratio | Mínimo |
|---|---|---|---|---:|---:|
| 1 | text | ink | canvas | 15.172 | 4.5:1 |
| 2 | text | ink | canvas-raised | 14.290 | 4.5:1 |
| 3 | text | ink | surface | 15.757 | 4.5:1 |
| 4 | text | ink | surface-raised | 14.592 | 4.5:1 |
| 5 | text | ink | surface-bright | 13.327 | 4.5:1 |
| 6 | text | muted | canvas | 6.854 | 4.5:1 |
| 7 | text | muted | canvas-raised | 6.456 | 4.5:1 |
| 8 | text | muted | surface | 7.119 | 4.5:1 |
| 9 | text | muted | surface-raised | 6.592 | 4.5:1 |
| 10 | text | muted | surface-bright | 6.021 | 4.5:1 |
| 11 | text | accent | canvas | 7.784 | 4.5:1 |
| 12 | text | accent | canvas-raised | 7.332 | 4.5:1 |
| 13 | text | accent | surface | 8.084 | 4.5:1 |
| 14 | text | accent | surface-raised | 7.487 | 4.5:1 |
| 15 | text | accent | surface-bright | 6.837 | 4.5:1 |
| 16 | text | danger | canvas | 7.034 | 4.5:1 |
| 17 | text | danger | canvas-raised | 6.625 | 4.5:1 |
| 18 | text | danger | surface | 7.305 | 4.5:1 |
| 19 | text | danger | surface-raised | 6.765 | 4.5:1 |
| 20 | text | danger | surface-bright | 6.179 | 4.5:1 |
| 21 | text | warning | canvas | 6.596 | 4.5:1 |
| 22 | text | warning | canvas-raised | 6.213 | 4.5:1 |
| 23 | text | warning | surface | 6.851 | 4.5:1 |
| 24 | text | warning | surface-raised | 6.344 | 4.5:1 |
| 25 | text | warning | surface-bright | 5.794 | 4.5:1 |
| 26 | text | success | canvas | 7.784 | 4.5:1 |
| 27 | text | success | canvas-raised | 7.332 | 4.5:1 |
| 28 | text | success | surface | 8.084 | 4.5:1 |
| 29 | text | success | surface-raised | 7.487 | 4.5:1 |
| 30 | text | success | surface-bright | 6.837 | 4.5:1 |
| 31 | text | home | canvas | 7.784 | 4.5:1 |
| 32 | text | home | canvas-raised | 7.332 | 4.5:1 |
| 33 | text | home | surface | 8.084 | 4.5:1 |
| 34 | text | home | surface-raised | 7.487 | 4.5:1 |
| 35 | text | home | surface-bright | 6.837 | 4.5:1 |
| 36 | text | away | canvas | 6.596 | 4.5:1 |
| 37 | text | away | canvas-raised | 6.213 | 4.5:1 |
| 38 | text | away | surface | 6.851 | 4.5:1 |
| 39 | text | away | surface-raised | 6.344 | 4.5:1 |
| 40 | text | away | surface-bright | 5.794 | 4.5:1 |
| 41 | control | line | canvas | 4.033 | 3:1 |
| 42 | control | line | canvas-raised | 3.799 | 3:1 |
| 43 | control | line | surface | 4.189 | 3:1 |
| 44 | control | line | surface-raised | 3.879 | 3:1 |
| 45 | control | line | surface-bright | 3.543 | 3:1 |
| 46 | control | danger-border | canvas | 4.598 | 3:1 |
| 47 | control | danger-border | canvas-raised | 4.331 | 3:1 |
| 48 | control | danger-border | surface | 4.776 | 3:1 |
| 49 | control | danger-border | surface-raised | 4.423 | 3:1 |
| 50 | control | danger-border | surface-bright | 4.039 | 3:1 |
| 51 | button-text | accent-ink | accent | 8.412 | 4.5:1 |
| 52 | button-text | accent-ink | danger | 7.601 | 4.5:1 |
| 53 | button-text | accent-ink | warning | 7.128 | 4.5:1 |
| 54 | button-text | accent-ink | success | 8.412 | 4.5:1 |
| 55 | button-text | accent-ink | home | 8.412 | 4.5:1 |
| 56 | button-text | accent-ink | away | 7.128 | 4.5:1 |
| 57 | pitch-island-text | island.ink | pitch-grass | 6.894 | 4.5:1 |
| 58 | pitch-island-text | island.accent | pitch-grass | 6.283 | 4.5:1 |
| 59 | pitch-island-text | island.warning | pitch-grass | 5.503 | 4.5:1 |
| 60 | pitch-island-text | island.ink | pitch-stripe | 5.822 | 4.5:1 |
| 61 | pitch-island-text | island.accent | pitch-stripe | 5.306 | 4.5:1 |
| 62 | pitch-island-text | island.warning | pitch-stripe | 4.648 | 4.5:1 |
| 63 | pitch-island-text | island.ink | pitch-player | 14.443 | 4.5:1 |
| 64 | pitch-island-text | island.accent | pitch-player | 13.163 | 4.5:1 |
| 65 | pitch-island-text | island.warning | pitch-player | 11.529 | 4.5:1 |
| 66 | pitch-control | pitch-line | pitch-grass | 7.378 | 3:1 |
| 67 | pitch-control | pitch-line | pitch-stripe | 6.231 | 3:1 |
| 68 | avatar | avatar-ink | highlight6%/canvas | 15.210 | 4.5:1 |
| 69 | tinted-text | ink | accent8%/canvas | 13.420 | 4.5:1 |
| 70 | tinted-text | muted | accent8%/canvas | 6.063 | 4.5:1 |
| 71 | tinted-text | accent | accent8%/canvas | 6.885 | 4.5:1 |
| 72 | tinted-text | danger | accent8%/canvas | 6.221 | 4.5:1 |
| 73 | tinted-text | warning | accent8%/canvas | 5.834 | 4.5:1 |
| 74 | tinted-text | success | accent8%/canvas | 6.885 | 4.5:1 |
| 75 | tinted-text | home | accent8%/canvas | 6.885 | 4.5:1 |
| 76 | tinted-text | away | accent8%/canvas | 5.834 | 4.5:1 |
| 77 | tinted-text | ink | accent10%/canvas | 13.020 | 4.5:1 |
| 78 | tinted-text | muted | accent10%/canvas | 5.882 | 4.5:1 |
| 79 | tinted-text | accent | accent10%/canvas | 6.680 | 4.5:1 |
| 80 | tinted-text | danger | accent10%/canvas | 6.036 | 4.5:1 |
| 81 | tinted-text | warning | accent10%/canvas | 5.661 | 4.5:1 |
| 82 | tinted-text | success | accent10%/canvas | 6.680 | 4.5:1 |
| 83 | tinted-text | home | accent10%/canvas | 6.680 | 4.5:1 |
| 84 | tinted-text | away | accent10%/canvas | 5.661 | 4.5:1 |
| 85 | avatar | avatar-ink | highlight6%/canvas-raised | 14.427 | 4.5:1 |
| 86 | tinted-text | ink | accent8%/canvas-raised | 12.698 | 4.5:1 |
| 87 | tinted-text | muted | accent8%/canvas-raised | 5.737 | 4.5:1 |
| 88 | tinted-text | accent | accent8%/canvas-raised | 6.515 | 4.5:1 |
| 89 | tinted-text | danger | accent8%/canvas-raised | 5.887 | 4.5:1 |
| 90 | tinted-text | warning | accent8%/canvas-raised | 5.521 | 4.5:1 |
| 91 | tinted-text | success | accent8%/canvas-raised | 6.515 | 4.5:1 |
| 92 | tinted-text | home | accent8%/canvas-raised | 6.515 | 4.5:1 |
| 93 | tinted-text | away | accent8%/canvas-raised | 5.521 | 4.5:1 |
| 94 | tinted-text | ink | accent10%/canvas-raised | 12.337 | 4.5:1 |
| 95 | tinted-text | muted | accent10%/canvas-raised | 5.573 | 4.5:1 |
| 96 | tinted-text | accent | accent10%/canvas-raised | 6.329 | 4.5:1 |
| 97 | tinted-text | danger | accent10%/canvas-raised | 5.719 | 4.5:1 |
| 98 | tinted-text | warning | accent10%/canvas-raised | 5.364 | 4.5:1 |
| 99 | tinted-text | success | accent10%/canvas-raised | 6.329 | 4.5:1 |
| 100 | tinted-text | home | accent10%/canvas-raised | 6.329 | 4.5:1 |
| 101 | tinted-text | away | accent10%/canvas-raised | 5.364 | 4.5:1 |
| 102 | avatar | avatar-ink | highlight6%/surface | 15.767 | 4.5:1 |
| 103 | tinted-text | ink | accent8%/surface | 13.926 | 4.5:1 |
| 104 | tinted-text | muted | accent8%/surface | 6.292 | 4.5:1 |
| 105 | tinted-text | accent | accent8%/surface | 7.145 | 4.5:1 |
| 106 | tinted-text | danger | accent8%/surface | 6.456 | 4.5:1 |
| 107 | tinted-text | warning | accent8%/surface | 6.055 | 4.5:1 |
| 108 | tinted-text | success | accent8%/surface | 7.145 | 4.5:1 |
| 109 | tinted-text | home | accent8%/surface | 7.145 | 4.5:1 |
| 110 | tinted-text | away | accent8%/surface | 6.055 | 4.5:1 |
| 111 | tinted-text | ink | accent10%/surface | 13.428 | 4.5:1 |
| 112 | tinted-text | muted | accent10%/surface | 6.066 | 4.5:1 |
| 113 | tinted-text | accent | accent10%/surface | 6.889 | 4.5:1 |
| 114 | tinted-text | danger | accent10%/surface | 6.225 | 4.5:1 |
| 115 | tinted-text | warning | accent10%/surface | 5.838 | 4.5:1 |
| 116 | tinted-text | success | accent10%/surface | 6.889 | 4.5:1 |
| 117 | tinted-text | home | accent10%/surface | 6.889 | 4.5:1 |
| 118 | tinted-text | away | accent10%/surface | 5.838 | 4.5:1 |
| 119 | avatar | avatar-ink | highlight6%/surface-raised | 14.722 | 4.5:1 |
| 120 | tinted-text | ink | accent8%/surface-raised | 12.883 | 4.5:1 |
| 121 | tinted-text | muted | accent8%/surface-raised | 5.820 | 4.5:1 |
| 122 | tinted-text | accent | accent8%/surface-raised | 6.610 | 4.5:1 |
| 123 | tinted-text | danger | accent8%/surface-raised | 5.973 | 4.5:1 |
| 124 | tinted-text | warning | accent8%/surface-raised | 5.601 | 4.5:1 |
| 125 | tinted-text | success | accent8%/surface-raised | 6.610 | 4.5:1 |
| 126 | tinted-text | home | accent8%/surface-raised | 6.610 | 4.5:1 |
| 127 | tinted-text | away | accent8%/surface-raised | 5.601 | 4.5:1 |
| 128 | tinted-text | ink | accent10%/surface-raised | 12.494 | 4.5:1 |
| 129 | tinted-text | muted | accent10%/surface-raised | 5.644 | 4.5:1 |
| 130 | tinted-text | accent | accent10%/surface-raised | 6.410 | 4.5:1 |
| 131 | tinted-text | danger | accent10%/surface-raised | 5.792 | 4.5:1 |
| 132 | tinted-text | warning | accent10%/surface-raised | 5.432 | 4.5:1 |
| 133 | tinted-text | success | accent10%/surface-raised | 6.410 | 4.5:1 |
| 134 | tinted-text | home | accent10%/surface-raised | 6.410 | 4.5:1 |
| 135 | tinted-text | away | accent10%/surface-raised | 5.432 | 4.5:1 |
| 136 | avatar | avatar-ink | highlight6%/surface-bright | 13.484 | 4.5:1 |
| 137 | tinted-text | ink | accent8%/surface-bright | 11.836 | 4.5:1 |
| 138 | tinted-text | muted | accent8%/surface-bright | 5.347 | 4.5:1 |
| 139 | tinted-text | accent | accent8%/surface-bright | 6.073 | 4.5:1 |
| 140 | tinted-text | danger | accent8%/surface-bright | 5.487 | 4.5:1 |
| 141 | tinted-text | warning | accent8%/surface-bright | 5.146 | 4.5:1 |
| 142 | tinted-text | success | accent8%/surface-bright | 6.073 | 4.5:1 |
| 143 | tinted-text | home | accent8%/surface-bright | 6.073 | 4.5:1 |
| 144 | tinted-text | away | accent8%/surface-bright | 5.146 | 4.5:1 |
| 145 | tinted-text | ink | accent10%/surface-bright | 11.491 | 4.5:1 |
| 146 | tinted-text | muted | accent10%/surface-bright | 5.191 | 4.5:1 |
| 147 | tinted-text | accent | accent10%/surface-bright | 5.895 | 4.5:1 |
| 148 | tinted-text | danger | accent10%/surface-bright | 5.327 | 4.5:1 |
| 149 | tinted-text | warning | accent10%/surface-bright | 4.996 | 4.5:1 |
| 150 | tinted-text | success | accent10%/surface-bright | 5.895 | 4.5:1 |
| 151 | tinted-text | home | accent10%/surface-bright | 5.895 | 4.5:1 |
| 152 | tinted-text | away | accent10%/surface-bright | 4.996 | 4.5:1 |
| 153 | pitch-control-composite | pitch-line55% | pitch-grass | 3.474 | 3:1 |
| 154 | pitch-control-composite | pitch-line62% | pitch-grass | 3.978 | 3:1 |
| 155 | pitch-control-composite | pitch-line85% | pitch-grass | 5.856 | 3:1 |
| 156 | pitch-control-composite | pitch-line55% | pitch-stripe | 3.116 | 3:1 |
| 157 | pitch-control-composite | pitch-line62% | pitch-stripe | 3.497 | 3:1 |
| 158 | pitch-control-composite | pitch-line85% | pitch-stripe | 5.028 | 3:1 |

## 8. Límites de esta entrega

Solo auditoría de código y cálculo de paleta, sin cambios de app ni datos temporales. No se ha renderizado el claro, comparado 0 píxeles, medido FOUC, inspeccionado CSP de un proxy productivo, ejecutado axe ni certificado lectores de pantalla/dispositivos físicos. Son criterios de aceptación de una implementación futura, no resultados de esta fase. No hay plan.md/tasks.md, aprobación ni PR nuevos.
