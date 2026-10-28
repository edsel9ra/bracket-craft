# Manual de usuario — Bracket Craft

Manual operativo alineado con el comportamiento real del producto. Complementa `README.md` (técnico) y `AGENTS.md`. Las rutas públicas son `/` y `/tournaments/{id}`; el Workspace (`/workspace`) requiere sesión y organización activa.

## 1. Acceso y organización

- Inicia sesión con email/contraseña o con Google (redirección). Si tu cuenta no tiene organización, se te ofrece crearla en `/organization` (nombre e identificador explícitos; «Ahora no» conserva la cuenta).
- El Workspace (`/workspace`) solo está disponible con sesión y una organización activa validada.
- La administración global vive en `/admin` y es independiente; no edita resultados ni versiones publicadas.
- La portada y el detalle de torneo son públicos: `/` y `/tournaments/{id}`. No requieren sesión.

## 2. Crear un torneo

1. En `/workspace`, crea un torneo con nombre, slug y configuración inicial.
2. Un torneo se versiona: edita en borrador y publica cuando esté listo. Las versiones publicadas son inmutables.
3. El avance entre fases es manual y solo en versiones en borrador: asigna equipos a una fase desde `GET/POST/DELETE /tournaments/{id}/stages/{stage_id}/teams`.

## 3. Configurar reglas

- En `/workspace/tournaments/{id}` (ancla `#configuracion`) usa el asistente de reglas (`?step=`).
- Configura puntuación, desempates, disciplina (tarjetas, suspensiones), sustituciones (`max_per_team`, `max_windows`, `allow_reentry`), ventana de inscripción (`roster_lock_matchday`), minutos (`regular_time_minutes`, `extra_time_minutes`), formato de juego (`game_format`: 5v5/7v7/9v9/11v11, declarativo) y límites de plantilla (`min_players_per_team`/`max_players_per_team`, 0 = sin límite).
- Los minutos salen de `stage_defaults` con overrides por fase; el máximo efectivo es el reglamentario para `regular`/`walkover`/`administrative` y el de prórroga para `extra_time`/`penalties` cuando la prórroga está habilitada.
- Guardar/publicar con `walkover_score.winner <= walkover_score.loser` se rechaza (422).
- El asistente guarda el paso en la dirección (`?step=`) y los datos en el almacenamiento de sesión de la pestaña (`bc_wizard:…`). Recargar conserva; otra pestaña empieza desde el servidor.

## 4. Configurar fases

- En `/workspace/tournaments/{id}` (ancla `#configuracion`) usa el asistente de fases.
- Tipos soportados: Round Robin, grupos, playoffs, Swiss (acotado: ≤64 equipos, presupuesto 50 000 evaluaciones, timeout 10 s).
- Las vueltas de liga/grupos se persisten (`schedule_legs`: 1 o 2).
- Sortear/regenerar calendario desde `/workspace/tournaments/{id}/calendar` con confirmación antes de reemplazar.

## 5. Equipos y plantillas

- Equipos: asistente en `/workspace/tournaments/{id}` (ancla `#equipos`); alta individual y en lote con `stage_id`.
- Plantillas: **única** pantalla `/workspace/tournaments/{id}/rosters` (`?team=`).
  - Alta individual, importación CSV/ZIP (campos: `first_name`, `last_name`, `national_id`, `birth_date`, `dorsal_number`; `photo_filename` vincula imágenes).
  - Foto y consentimiento de imagen por jugador.
  - Retiro/reactivación lógica (`PATCH …/rosters/{roster_id}/status` con `{is_active}`), sin borrar la fila.
  - El retiro es la única excepción al bloqueo por jornada; la reactivación se comporta como un alta.
  - Los límites de plantilla solo bloquean al inscribir en fase, al crear un equipo con `stage_id` y al abrir el primer segmento (409 `ROSTER_SIZE_OUT_OF_RANGE`); editar la plantilla nunca se bloquea por tamaño.
- Escudos de equipo: una imagen por equipo, compartida entre torneos, gestionada con `MANAGE_TOURNAMENTS` desde el torneo donde está inscrito. Formatos JPG/PNG/WEBP estáticos, máximo 5 MiB (compartido con fotos). `logo_url` externo es respaldo mientras no haya escudo y se retira (`null`) con la primera carga confirmada; nunca se muestra en público.

## 6. Calendario

- `/workspace/tournaments/{id}/calendar` (`?stage=`): crear partido manualmente, sortear/regenerar (con confirmación) y listar partidos con enlace a operación.
- No se regenera el calendario al asignar/quitar equipos manualmente.

