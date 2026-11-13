# Manual de usuario — Bracket Craft

Manual operativo alineado con el comportamiento real del producto. Complementa `README.md` (técnico) y `AGENTS.md`. Las rutas públicas son `/` y `/tournaments/{id}`; el Workspace (`/workspace`) requiere sesión y organización activa.

## 1. Acceso y organización

- Inicia sesión con email/contraseña o con Google (redirección). Si tu cuenta no tiene organización, se te ofrece crearla en `/organization` (nombre e identificador explícitos; «Ahora no» conserva la cuenta).
- El Workspace (`/workspace`) solo está disponible con sesión y una organización activa validada.
- La administración global vive en `/admin` y es independiente; no edita resultados ni versiones publicadas.
- La portada y el detalle de torneo son públicos: `/` y `/tournaments/{id}`. No requieren sesión.

### Apariencia e idioma

El selector **Tema** está junto a **Idioma**: en el grupo flotante de las vistas públicas y en la cabecera del Workspace o su menú móvil. El flotante público puede apilarse hacia arriba para no tapar contenido.

- **Oscuro** es la apariencia inicial cuando no has elegido ninguna.
- **Claro** mantiene siempre la paleta clara.
- **Sistema** sigue la apariencia clara u oscura de tu dispositivo, también cuando cambia mientras usas la aplicación.

En inglés las opciones son **Dark**, **Light** y **System**. Puedes usar el selector con el teclado. El cambio no recarga la página ni descarta tus formularios. La elección se guarda durante un año en una cookie opcional y se aplica ya al recargar; idioma y tema son preferencias independientes. Si el navegador bloquea esa cookie, el cambio funciona en la sesión actual, pero no se garantiza al recargar. El campo sigue verde en ambos temas y las fotos y escudos conservan su imagen original.

La preferencia también se aplica a la administración y al alta de organización, sin cambiar tus permisos. No se sincroniza entre dispositivos ni con tu cuenta; una preferencia guardada desconocida se trata como Oscuro, sin repararla automáticamente. Para seguir de nuevo la apariencia del dispositivo, elige **Sistema**.

## 2. Crear un torneo

1. En `/workspace`, crea un torneo con nombre, slug y configuración inicial.
2. Un torneo se versiona: edita en borrador y publica cuando esté listo. Las versiones publicadas son inmutables.
3. El avance entre fases es manual y solo en versiones en borrador: asigna equipos a una fase desde `GET/POST/DELETE /tournaments/{id}/stages/{stage_id}/teams`.

## 3. Configurar reglas

El recorrido de configuración de un torneo en borrador sigue el orden **Reglas → Equipos y plantillas → Fases → Calendario**, con la numeración visible «01 · Reglas», «02 · Equipos», «03 · Fases» y «04 · Calendario» (el `04` vive en la pantalla de calendario y la pantalla de plantillas no lleva número). Los apartados 3 a 6 de este manual cuentan esa misma secuencia. La configuración conserva las anclas `#resumen`, `#configuracion`, `#equipos` y `#fases`; `#fases` no añade ninguna entrada al índice del torneo —la sección activa sigue siendo Configuración— y es el destino de los enlaces equipos → fases y plantillas → fases, que no escriben ningún paso en la dirección: el propio asistente de fases resuelve su paso de entrada. Seguir esos enlaces no descarta el borrador de la pestaña de ningún asistente.

- En `/workspace/tournaments/{id}` (ancla `#configuracion`) usa el asistente de reglas (`?step=`).
- Configura puntuación, desempates, disciplina (tarjetas, suspensiones), sustituciones (`max_per_team`, `max_windows`, `allow_reentry`), ventana de inscripción (`roster_lock_matchday`), minutos (`regular_time_minutes`, `extra_time_minutes`), formato de juego (`game_format`: 5v5/7v7/9v9/11v11, declarativo) y límites de plantilla (`min_players_per_team`/`max_players_per_team`, 0 = sin límite).
- Los minutos salen de `stage_defaults` con overrides por fase; el máximo efectivo es el reglamentario para `regular`/`walkover`/`administrative` y el de prórroga para `extra_time`/`penalties` cuando la prórroga está habilitada.
- Guardar/publicar con `walkover_score.winner <= walkover_score.loser` se rechaza (422).
- El asistente guarda el paso en la dirección (`?step=`) y los datos en el almacenamiento de sesión de la pestaña (`bc_wizard:…`). Recargar conserva; otra pestaña empieza desde el servidor.

