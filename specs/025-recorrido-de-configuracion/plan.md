# Plan 025 — Orden, rótulos, ancla y enlaces del recorrido de configuración

Estado: aprobado (2026-10-28)

Parte de `specs/025-recorrido-de-configuracion/spec.md` (**17 RF, 5 RNF**, ORD-1, ORD-2 revisada de nuevo, ORD-3 y la parte de enlaces de ORD-13). El plan no añade requisitos: describe cómo se cumplen. Las tareas están en `tasks.md`.

> **Alcance tras la división.** Esta spec se queda con el **reordenado y su presentación y navegación estática** y es **autocontenida y desplegable por sí sola**. La **cadena de avance**, el **aviso de minutos** y la **cifra de composición** viven en `specs/026-cadena-de-avance-y-cifra/` y **no** aparecen en este plan: no se tocan el salto entre secciones, los controles del aviso, el total de equipos ni el arnés E2E.

## 1. Alcance del cambio

Cambio **solo de frontend** (Nuxt 4 / Vue 3), más documentación. Se toca:

- El documento de configuración del torneo (`/workspace/tournaments/{id}`) y la pantalla de calendario.
- La utilidad pura del enlace cruzado y las traducciones de los rótulos.
- Las pruebas de navegación, del asistente de equipos y del enlace desde plantillas.
- El manual de usuario, `README.md` y `AGENTS.md`.

**Confirmaciones de alcance (RNF-005):**

- **Sin backend:** no se toca ningún módulo de `backend/app/`, ni `backend/app/main.py`, ni `scripts/`.
- **Sin migraciones ni esquema:** no se crea ninguna migración; el esquema sigue en **031**.
- **Sin contratos HTTP:** ningún endpoint, campo de respuesta, parámetro de consulta, código `code` ni `engine_version` nuevos; las peticiones de los asistentes son las mismas y en el mismo orden (RF-015).
- **Sin permisos nuevos:** no se añade rol, permiso ni visibilidad; el observador sigue en solo lectura (RF-016).
- **Sin rediseño visual:** no se cambian tipografía, espaciado, colores ni estructura de los paneles; solo los rótulos, el orden del documento, el ancla y el destino de dos enlaces (RF-003, RF-015).
- **Sin tocar el arnés E2E:** `frontend/e2e/` y su veredicto quedan igual (RNF-002), porque ningún anclaje del arnés depende del orden, de los rótulos numerados ni del enlace cruzado.

## 2. Archivos y responsabilidades

| Archivo | Responsabilidad en este cambio | RF |
|---|---|---|
| `frontend/app/pages/workspace/tournaments/[id]/index.vue` | Orden del documento (Reglas → Equipos → Fases) y orden de los ítems de `setupChecks`; el bloque de fases ya queda identificado por el panel del asistente. | RF-001, RF-002, RF-006 |
| `frontend/app/components/StageTeamsWizard.vue` | Raíz del panel con `id="fases"` y el rótulo visible `03 · Fases` encima de `WizardShell`. | RF-003, RF-004 |
| `frontend/app/components/wizard/WizardShell.vue` | El `<h2>` del asistente (`wizard-title-phases`) pasa a ser enfocable (`tabindex="-1"`), sin mover el foco por sí solo. | RF-004, RNF-003 |
| `frontend/app/pages/workspace/tournaments/[id]/calendar.vue` | Rótulo `04 · Calendario` en su propia pantalla; sin otros cambios. | RF-003 |
| `frontend/app/composables/useI18n.ts` | Rótulos numerados es/en: `01 · Reglas`/`01 · Rules`, `03 · Fases`/`03 · Stages`, `04 · Calendario`/`04 · Schedule`; `02 · Equipos`/`02 · Teams` se conserva. | RF-003, RNF-004 |
| `frontend/app/utils/teamsWizard.ts` | `phasesAssistantHref` devuelve `/workspace/tournaments/{id}#fases`, sin `?step=`. | RF-013 |
| `frontend/app/utils/tournamentNavigation.ts` | Sin cambio de comportamiento: `#fases` ya resuelve a `configuration` y `legacySectionRedirect` ya devuelve `null` para `fases`. Solo se cubre con pruebas. | RF-004, RF-005, RF-017 |
| `frontend/app/components/WorkspaceShell.vue` | Sin cambio: conserva las cuatro entradas de configuración y la de operación condicionada. Prueba de que no gana entradas. | RF-005 |
| `frontend/tests/navigation.test.ts` | Posición relativa de los tres asistentes, cadena de rótulos, orden de `setupChecks`, ancla `#fases`, sección activa, `legacySectionRedirect`, índice sin entradas nuevas, normalización sin doble escritura. | RF-001, RF-003, RF-004, RF-005, RF-006, RF-011, RF-012 |
| `frontend/tests/stage-teams.test.ts` | Dirección exacta del enlace a fases actualizada a `#fases` sin paso. | RF-013, RNF-001 |
| `frontend/tests/roster-lock.test.ts` | Sin cambio: sigue exigiendo que el enlace desde plantillas exista; pasa con la dirección nueva. | RF-013, RF-014 |
| `frontend/tests/wizard-step.test.ts` | No regresión del paso en la dirección, normalización y «Siguiente»/«Anterior». | RF-008 a RF-012, RF-017 |
| `docs/manual-usuario.md` | Apartados de configuración en el orden nuevo, renumerados; orden, numeración, ancla `#fases` y enlaces cruzados descritos. | RF-007, RNF-002 |
| `README.md` | Enumeración de apartados del manual y de anclas de la configuración (`#fases`); sin repetir la secuencia numerada. | RF-007, RNF-002 |
| `AGENTS.md` | La misma actualización de enumeraciones y anclas. | RF-007, RNF-002 |

