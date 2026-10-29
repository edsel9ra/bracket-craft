# Tareas 025 — Orden, rótulos, ancla y enlaces del recorrido de configuración

Estado: T1–T4 completadas (2026-10-28)

> **Alcance.** Esta spec quedó **recortada** tras la división aprobada el 2026-10-28: cubre el reordenado y su presentación y navegación estática, y es **autocontenida y desplegable por sí sola**. La cadena de avance, el aviso de minutos y la cifra de composición están en `specs/026-cadena-de-avance-y-cifra/` y **no** se implementan aquí.
>
> **Pruebas primero.** T1 escribe las pruebas del comportamiento nuevo y las deja en rojo antes de tocar la presentación; T2 a T4 las ponen en verde.

- [x] **T1. Pruebas del orden, los rótulos, el ancla y el enlace cruzado (en rojo).** RF-001, RF-003, RF-004, RF-005, RF-006, RF-011, RF-012, RF-013, RF-017, RNF-001, RNF-004
- Hecho cuando: `frontend/tests/navigation.test.ts` comprueba la **posición relativa** de los tres asistentes, la cadena de los cuatro rótulos en español e inglés, el orden de `setupChecks`, `id="fases"` con su título, la sección activa con `#fases`, `legacySectionRedirect('#fases') === null`, el índice con cuatro entradas de configuración y ninguna «Fases», y la normalización sin doble escritura; `frontend/tests/stage-teams.test.ts` exige la dirección exacta `/workspace/tournaments/tournament-1#fases` de `phasesAssistantHref`; y `cd frontend && pnpm test` falla **solo** en esas comprobaciones nuevas, con el motivo esperado registrado en la tarea.

- [x] **T2. Reordenado de los tres asistentes y de la lista de verificación, sin regresión de «Siguiente»/«Anterior».** RF-001, RF-002, RF-006, RF-008, RF-009, RF-010, RF-017
- Hecho cuando: `frontend/app/pages/workspace/tournaments/[id]/index.vue` presenta reglas → equipos → fases en el marcado y `setupChecks` queda versión → equipos → fases → partidos → plantillas con textos, `detail` y umbrales intactos; `cd frontend && pnpm test` pasa con la prueba de posición relativa, la del orden de la checklist y `frontend/tests/wizard-step.test.ts` en verde sin cambios de expectativa, confirmando que ningún movimiento de «Siguiente»/«Anterior» cruza de asistente ni de sección y que abrir por paso o por ancla no cambia de sección.

- [x] **T3. Rótulos numerados es/en con «03 · Fases» pintado y ancla `#fases` enfocable.** RF-003, RF-004, RF-005, RF-011, RF-012, RNF-003, RNF-004
- Hecho cuando: `setup.rulesEyebrow`, `setup.teamsEyebrow`, `setup.stagesEyebrow` y `setup.calendarEyebrow` son exactamente «01 · Reglas», «02 · Equipos», «03 · Fases» y «04 · Calendario» —y su par inglés—, el panel de `StageTeamsWizard` lleva `id="fases"` y pinta su rótulo, el `<h2>` del asistente es enfocable con `tabindex="-1"` sin mover el foco por sí solo, el calendario pinta el `04` en su ruta y plantillas sigue sin número; `#resumen`, `#configuracion` y `#equipos` siguen resolviendo a su contenido y `WorkspaceShell.vue` no gana entradas; `cd frontend && pnpm test` pasa con las pruebas de rótulos, ancla e índice y `cd frontend && pnpm run typecheck` termina sin errores.

- [x] **T4. Enlaces cruzados al ancla, documentación y cierre.** RF-007, RF-013, RF-014, RF-015, RF-016, RNF-001, RNF-002, RNF-005
- Hecho cuando: `phasesAssistantHref` devuelve `/workspace/tournaments/{id}#fases` sin `?step=`, los dos puntos de origen (`TeamsWizard.vue` y `rosters.vue`) siguen ofreciendo el enlace y los borradores no se pierden al seguirlo; `docs/manual-usuario.md` presenta los apartados de configuración en el orden reglas → equipos y plantillas → fases → calendario, renumerados y sin referencias desfasadas, y describe el orden, la numeración, el ancla y los enlaces; `README.md` y `AGENTS.md` actualizan sus enumeraciones de apartados y su lista de cuatro anclas (`#resumen`, `#configuracion`, `#equipos`, `#fases`) sin repetir la secuencia numerada y sin recortar sus listas operativas; `frontend/e2e/` no cambia (`git diff --stat` acotado a `frontend/`, `docs/`, `README.md`, `AGENTS.md`); y pasan `cd frontend && pnpm test`, `cd frontend && pnpm run typecheck` y `cd frontend && pnpm run build`, sin relajar ninguna comprobación existente salvo la dirección del enlace declarada en T1, y con `MEMORY.md` registrando la fase y las decisiones de implementación.

## Trazabilidad de la cobertura exigida

| Cobertura | Tareas |
|---|---|
| Pruebas nuevas en rojo | T1 |
| Orden de asistentes y checklist | T2 |
| No regresión de «Siguiente»/«Anterior» y apertura | T2 |
| Rótulos es/en y «03 · Fases» visible | T3 |
| Ancla `#fases`, título enfocable e índice sin entradas | T3 |
| Enlaces cruzados sin paso | T1, T4 |
| Manual + README + AGENTS | T4 |
| Actualización de expectativas existentes | T1 (`stage-teams.test.ts`) |
| Cierre (`test`, `typecheck`, `build`) | T2, T3, T4 |
| Sin cambios de backend, esquema ni contratos | T4 |