### Cadena de avance (spec 026)

La acción principal de cada sección abre la siguiente, **solo con guardado efectivo**: guardar las reglas abre **Equipos** (ancla `#equipos`); dar de alta equipos (individual o en lote) abre el asistente de **Fases** en su paso de entrada (identificación si la versión aún no tiene fases, composición si ya las tiene, con la identificación en solo lectura); confirmar una fase abre el **Calendario**. Con error, validación pendiente, guardado parcial o acción principal deshabilitada la pantalla se queda en la sección y muestra el error como hoy. El calendario es el final de la cadena: sus acciones no encadenan a otra sección. No viaja ningún mensaje de éxito entre secciones; el resultado se lee en la lista o el control propio del destino. La recarga posterior al guardado no condiciona el salto.

### Aviso de minutos y sus controles

Si el cambio de minutos deja segmentos ya registrados o eventos del borrador fuera del máximo nuevo (spec 012, RF-035), el aviso aparece **solo cuando el guardado ya terminó con éxito**, con dos controles: **«Continuar»** (descarta el aviso y abre Equipos) y **«Quedarme»** (descarta el aviso, cancela el salto y deja editar las reglas). Ninguno guarda ni envía peticiones. Editar una regla, un guardado nuevo o fallido, un cambio de versión o de torneo, una recarga o cualquier navegación descartan el aviso y el salto sin ejecutarlo. En solo lectura no hay aviso, controles ni salto. (Spec 026, RF-015 y RF-016.)

### Límite declarado

En el modo «fase existente» con **0 equipos seleccionados** la acción principal sigue deshabilitada: no hay escritura ni salto, y el usuario continúa por el índice del torneo (resumen, configuración, calendario y plantillas; operación solo si hay un partido en contexto) o por cualquier enlace que la pantalla ya ofrezca. Es un límite explícito del recorrido, no un defecto. (Spec 026, RF-004 y ORD-7.)

## 4. Equipos y plantillas

- Equipos: asistente en `/workspace/tournaments/{id}` (ancla `#equipos`); alta individual y en lote con `stage_id`.
- Plantillas: **única** pantalla `/workspace/tournaments/{id}/rosters` (`?team=`).
  - Alta individual, importación CSV/ZIP (campos: `first_name`, `last_name`, `national_id`, `birth_date`, `dorsal_number`; `photo_filename` vincula imágenes).
  - Foto y consentimiento de imagen por jugador.
  - Retiro/reactivación lógica (`PATCH …/rosters/{roster_id}/status` con `{is_active}`), sin borrar la fila.
  - El retiro es la única excepción al bloqueo por jornada; la reactivación se comporta como un alta.
  - Los límites de plantilla solo bloquean al inscribir en fase, al crear un equipo con `stage_id` y al abrir el primer segmento (409 `ROSTER_SIZE_OUT_OF_RANGE`); editar la plantilla nunca se bloquea por tamaño.
- Escudos de equipo: una imagen por equipo, compartida entre torneos, gestionada con `MANAGE_TOURNAMENTS` desde el torneo donde está inscrito. Formatos JPG/PNG/WEBP estáticos, máximo 5 MiB (compartido con fotos). `logo_url` externo es respaldo mientras no haya escudo y se retira (`null`) con la primera carga confirmada; nunca se muestra en público.

## 5. Configurar fases

- En `/workspace/tournaments/{id}` (ancla `#fases`) usa el asistente de fases. El bloque de fases es el destino de los enlaces «Ir al asistente de fases» del alta de equipos y de la pantalla de plantillas; esos enlaces no fijan ningún paso en la dirección.
- Tipos soportados: Round Robin, grupos, playoffs, Swiss (acotado: ≤64 equipos, presupuesto 50 000 evaluaciones, timeout 10 s).
- Las vueltas de liga/grupos se persisten (`schedule_legs`: 1 o 2).

### Cifra de composición (spec 026)

