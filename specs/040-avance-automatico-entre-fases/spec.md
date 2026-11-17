# Spec 040 — Avance automático entre fases (F2)

Estado: aprobada por el usuario (2026-11-16, «Apruebo la spec 040»). DA-1–DA-4 resueltas.

## Decisiones del usuario (2026-11-16)

- **DA-1 = (a).** El gestor ve la vista previa y confirma; nada se llena solo al cerrar el último partido.
- **DA-2 = (a).** Fases destino: eliminación simple y doble eliminación. Las fases de grupos como destino quedan fuera.
- **DA-3 = (a).** El gestor fija los cruces en el borrador asignando un origen a cada plaza de la primera ronda; el sistema ofrece una plantilla clásica sugerida que puede editar.
- **DA-4 = (a).** «Mejores N.º» se comparan con los criterios de la versión salvo el enfrentamiento directo; si los grupos de origen tienen distinto tamaño, esa comparación no se admite.

## Contexto y objetivo

Hoy el avance entre fases es manual y solo en borrador (spec 006): `GET/POST/DELETE /tournaments/{id}/stages/{stage_id}/teams`. Una vez publicada la versión, las asignaciones de equipos a fases (`stage_teams`) son inmutables, así que un torneo de grupos seguido de eliminatoria no puede llenar la eliminatoria con los clasificados reales: el organizador tendría que conocerlos antes de publicar. Dentro de una llave sí hay avance automático (enlaces de ganador/perdedor) y el suizo sortea rondas posteriores ya publicado.

F2 permite declarar en borrador **de dónde sale cada plaza** de una fase posterior (por ejemplo «1.º del grupo A» o «mejor 3.º n.º 1») y, cuando la fase de origen termina, **resolver esas plazas** con la clasificación vigente: vista previa, confirmación y llenado de la fase destino. Retoma lo que 006, 008 y 020 dejaron fuera (R12, sembrado por `stage_rank`).

Relación con la constitución: §2.3 prohíbe editar lo publicado. La resolución no edita la estructura: las plazas y su origen se declaran en borrador y quedan congeladas al publicar; resolver solo las llena con el resultado de una regla ya publicada, igual que los enlaces de llave y las rondas suizas. Ninguna plaza ya llena se reasigna (ver RF-010). No requiere enmienda.

## Usuarios

- Organizadores que operan torneos con varias fases.
- Público que sigue el torneo.

## Roles y visibilidad

- **Público:** ve los equipos de la fase destino solo después de confirmada la resolución, como hoy ve cualquier llave; no ve vistas previas ni plazas sin resolver más allá de su etiqueta («1.º grupo A»).
- **Miembro de organización sin permiso de gestión:** ve la declaración de origen y el estado de cada plaza; no puede resolver.
- **Administrador de organización / gestor (`MANAGE_TOURNAMENTS`):** declara orígenes en borrador, ve la vista previa y confirma la resolución.
- **Administrador de plataforma:** sin acciones nuevas.
- Ninguna organización ve ni modifica declaraciones, vistas previas ni resoluciones de otra.

## Historias de usuario

- HU-1. Como organizador, quiero declarar en borrador que la plaza 1 de la eliminatoria es «1.º del grupo A» para no tener que conocer los clasificados antes de publicar.
- HU-2. Como organizador, quiero ver qué equipos ocuparían cada plaza antes de confirmar, para detectar errores.
- HU-3. Como organizador, quiero que el sistema me impida resolver si la fase de origen no ha terminado o hay un empate que exige sorteo.
- HU-4. Como público, quiero ver la eliminatoria llena con los clasificados en cuanto el organizador la confirme.

## Definiciones

- **Plaza:** posición de un equipo en la primera ronda de la llave destino (en doble eliminación, la del cuadro de ganadores). Las rondas siguientes se siguen llenando por los enlaces de ganador y perdedor.
- **Fase de origen:** fase anterior de la misma versión de tipo todos contra todos, grupos o suizo (en las dos últimas sin grupos, la tabla única cuenta como un grupo).
- **Origen de plaza:** regla declarada en borrador: posición N de un grupo concreto de una fase de origen, o el k-ésimo mejor entre los equipos que acabaron en la posición N de todos los grupos de una fase de origen («mejores N.º»).
- **Plantilla clásica:** propuesta de orígenes que cruza posiciones altas con bajas de grupos distintos (1.º A contra 2.º B, 1.º B contra 2.º A…) y evita que dos equipos del mismo grupo se crucen en la primera ronda cuando es posible.
- **Fase de origen terminada:** todos sus partidos están finalizados o resueltos administrativamente (W.O.), sin partidos programados, en vivo ni suspendidos.
- **Clasificación vigente:** la de la fase de origen con las actas vigentes (incluidas rectificaciones publicadas).

## Requisitos funcionales

