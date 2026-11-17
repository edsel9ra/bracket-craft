# Tareas — Spec 040: Avance automático entre fases (F2)

Estado: aprobadas por el usuario el 2026-11-16. PR documental y un PR por bloque: A (T1–T6, migración y backend) y B (T7–T11, frontend, E2E, documentación y cierre).

## Bloque A

- [ ] **T1. Migración 063.** RF-003, RF-007, RNF-002, RNF-003
- Hecho cuando: `RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_063.py` en rojo y luego verde (CHECK con `stage_rank`, RLS/FORCE y políticas, `UNIQUE (stage_id)`, append-only, excepción solo para `INSERT` en `stage_teams` con resolución válida, rechazo con resolución de otra fase u organización); cadena limpia 001→063 y salto 062→063.

- [ ] **T2. Funciones puras.** RF-002, RF-006, RF-008, RF-012, RF-013, CL-1, CL-2, CL-7, CL-8
- Hecho cuando: `pytest -q tests/test_stage_slot_origins.py` en rojo y luego verde (validación, plantilla clásica, cabezas de serie y pases libres, mejores N.º sin enfrentamiento directo, empates no resolubles, huella estable, fase terminada).

- [ ] **T3. Declarar orígenes y generar la llave en borrador.** RF-001, RF-001b, RF-002, RF-003, RF-011, CL-5
- Hecho cuando: `GET/PUT slot-origins` y `GET slot-origins/template` con tests DB: borrador 200, publicado 409, 422 por plaza, doble eliminación solo con potencia de dos, avance manual y sorteo 409 en llave con orígenes.

- [ ] **T4. Vista previa.** RF-004, RF-005, RF-006, RF-012, RF-013, CL-2, CL-3, CL-4
- Hecho cuando: `GET resolution/preview` sin escrituras, motivos por plaza y número de consultas constante (RNF-001).

- [ ] **T5. Confirmación.** RF-007, RF-008, RF-009, RNF-002
- Hecho cuando: `POST resolution` llena todo o nada, 409 por huella obsoleta o ya resuelta, carrera de dos confirmaciones → una, auditoría `STAGE_SLOTS_RESOLVED` y `MATCH_UPDATED` por partido, 404 entre organizaciones.

- [ ] **T6. Clonado, rectificación y lectura pública.** RF-010, CL-6, §8 del plan
- Hecho cuando: el clon reasigna IDs, una rectificación posterior abre `later_phase` sin cambiar plazas, y `home_origin`/`away_origin` aparecen solo en plazas sin resolver; suite backend completa, ruff y bandit en verde.

## Bloque B

- [ ] **T7. Editor de orígenes en el borrador.** RF-001, RF-001b, RF-002, RNF-004
- [ ] **T8. Panel de resolución en lo publicado.** RF-004–RF-008, RNF-004 (confirmación con `useConfirm` y `singleFlight`)
- [ ] **T9. Etiqueta de origen en la llave pública.** RF-009, §8 del plan
- [ ] **T10. E2E** `stage-advancement.spec.ts` (proyecto `workspace`) y etiqueta en `public-polish` a 1440/390 px en los dos temas, con axe sin violaciones.
- [ ] **T11. Documentación y cierre:** runbook de la 063 en README, AGENTS, manual, matriz de la 020 y MEMORY; evidencia por RF, RNF y CL.