El paso de composición y el resumen de revisión muestran **un solo total** de equipos **inscritos + seleccionados** (equipos distintos), en el patrón «N de 64 equipos» mientras el total no supere 64 y el **total real** por encima de 64. La cifra no inscribe, no desinscribe ni envía ninguna petición. En el modo «fase existente» no se muestra ninguna cifra mientras la lista de inscritos no haya cargado (se ve el estado de carga del asistente); en el alta de una fase nueva aparece con los seleccionados en cuanto hay lista de equipos. `64` es el máximo **por petición de inscripción**, no un tope total de la fase: una fase puede acumular más de 64 en varias visitas. Los avisos de composición vacía, de equipos disponibles y el bloqueo por límites de plantilla no cambian. (Spec 026, RF-010 a RF-014.)
- Sortear/regenerar calendario desde `/workspace/tournaments/{id}/calendar` con confirmación antes de reemplazar.

## 6. Calendario

- `/workspace/tournaments/{id}/calendar` (`?stage=`): crear partido manualmente, sortear/regenerar (con confirmación) y listar partidos con enlace a operación.
- No se regenera el calendario al asignar/quitar equipos manualmente.

## 7. Operación de partido y actas

### Actualizaciones y recuperación del Workspace

Las actualizaciones privadas solo invalidan recursos cuya lectura esté autorizada
en ese momento; el detalle se vuelve a consultar por HTTP. La comprobación de
sesión periódica no concede permiso de lectura. Cambiar de organización o usuario
invalida las respuestas pendientes del contexto anterior. Una retirada confirmada
afecta a las evaluaciones posteriores, no retira lo ya recibido.

Tras publicar una rectificación, la operación y «Versiones del acta» se actualizan
sin pulsar «Actualizar». Con el editor abierto se conserva el borrador y se aplaza
la recarga del historial hasta terminar o cancelar. La conexión es de mejor
esfuerzo: al reconectar o resincronizar se reconstruye por HTTP el estado vigente,
no una lista de eventos perdidos. Si no se puede verificar la autorización se
suspenden las actualizaciones afectadas, sin convertirlas en públicas ni usar
permisos antiguos. Se mantienen los estados y el botón «Reintentar» existentes.

F8 está **implementada y aceptada** desde el 2026-11-13; R32f cerrado tras #78/T49. Esto no habilita borradores privados F1.
Los avisos de sanciones F9 permanecen en su bandeja/correo, fuera de Socket.IO.

El catálogo actual cubre cierre, actualización de partido, clasificación y sus
publicaciones rectificativas; no concede nuevas lecturas ni permisos de escritura.
Compatibilidad, despliegue coordinado y contingencia sin restaurar el broadcast:
[runbook de tiempo real](despliegue-tiempo-real-por-rol.md).

### Operación y cierre

- `/workspace/matches/{id}`: segmentos, planilla, oficiales, eventos y cierre.
- Segmentos: ventanas de tiempo con número consecutivo, `minute_start`, `minute_end` opcional y estado `active`/`completed`/`interrupted`. Crear con otro activo cierra el activo en su minuto. `GET …/operation` devuelve `next_segment` (propuesta calculada por el servidor).
- Planilla: publicar/despublicar formación táctica. Solo las publicadas son visibles públicamente.
- Eventos del acta (catálogo cerrado): `goal`, `own_goal`, `penalty_goal`, `yellow_card`, `red_card`, `substitution`, `foul`. `goal` admite `assist_player_id` opcional. `red_card` admite `metadata.red_card_type` (`direct_red` o `double_yellow_red`).
- Resolución prevista: un control único (`regular` por defecto) validado contra el máximo efectivo; vive en la sesión de la pestaña y se envía al crear/interrumpir segmentos y al cerrar.
- Cierre: elige resolución (`regular`, `extra_time`, `penalties`, `administrative`, `walkover`) y ganador cuando aplique. Walkover: `winner_team_id` + `reason` del catálogo (`no_show`, `withdrawal`, `insufficient_players`, `sanction`); el marcador se deriva de `walkover_score` de la fase; no exige segmento activo ni plantilla; no genera eventos ni sanciones. Resolución administrativa exige ganador y `reason` (texto libre 1..1000). Los marcadores de juego son opcionales y se ignoran si coinciden con la pareja derivada.
- La coherencia numérica del marcador (final < reglamentario, `regular` con final distinto, `penalties` sin empate, tanda igualada) es 409 de dominio.
- Una expulsión por doble amarilla exige exactamente dos amarillas previas del mismo jugador en el mismo acta; si no, 409 `DOUBLE_YELLOW_INCONSISTENT`.
- Al cerrar se crean sanciones (una por expulsión por doble amarilla, absorbiendo las amarillas), se actualiza clasificación y avance de llave, se emiten eventos al outbox. Las actas cerradas son inmutables.