- **RF-001.** MIENTRAS la versión esté en borrador, EL SISTEMA permitirá a un gestor crear una llave de eliminación simple o doble con un número de plazas (2–64) y declarar el origen de cada plaza a partir de fases de origen de la misma versión, con los mismos pases libres que hoy genera la llave.
- **RF-001b.** CUANDO un gestor pida la plantilla clásica, EL SISTEMA propondrá orígenes para todas las plazas según los grupos y el número de plazas; el gestor puede aceptarla o editarla antes de guardar, y nada se guarda sin su acción.
- **RF-002.** SI un origen apunta a una fase que no es anterior, a un grupo o posición inexistente, o dos plazas declaran el mismo origen, o un «mejores N.º» pide más equipos de los que hay grupos, ENTONCES EL SISTEMA rechazará la declaración con un error que identifique la plaza.
- **RF-003.** CUANDO se publique la versión, EL SISTEMA congelará los orígenes declarados; cualquier intento de cambiarlos responderá 409.
- **RF-004.** CUANDO un gestor pida la vista previa de una fase destino, EL SISTEMA devolverá, por plaza, su origen y el equipo que la ocuparía con la clasificación vigente, sin escribir nada.
- **RF-005.** SI la fase de origen no ha terminado, ENTONCES EL SISTEMA marcará en la vista previa las plazas afectadas como no resolubles e impedirá confirmar.
- **RF-006.** SI dos equipos siguen empatados en una posición que decide una plaza tras aplicar todos los criterios declarados (incluido el sorteo determinista si la versión lo declara), ENTONCES EL SISTEMA lo indicará en la vista previa e impedirá confirmar.
- **RF-007.** CUANDO un gestor confirme la resolución con la vista previa vigente, EL SISTEMA llenará todas las plazas de la fase destino o ninguna, en una sola operación, y registrará en auditoría quién, cuándo y con qué clasificación.
- **RF-008.** SI la clasificación cambió entre la vista previa y la confirmación, ENTONCES EL SISTEMA rechazará la confirmación (409) y pedirá una vista previa nueva.
- **RF-009.** CUANDO se confirme la resolución, EL SISTEMA publicará el cambio a la vista pública y en tiempo real por los mismos canales que hoy usa la llave.
- **RF-010.** SI tras la confirmación una rectificación publicada cambia la clasificación de origen, ENTONCES EL SISTEMA no reasignará automáticamente ninguna plaza y registrará el impacto competitivo para su procedimiento auditado (spec 033).
- **RF-011.** EL SISTEMA mantendrá el avance manual de la spec 006 en borrador; una llave con orígenes declarados no admite además asignación manual ni el sorteo aleatorio actual.
- **RF-012.** CUANDO compare «mejores N.º» entre grupos, EL SISTEMA aplicará los criterios de clasificación de la versión en su orden, omitiendo el enfrentamiento directo.
- **RF-013.** SI los grupos de la fase de origen no tienen todos el mismo número de equipos, ENTONCES EL SISTEMA rechazará declarar «mejores N.º» sobre ella y, si el tamaño cambió después de declararlo, la vista previa lo indicará e impedirá confirmar.

## Requisitos no funcionales

- **RNF-001.** Vista previa y confirmación responden con un número de consultas acotado e independiente del número de partidos de la fase de origen.
- **RNF-002.** Dos confirmaciones simultáneas producen como máximo un llenado.
- **RNF-003.** Todas las lecturas y escrituras corren con RLS de la organización del torneo.
- **RNF-004.** Pantallas en ES/EN, accesibles y correctas en los temas claro y oscuro, a 1440 y 390 px.

## Datos personales y privacidad

No aplica: solo intervienen equipos y clasificaciones; no hay datos de jugadores nuevos ni campos públicos nuevos salvo la etiqueta de origen de cada plaza.

## Casos límite

- CL-1. Grupos de distinto tamaño: «posición N de un grupo» sigue admitida; «mejores N.º» no (RF-013).
- CL-7. Número de plazas que no es potencia de dos: los pases libres se colocan como hoy y la plantilla los asigna a los orígenes mejor clasificados.
- CL-8. Un grupo con menos de N equipos: un origen «posición N» sobre él se rechaza al declararlo.
- CL-2. Un partido de la fase de origen cancelado: cuenta como terminado solo si está resuelto administrativamente.
- CL-3. Un equipo descalificado o retirado tras terminar la fase: la vista previa lo señala y no se puede confirmar hasta resolverlo.
- CL-4. Rectificación publicada antes de confirmar: la vista previa usa la clasificación vigente.
- CL-5. Doble eliminación: solo se declaran las plazas del cuadro de ganadores; el de perdedores y la gran final siguen saliendo de los enlaces.
- CL-6. Versión clonada: los orígenes declarados se copian a la versión nueva en borrador.

## Fuera de alcance

- Reasignar plazas ya llenas (lo cubre el procedimiento de impacto competitivo de la 033).
- Orígenes entre torneos distintos.
- Sorteo de desempates dentro de esta spec (se usa el resultado ya registrado).
- Fases de grupos, todos contra todos o suizo como destino (DA-2).
- Siembra automática sin plantilla editable y sorteo de cruces al confirmar (DA-3).
- Cambios en `engine_version` o en el contrato de reglas.

## Criterios de finalización

1. Un torneo grupos → eliminatoria se publica sin conocer clasificados y la eliminatoria se llena tras confirmar.
2. Vista previa y bloqueo de RF-005/RF-006/RF-008 cubiertos por pruebas.
3. Ninguna plaza se reasigna tras una rectificación; el impacto queda registrado.
4. CI verde; README, AGENTS y manual actualizados.

## Dudas abiertas

Ninguna. DA-1–DA-4 resueltas arriba.