**Fuera del cambio (y de la 026):** `frontend/app/components/StageTeamsWizard.vue` en lo relativo a la cifra de composición y al evento de confirmación; `frontend/app/pages/workspace/tournaments/[id]/index.vue` en lo relativo a la navegación posterior al guardado y al aviso de minutos; `frontend/app/utils/stageComposition.ts` y `frontend/app/utils/sectionAdvance.ts` (no existen en esta spec); `frontend/e2e/`; `frontend/app/composables/useApi.ts` (no hay llamadas nuevas); `frontend/app/utils/wizardStep.ts` y `useWizardStep.ts` (la fuente del paso no se toca); `frontend/app/utils/stageTeams.ts` (peticiones y modelo); `infra/` y `backend/`.

## 3. Funciones puras

### 3.1 `phasesAssistantHref` (firma sin cambio)

```ts
export function phasesAssistantHref(tournamentId: string): string {
  return `/workspace/tournaments/${tournamentId}#fases`;
}
```

- Deja de fijar `phases.identity` y el ancla `#configuracion`.
- No crea ruta ni parámetro nuevos: solo el fragmento `#fases` (RF-004, RF-013).
- No lee el entorno ni el estado del borrador: el paso de entrada lo resuelve el asistente al montar (RF-011).

**Decisión (D-1):** el enlace se resuelve en la función pura que ya existe y consumen los dos puntos de origen. *Alternativa descartada:* construir la dirección en cada vista (`TeamsWizard.vue` y `rosters.vue`) —duplicaría la regla del ancla sin paso y las dos copias podrían divergir, además de perder la prueba pura de la dirección exacta—.

### 3.2 Sin funciones nuevas

El reordenado, los rótulos y el ancla son presentación y marcado; no hay lógica con estado ni cálculos que exigieran un módulo puro nuevo (RF-015). La normalización del paso se conserva tal como está (`wizardStep.ts`).

## 4. Mecanismo

### 4.1 Orden del documento (RF-001, RF-002)

En `index.vue`, el bloque de reglas se mueve por encima del de equipos y el de equipos por encima del de fases. No se reordena nada más: el resumen, la barra de versión y la lista de verificación conservan su posición. El orden de tabulación sigue al del marcado, así que se cumple sin `tabindex` positivo (que no se usa).

### 4.2 Lista de verificación (RF-006)

`setupChecks` pasa a declarar los ítems en el orden **versión → equipos → fases → partidos → plantillas**. Solo cambia el orden de las entradas: textos, `detail`, `valid` y umbrales se copian sin tocar. El ítem «Equipos» sigue midiendo asignaciones de fase (`draftAssignedStageTeamCount`).

### 4.3 Rótulos y ancla (RF-003, RF-004, RF-005)

- `setup.rulesEyebrow`: «Reglas» → «01 · Reglas» («01 · Rules»).
- `setup.teamsEyebrow`: «02 · Equipos» / «02 · Teams» sin cambio.
- `setup.stagesEyebrow`: «01 · Fases» → «03 · Fases» («03 · Stages») y **se pinta por primera vez**, en la raíz del panel de `StageTeamsWizard`.
- `setup.calendarEyebrow`: «03 · Calendario» → «04 · Calendario» («04 · Schedule»).
- El panel de `StageTeamsWizard` recibe `id="fases"` en su `<section>` raíz; el `<h2 id="wizard-title-phases">` de `WizardShell` recibe `tabindex="-1"` para ser enfocable y anunciarse al recibir el foco.
- `WorkspaceShell.vue` y `tournamentNavigation.ts` **no cambian**: el índice conserva sus cuatro entradas de configuración más operación condicionada, la sección activa sigue siendo Configuración y `#fases` no redirige.