### Corregir un acta confirmada (spec 033, criterios 1–9)

1. Abre el partido confirmado en el Workspace y elige «Solicitar rectificación». Completa la propuesta, el motivo y la evidencia; quedan asociados a tu identidad, fecha y versión base. Una solicitud inválida no se guarda.
2. No puedes decidir tu propia solicitud, aunque seas owner o administrador de plataforma. No verás los botones de aprobación/rechazo.
3. Otra persona con permiso de aprobación abre «Rectificaciones», revisa vigente/propuesta/diferencias, calcula la vista previa e indica el motivo de su decisión. Excepcionalmente el owner puede autorizar a plataforma para esa solicitud: la autorización se consume al decidir y ambas auditorías registran al responsable.
4. Mientras está pendiente, rechazada o retirada se conserva el resultado vigente. Puedes retirar tu pendiente. La vista previa no guarda nada; si la base ha cambiado debes actualizar y volver a previsualizar antes de aprobar.
5. Aprobar publica una versión nueva junto con sus efectos, sin borrar ni editar el original. «Versiones del acta» permite consultar también las anteriores.
6. Clasificación, estadísticas, sanciones y avance pendiente reflejan el resultado vigente. El público ve el nuevo marcador y «Resultado rectificado · fecha», no motivo/evidencia ni responsables.
7. Ningún partido posterior comenzado o confirmado ni sus sanciones se modifica. Un impacto conserva los partidos/asignaciones afectados y bloquea solo los no comenzados. Un aprobador organizativo lo cierra con `keep_as_played` y motivo; no existe repetición ni cierre desde plataforma.
8. El solicitante recibe por correo decisión y motivo, sin evidencia. Los avisos organizativos y el correo se registran mediante outbox, con reintentos SMTP; previsualizar no envía ni conserva notificaciones.
9. Solo puedes consultar o modificar recursos de tu organización; los ajenos se comportan como inexistentes o listas vacías.

Para verificarlo en desarrollo: ejecuta el seed y después `cd frontend && pnpm exec playwright test e2e/rectification.spec.ts --project workspace`. El seed proporciona dueño y segundo aprobador (`demo.approver@bracketcraft.dev`, contraseña ficticia `Demo1234!`), sin cuentas de producción. El E2E usa sesiones independientes, API y PostgreSQL reales, y comprueba además que el solicitante no puede decidir. Consulta la [verificación por criterio](../specs/033-acta-rectificativa/verificacion.md).

### Delegación excepcional de una rectificación (API, spec 033)

En el Workspace, «Rectificaciones» abre la bandeja y la revisión. Desde un partido confirmado, «Versiones del acta» muestra el original y las versiones publicadas, y «Solicitar rectificación» abre el editor si tienes permiso. Puedes cambiar resolución, marcadores, penales y eventos (incluido su orden), con motivo y evidencia obligatorios. La solicitud no cambia el acta vigente. Mediante la API, un dueño activo puede autorizar a un administrador de plataforma activo (no soporte) a decidir una solicitud pendiente concreta, indicando su correo y el motivo. Puede revocar una autorización vigente antes de la decisión. El administrador solo accede a las solicitudes para las que está autorizado; la autorización deja de servir al revocarla, consumirla, cerrar la solicitud o perder el autorizante su condición de dueño activo. No se admite decidir una solicitud propia. La decisión se registra con el usuario real de plataforma y no le concede pertenencia permanente a la organización. Al aprobar se recalcula la clasificación y se registra si un grupo antes empatado y resuelto por sorteo ya no conserva los mismos integrantes, sin cambiar el algoritmo ni la semilla del sorteo. También se crean las sanciones nuevas y se anulan con registro las que ya no corresponden: los cumplimientos anteriores se conservan y una sanción nueva no se cumple en un partido que ya había comenzado. Las sanciones posteriores a la confirmación original no bloquean retroactivamente la rectificación; si falta la fecha histórica se conserva la comprobación anterior. La vista previa muestra los efectos sin conservar cambios. Los cambios de acumulación que afectarían a partidos posteriores confirmados solo se calculan como candidatos: no modifican sus sanciones. Las notificaciones se encolan y registran mediante la outbox; la vista previa y las decisiones están disponibles en el Workspace.