## 7. Operación de partido y actas

- `/workspace/matches/{id}`: segmentos, planilla, oficiales, eventos y cierre.
- Segmentos: ventanas de tiempo con número consecutivo, `minute_start`, `minute_end` opcional y estado `active`/`completed`/`interrupted`. Crear con otro activo cierra el activo en su minuto. `GET …/operation` devuelve `next_segment` (propuesta calculada por el servidor).
- Planilla: publicar/despublicar formación táctica. Solo las publicadas son visibles públicamente.
- Eventos del acta (catálogo cerrado): `goal`, `own_goal`, `penalty_goal`, `yellow_card`, `red_card`, `substitution`, `foul`. `goal` admite `assist_player_id` opcional. `red_card` admite `metadata.red_card_type` (`direct_red` o `double_yellow_red`).
- Resolución prevista: un control único (`regular` por defecto) validado contra el máximo efectivo; vive en la sesión de la pestaña y se envía al crear/interrumpir segmentos y al cerrar.
- Cierre: elige resolución (`regular`, `extra_time`, `penalties`, `administrative`, `walkover`) y ganador cuando aplique. Walkover: `winner_team_id` + `reason` del catálogo (`no_show`, `withdrawal`, `insufficient_players`, `sanction`); el marcador se deriva de `walkover_score` de la fase; no exige segmento activo ni plantilla; no genera eventos ni sanciones. Resolución administrativa exige ganador y `reason` (texto libre 1..1000). Los marcadores de juego son opcionales y se ignoran si coinciden con la pareja derivada.
- La coherencia numérica del marcador (final < reglamentario, `regular` con final distinto, `penalties` sin empate, tanda igualada) es 409 de dominio.
- Una expulsión por doble amarilla exige exactamente dos amarillas previas del mismo jugador en el mismo acta; si no, 409 `DOUBLE_YELLOW_INCONSISTENT`.
- Al cerrar se crean sanciones (una por expulsión por doble amarilla, absorbiendo las amarillas), se actualiza clasificación y avance de llave, se emiten eventos al outbox. Las actas cerradas son inmutables.

## 8. Consulta pública

- Portada `/` lista torneos públicos. Detalle `/tournaments/{id}` muestra fases/grupos, clasificación, partidos con alineaciones publicadas y formaciones publicadas.
- Un torneo no visible responde 404 indistinguible.
- Estadísticas: `GET /tournaments/public/{id}/player-stats` y `GET /tournaments/public/{id}/team-stats`, con filtro opcional por fase.
- Portería imbatida: del equipo, partido disputado con cero goles recibidos (prórroga incluida, penales excluidos); del portero, identificable por `GK` en formación táctica publicada, titular del primer segmento o entrante acreditado por sustitución en formación publicada posterior, con ≥60 minutos y sin goles recibidos. Walkover y resolución administrativa no cuentan.
- No se publican: documentos de identidad, fecha de nacimiento, edad, plantilla inscrita, asistencias, sanciones, suspensiones, motivo de walkover/resolución administrativa, `logo_url` heredado, claves de almacenamiento, datos de miembros/organizaciones.
- Las fotos solo se publican con inscripción vigente + consentimiento de imagen + foto cargada; un jugador retirado lógicamente nunca publica foto (iniciales).

## 9. Verificación

- Suites puras: `cd backend && pytest -q` (sin `RUN_DATABASE_TESTS`), `cd frontend && pnpm test`, `node --test` donde aplique. Se ejecutaron y pasaron según los bloques A–G de la spec 023.
- Suites opt-in (PostgreSQL): `RUN_DATABASE_TESTS=1 pytest -q` con `DATABASE_ADMIN_URL`; se declaran no ejecutadas si no hay entorno.
- E2E: `pnpm run e2e`/`e2e:test` (Docker). En esta entrega el E2E falló por setup (`session.setup.ts`, «Workspace privado» no visible tras 30 s) y se declaró no ejecutado en verde (código de salida 2), sin modificar código.
- Accesibilidad: inspección manual documentada en `docs/inspeccion-accesibilidad.md`; la accesibilidad completa (contraste, `alt` en todas las vistas, orden de foco fuera de los asistentes) se declara no ejecutada en esta entrega por falta de navegador/entorno.
- Google por redirección: no ejecutado (sin cliente OAuth real configurado); solo se verificaron email/password, sesión y creación de organización.
- `verify_worker_loop_health.sh`: no ejecutado en esta entrega (sin Docker en el runner).
- Coherencia documental: `README.md`, `AGENTS.md` y esta spec se mantienen alineados; ante divergencia gana el código y la CI.