**Decisión (D-2):** el ancla y el rótulo viven en la raíz del panel del asistente. *Alternativas descartadas:* envolver el asistente en un panel nuevo desde la página —panel dentro de panel o título fuera del panel con estilos nuevos, que es rediseño—; y poner solo el `id` sin rótulo —el destino no tendría el título numerado visible que RF-003 y RF-004 exigen—.

**Decisión (D-3):** el título enfocable es el `<h2>` que ya existe en `WizardShell`. *Alternativa descartada:* añadir un `<h2>` nuevo en la página —duplicaría el título del asistente y rompería `aria-labelledby` del shell—.

### 4.4 Enlaces cruzados (RF-013, RF-014)

`TeamsWizard.vue` y `rosters.vue` siguen consumiendo `phasesAssistantHref`; no cambian sus plantillas. El enlace resultante es `#fases` sin paso, así que el asistente de fases resuelve su paso de entrada con `useWizardStep` y el `?step=` presente no se añade ni se retira. Seguir el enlace no descarta ningún borrador de pestaña.

### 4.5 No regresión de la navegación (RF-008 a RF-012, RF-017)

No se toca `WizardShell` en su navegación (`previousId`/`nextId`), ni `wizardStep.ts`, ni `useWizardStep.ts`. El reordenado no puede cambiar el destino de «Siguiente»/«Anterior» porque esas funciones trabajan sobre `WizardKind` y no sobre la posición en el documento; las pruebas lo confirman. Abrir por paso, por ancla o con `#fases` no cambia de sección (RF-017).

## 5. Interfaz

- **Pantallas:** la configuración del torneo (Reglas → Equipos → Fases) y el calendario (`04 · Calendario`). No hay pantallas nuevas.
- **Direcciones:** ninguna ruta ni parámetro nuevos. `#fases` es la única adición de fragmento; el enlace cruzado deja de nombrar paso.
- **Contratos:** ninguno. Los asistentes conservan sus peticiones en el mismo número y orden.
- **Traducciones:** `setup.rulesEyebrow`, `setup.stagesEyebrow` y `setup.calendarEyebrow` en es/en; sin claves nuevas.

## 6. Estrategia de tests

La suite de frontend es de Node (`node --test`): prueba funciones puras e inspecciona el fuente de páginas y componentes. Los tests se escriben **antes** del cambio de presentación y se confirman en rojo (T1).

1. **Puras:** `frontend/tests/stage-teams.test.ts` exige la dirección exacta `…/tournament-1#fases` en `phasesAssistantHref`.
2. **De fuente (ampliadas):** `navigation.test.ts` cubre la posición relativa de los tres asistentes, la cadena de rótulos en los dos idiomas, el orden de `setupChecks`, `id="fases"` con su título, `tabindex` del título, sección activa, `legacySectionRedirect('#fases') === null`, índice sin «Fases» y normalización sin doble escritura.
3. **No regresión:** `wizard-step.test.ts` (pasos, normalización, «Siguiente»/«Anterior») y `roster-lock.test.ts` (enlace desde plantillas) sin cambios de expectativa.
4. **Cierre:** `pnpm test`, `pnpm run typecheck` y `pnpm run build`. El arnés E2E no se ejecuta como parte de esta spec porque no se modifica y no depende de los anclajes cambiados; si se ejecuta, se informa aparte. Lo que no pueda ejecutarse se declara **no ejecutado**.

## 7. Decisiones y alternativas descartadas

| # | Decisión | Alternativa descartada | Motivo |
|---|---|---|---|
| D-1 | Actualizar `phasesAssistantHref` a `#fases` sin paso | Construir la dirección en cada vista; mantener `?step=phases.identity#configuracion` | Una sola definición del destino, con prueba pura, y orden coherente con ORD-13 |
| D-2 | Ancla y rótulo en la raíz del panel del asistente de fases | Envoltorio con panel nuevo; solo `id` sin rótulo | Evita paneles anidados y estilos nuevos, y el destino conserva título visible |
| D-3 | El `<h2>` de `WizardShell` es el título enfocable del bloque | `<h2>` nuevo en la página | No duplica el título ni rompe `aria-labelledby` del shell |
| D-4 | El índice y `tournamentNavigation.ts` no cambian; solo pruebas | Añadir entrada «Fases» al índice | ORD-2 revisada de nuevo y RF-005 |
| D-5 | Manual como fuente normativa única; README y AGENTS solo actualizan enumeraciones | Repetir la secuencia numerada en README y AGENTS | RNF-002 y constitución §4 |
| D-6 | Actualizar la expectativa de `stage-teams.test.ts` a la dirección nueva | Mantener la dirección antigua o retirar la aserción | RNF-001: se actualiza sin relajar; la dirección exacta se sigue exigiendo |
| D-7 | No tocar `frontend/e2e/` | Ajustar el arnés «por si acaso» | Ningún anclaje del arnés depende de rótulos, orden ni enlace cruzado (RNF-002) |