Una rectificación también revisa el avance por enlaces de ganador y perdedor. Solo sustituye automáticamente un equipo si el destino sigue programado, no tiene segmentos ni resultado confirmado, el equipo anterior llegó exclusivamente por ese enlace y el nuevo coincide con su resultado rectificado. Si hay una fase posterior ya asignada tampoco hay sustitución automática. Se conservan las asignaciones anteriores y se registra la nueva con su trazabilidad. Si no es seguro sustituir, el sistema calcula un candidato para un procedimiento de impacto competitivo con todos los partidos afectados. La vista previa no conserva ninguna sustitución.

En «Rectificaciones» filtra solicitudes por estado y torneo, y usa Anterior/Siguiente para recorrer la bandeja. Los impactos tienen su propio filtro abierto/cerrado. En la revisión puedes comparar vigente/propuesta y diferencias; otro aprobador debe calcular la vista previa antes de aprobar, e indicar el motivo de su decisión. El solicitante puede retirar una pendiente pero no decidirla. Si cambia la versión base, actualiza y vuelve a previsualizar; un conflicto invalida la vista previa. El owner ve las autorizaciones incluso después de recargar y puede concederlas o revocarlas con confirmación.

En `/admin`, «Rectificaciones autorizadas» abre `/admin/rectifications`. Solo un administrador de plataforma activo, con autorización vigente del owner para esa solicitud, puede revisar y decidir. La revisión muestra el acta vigente, propuesta, diferencias y efectos simulados; aprobar exige vista previa, motivo y confirmación. La vista previa nunca consume la autorización ni conserva cambios o auditoría; la decisión sí consume la autorización y deja las auditorías correspondientes. No puedes decidir tu propia solicitud ni cerrar impactos desde esta pantalla. Una autorización revocada o consumida deja de dar acceso.

API de plataforma: `GET /api/v1/platform/rectifications`, `GET /api/v1/platform/rectifications/{rid}` (incluye `current_version`), `GET /api/v1/platform/rectifications/{rid}/preview` y `POST /api/v1/platform/rectifications/{rid}/decision`. Los previews organizativo y de plataforma devuelven `{version,effects,expected_base_version}`; la decisión recibe `{decision,reason,expected_base_version}`. Sin autorización vigente, detalle y preview responden el mismo 404 que una solicitud inexistente.

El público ve «Resultado rectificado · fecha» en las tarjetas de partido, el modal de alineaciones y la llave. La fecha procede de `rectified_at`; no se muestran el motivo, la evidencia, responsables ni versiones anteriores. Sin rectificación no aparece la marca. Está disponible en ambos temas y en ES/EN, con texto y fecha además de cualquier estilo visual.

Contrato API de la bandeja: `GET /api/v1/rectifications` y `GET /api/v1/competitive-impacts`, para cualquier miembro, admiten `status`, `tournament_id`, `limit=25` (1–100) y `offset=0` (≥0). Respuesta `{items,total,limit,offset}`, orden por fecha e ID descendentes; un torneo ajeno o inexistente produce la misma página vacía bajo RLS. Estados: solicitudes `pending|published|rejected|withdrawn`, impactos `open|closed`; valores o parámetros no admitidos dan 422. `GET /api/v1/rectifications/{rid}/platform-authorizations` es exclusivo del owner: lista vigentes/revocadas/consumidas, y responde el mismo 404 al resto o si no existe la solicitud. Leer impactos no permite cerrarlos.

Los procedimientos de impacto se consultan en `GET /api/v1/tournaments/{id}/competitive-impacts` por cualquier miembro de la organización. Incluyen snapshots de partidos y asignaciones; una fase afectada incluye todos sus partidos y los candidatos repetidos no duplican partidos. Mientras sigan abiertos, los afectados sin segmentos ni acta confirmada no pueden abrir su primer segmento ni cerrar el acta (409 `COMPETITIVE_IMPACT_OPEN`). Los ya comenzados no se bloquean por el procedimiento. Un aprobador organizativo puede cerrarlo mediante `POST /api/v1/competitive-impacts/{pid}/close`, con `{reason}` no vacío: únicamente mantiene lo jugado y las asignaciones existentes (`keep_as_played`), deja auditoría y libera ese bloqueo. No hay repetición, cierre desde plataforma ni cambios de sanciones posteriores o actas confirmadas. Las validaciones habituales siguen aplicándose tras el cierre.

Al aprobar o rechazar una rectificación, el solicitante recibe un correo con la decisión y su motivo, sin evidencia, también cuando decide plataforma. Se encola dentro de la transacción; un fallo de SMTP no deshace la decisión, sino que deja el correo en reintento con los límites habituales del worker. Publicar también encola los avisos de partido, clasificación y rectificación exclusivamente para la organización. Cada aviso y correo se registra, y la vista previa no conserva ninguna notificación ni evento. No se añaden datos al canal público.

### Apelar o resolver una sanción (spec 034, Workspace)

- «Expedientes de sanciones» abre la bandeja privada. Consultar exige la facultad de ver expedientes: los filtros muestran pendientes o archivo por estado y tipo; el detalle separa duración original/efectiva, cumplimientos, procedencia, resoluciones y su aplicación pendiente o acreditada.
- Con facultad de presentar puedes registrar una apelación indicando el identificador de sanción, representación de jugador/equipo y su identificador, y motivo. Evidencia opcional de texto/enlaces HTTP(S), sin archivos ni caducidad. El recibo no concede acceso al expediente al presentante ni al representado. La apelación no suspende ni modifica la sanción.
- Con facultad de resolver puedes proponer anular/reducir. Otra persona debe decidir, también si actúa como plataforma. Previsualiza el expediente, elige una decisión y confirma con motivo; una propuesta pendiente no tiene efecto. Una resolución no declarativa permanece pendiente hasta una apertura posterior acreditada; no cambia partidos ya comenzados.
- Solo el autor con permiso vigente puede retirar un expediente pendiente, con motivo y evidencia opcional. Si no tiene facultad de consulta, puede hacerlo desde el recibo que acaba de obtener al presentar/proponer, sin consultar el detalle. Un cierre por rectificación permite preparar una nueva presentación vinculada, que debes completar y enviar manualmente sobre una sanción vigente; nunca reabre el expediente anterior. Una decisión es definitiva: no hay segunda instancia ni retirada después de resolver.
- El dueño puede conceder/revocar autorización F9 puntual a un administrador de plataforma activo, indicando correo y motivo. Si no puede consultar expedientes, introduce un identificador conocido para gestionar únicamente esa autorización. No reutiliza autorizaciones de rectificación 033.
- «Avisos disciplinarios» contiene avisos internos de acto/motivo/decisión, sin evidencia. Ser destinatario no concede consulta: el enlace al expediente solo aparece con facultad de lectura. Los avisos se obtienen por HTTP, no por Socket.IO.
- Preparando una alineación, el aviso privado muestra jugador y partidos pendientes. Es informativo incluso si falla su consulta: guardar y publicar siguen disponibles y la alineación nunca se modifica automáticamente. El cierre conserva la revalidación disciplinaria.

### Decisión excepcional desde plataforma (spec 034, Administración)

1. Un dueño activo concede una autorización F9 para el expediente y el administrador de plataforma concretos. No basta con una autorización de rectificación 033.
2. En `/admin`, abre «Decisión excepcional de sanciones». La bandeja solo lista expedientes con autorización F9 vigente; no ofrece presentar apelaciones ni proponer medidas.
3. Abre «Ver expediente», consulta el historial privado y pulsa «Previsualizar decisión». Elige la decisión, indica el motivo y confirma «Registrar decisión». No puedes decidir sobre un expediente que hayas presentado tú.
4. La decisión revalida la sanción y los actores y consume la autorización. Al actualizar la bandeja, el expediente ya no aparece con ese scope; para futuras actuaciones hace falta una nueva autorización válida. Una revocación o denegación durante preview/decisión retira el detalle visible. La fecha de decisión y su aplicación efectiva son hechos distintos: no modifica partidos ya comenzados.