## 8. Cobertura de requisitos por parte

| Parte | RF/RNF |
|---|---|
| Reordenado del documento y de la lista de verificación | RF-001, RF-002, RF-006 |
| Rótulos numerados y traducciones | RF-003, RNF-004 |
| Ancla `#fases`, título enfocable e índice | RF-004, RF-005, RNF-003 |
| Enlaces cruzados equipos → fases y plantillas → fases | RF-013, RF-014 |
| No regresión de pasos, borradores y apertura | RF-008, RF-009, RF-010, RF-011, RF-012, RF-015, RF-017 |
| Permisos y solo lectura | RF-016 |
| Documentación | RF-007, RNF-002 |
| Pruebas y ausencia de efectos | RNF-001, RNF-005 |

## 9. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento por tenant con RLS | No | No hay consultas ni esquema nuevos; la pantalla sigue mostrando solo el torneo de la organización activa y no acepta identificadores ajenos (RF-002, RF-013). |
| §2.2 La aplicación no elude RLS | No | No se toca el backend ni el rol de base de datos. |
| §2.3 Lo publicado es inmutable | Sí | El cambio es de presentación y navegación; no escribe nada, tampoco en una versión publicada, que se muestra en solo lectura con el mismo orden (RF-016). |
| §2.4 Historial de esquema append-only | No | Sin migraciones ni cambios de esquema (RNF-005). |
| §2.5 Lo público es una proyección mínima | No | No se tocan proyecciones públicas ni datos de jugadores. |
| §2.6 Ningún secreto por defecto fuera de desarrollo | No | No hay variables de entorno nuevas. |
| §2.7 Administración global separada y auditada | No | `/admin` queda fuera del alcance. |
| §2.8 Nada se da por terminado sin verificación | Sí | `pnpm test`, `pnpm run typecheck` y `pnpm run build`; lo no ejecutable se declara no ejecutado. |
| §2.9 El código de desarrollo no llega a producción | No | No se añaden seeds ni datos demo. |
| §3.1 Base de datos y multi-tenancy | No | Sin migraciones, tablas ni políticas. |
| §3.2 Backend | No | Sin módulos, routers, outbox ni reglas de dominio. |
| §3.3 Frontend: `useApi.ts` y rutas | Sí | No hay llamadas nuevas ni modificadas: los asistentes conservan sus peticiones por `useApi.ts` en el mismo orden (RF-015); solo se trabaja en rutas del Workspace, sin rutas públicas nuevas. |
| §3.4 Seguridad y configuración | No | Sin secretos, dependencias ni configuración nuevos. |
| §3.5 Infraestructura y CI | No | No cambian versiones, lockfile ni Compose; el job `e2e` no cambia porque el arnés no se toca (RNF-002). |
| §4 Pasa el job de CI que aplique | Sí | `frontend` (`pnpm test`, `typecheck`, `build`). El job `e2e` no cambia y, si se ejecuta, se informa aparte. |
| §4 Sin secretos, credenciales ni datos personales | Sí | El cambio no introduce datos personales ni secretos; la documentación y las pruebas no los incluyen. |
| §4 Documentación actualizada si cambia el comportamiento | Sí | Manual, `README.md` y `AGENTS.md` en el mismo cambio (RF-007, RNF-002). |
| §4 Pruebas del comportamiento nuevo o corregido | Sí | Pruebas puras y de fuente para orden, rótulos, ancla y enlace (RNF-001). |
| §4 Cambios de base de datos / API / infraestructura / dependencias | No | No aplican: sin migración, sin backend, sin infraestructura y sin dependencias. |
| §5.1 Excepciones | No | No se requiere ninguna excepción. |

## 10. Riesgos y límites declarados

- **Foco del ancla:** `#fases` no mueve el foco al abrir la página con el fragmento; solo deja el título enfocable y el bloque a la vista. Es la accesibilidad que esta spec promete (RNF-003). Quien navega por el enlace cruzado desde otra pantalla llega al bloque por desplazamiento del navegador.
- **Título compartido:** hacer enfocable el `<h2>` de `WizardShell` afecta a los tres asistentes. Es inocuo (no cambia el orden de tabulación ni añade paradas) y evita duplicar títulos.
- **Documentación repartida:** este cambio actualiza el **orden, la numeración, el ancla y los enlaces** del manual y de las enumeraciones de README y AGENTS. La descripción de la cadena, del aviso y de la cifra llega con la 026, que depende de esta.
- **Sin despliegue parcial a medias:** esta spec no deja ninguna pieza a medio conectar. El enlace cruzado funciona por sí solo con `#fases`, y el bloque de fases se ve sin necesidad de la cadena.