Todo este contenido es privado. La consulta pública no muestra sanciones, expedientes, motivos, evidencia, responsables, decisiones ni cumplimientos. Las pantallas y confirmaciones están disponibles en ES/EN y tema claro/oscuro; las verificaciones y sus límites se documentan en `specs/034-apelaciones-sanciones/verificacion.md`.

## 8. Consulta pública

- Portada `/` lista torneos públicos. Detalle `/tournaments/{id}` muestra fases/grupos, clasificación, partidos con alineaciones publicadas y formaciones publicadas.
- «Ver torneos» lleva directamente al listado desde la primera pantalla. El marcador fijo de portada es un ejemplo, no un partido real. Registro y documentación siguen disponibles.
- En el detalle, «Resultados», «Estadísticas» y «Equipos» enlazan a sus secciones, también sin JavaScript. El selector de fase aparece antes de la lista completa de equipos; esta conserva su propio acceso.
- Las estadísticas abren en «Torneo completo»; elegir una fase y restaurar el torneo completo es independiente del calendario. Posición y empates son los recibidos del servidor. El recuento indica filas mostradas y el criterio de orden está junto a cada tabla. En móvil se ven inicialmente Posición/Jugador/Goles o Posición/Equipos/GF; las demás métricas se alcanzan con scroll local y la identidad permanece fija. Clasificación también tiene pista y región de scroll con foco de teclado.
- Un torneo no visible responde 404 indistinguible.
- La llave permite desplazamiento horizontal local, también con teclado. Usa Final, Semifinales, Cuartos u Octavos cuando los códigos publicados identifican la ronda; en otro caso conserva «Ronda n» o una etiqueta genérica.
- Los conectores solo muestran avances inequívocos: ganador confirmado del partido anterior y participante del siguiente, también por penales o W.O. Un partido sin línea no implica eliminación ni pase libre; pendientes y participantes por definir permanecen visibles. La relación también está disponible en texto accesible y el ganador no se indica solo por color.
- Estadísticas: `GET /tournaments/public/{id}/player-stats` y `GET /tournaments/public/{id}/team-stats`, con filtro opcional por fase.
- Portería imbatida: del equipo, partido disputado con cero goles recibidos (prórroga incluida, penales excluidos); del portero, identificable por `GK` en formación táctica publicada, titular del primer segmento o entrante acreditado por sustitución en formación publicada posterior, con ≥60 minutos y sin goles recibidos. Walkover y resolución administrativa no cuentan.
- No se publican: documentos de identidad, fecha de nacimiento, edad, plantilla inscrita, asistencias, sanciones, suspensiones, motivo de walkover/resolución administrativa, `logo_url` heredado, claves de almacenamiento, datos de miembros/organizaciones.
- Las fotos solo se publican con inscripción vigente + consentimiento de imagen + foto cargada; un jugador retirado lógicamente nunca publica foto (iniciales).

## 9. Verificación

Los errores de validación de los campos aparecen debajo del control. La
verificación automática incluye el enlace explícito de los componentes UI
para evitar que un componente de error quede sin resolver y oculte el mensaje.

- Suites puras: `cd backend && pytest -q` (sin `RUN_DATABASE_TESTS`), `cd frontend && pnpm test`, `node --test` donde aplique. Se ejecutaron y pasaron según los bloques A–G de la spec 023.
- Suites opt-in (PostgreSQL): `RUN_DATABASE_TESTS=1 pytest -q` con `DATABASE_ADMIN_URL`; se declaran no ejecutadas si no hay entorno.
- E2E: `pnpm run e2e`/`e2e:test` (Docker). En esta entrega el E2E falló por setup (`session.setup.ts`, «Workspace privado» no visible tras 30 s) y se declaró no ejecutado en verde (código de salida 2), sin modificar código.
- Accesibilidad: inspección manual documentada en `docs/inspeccion-accesibilidad.md`; la accesibilidad completa (contraste, `alt` en todas las vistas, orden de foco fuera de los asistentes) se declara no ejecutada en esta entrega por falta de navegador/entorno.
- Google por redirección: no ejecutado (sin cliente OAuth real configurado); solo se verificaron email/password, sesión y creación de organización.
- `verify_worker_loop_health.sh`: no ejecutado en esta entrega (sin Docker en el runner).
- Coherencia documental: `README.md`, `AGENTS.md` y esta spec se mantienen alineados; ante divergencia gana el código y la CI.
