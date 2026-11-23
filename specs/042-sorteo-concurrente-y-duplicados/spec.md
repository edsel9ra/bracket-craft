# Spec 042 — Sorteo concurrente y duplicados en calendarios generados (F11)

Estado: aprobada por el usuario el 2026-11-23 («Apruebo la spec»). DA-1–DA-4 resueltas el 2026-11-22.

## Decisiones del usuario (2026-11-22)

- **DA-1 = (a).** Además del bloqueo, una migración nueva impide en la base de datos dos partidos generados con el mismo código en la misma fase y versión.
- **DA-2 = (a).** Si ya hay códigos repetidos, la migración se detiene sin cambiar nada y lista las fases afectadas para regenerarlas.
- **DA-3 = (a).** El calendario generado se comprueba antes de guardarlo; si falla, 409 y no se guarda nada. Sin aviso nuevo en el Workspace.
- **DA-4 = (a).** Dos reemplazos simultáneos se aplican uno tras otro y queda el último; nunca se mezclan partidos.
  - **Aclaración Swiss (2026-11-23, «Dejar swiss como está»).** En Swiss el emparejamiento se calcula fuera del bloqueo y se revalida dentro; si dos reemplazos coinciden, se aplica el primero y el segundo recibe 409 «el estado de la fase cambió durante el sorteo; vuelve a intentarlo». Tampoco se mezclan partidos. Recalcular dentro del bloqueo alargaría la transacción que el presupuesto de cálculo Swiss evita.

## Contexto y objetivo

La spec 005 aceptó como riesgo residual **H7**: en la ronda 1 de una fase Swiss sin partidos, dos sorteos simultáneos «en frío» podían insertar dos calendarios en la misma fase, porque no había filas que bloquear y el código del partido generado no es único. Las specs 008 y 011 mantuvieron el riesgo como aceptado y 008 dejó fuera el control de duplicados en calendarios generados y en eliminatorias. README y AGENTS siguen declarándolo abierto. El informe de funciones adicionales lo recoge como F11.

**Hallazgo previo (lectura del código, no verificado con concurrencia real):** la spec 006 añadió después el protocolo de bloqueo fase → versión a la generación y a todos los sorteos, incluida la transacción de escritura Swiss. Si ese bloqueo serializa de verdad las dos peticiones, H7 ya no se produce y lo que falta es **demostrarlo con pruebas de concurrencia reales, blindarlo en la base de datos y corregir la documentación**. Si las pruebas reproducen el duplicado, esta spec también lo corrige.

F11 cierra H7 de forma verificable y añade una comprobación de integridad del calendario generado, para que ninguna fase acabe con partidos generados duplicados ni con emparejamientos repetidos por encima de lo que permite su formato.

Relación con la constitución: §2.1–2.2 (aislamiento por organización; todo corre con RLS), §2.3 (lo publicado no cambia: una versión publicada sigue sin admitir sorteo salvo las rondas Swiss posteriores) y reglas de migraciones numeradas. No requiere enmienda.

## Usuarios

- Quien gestiona torneos en una organización (permiso de gestión de torneos).

## Roles y visibilidad

- **Público:** sin cambios; solo ve calendarios de versiones publicadas.
- **Miembro con permiso de gestión de torneos:** sortea y genera calendarios como hoy; ante un conflicto concurrente recibe un error que puede reintentar.
- **Miembro sin ese permiso:** sin cambios (403).
- **Administrador de plataforma:** sin acciones nuevas.
- Ninguna organización ve ni modifica fases o partidos de otra.

## Historias de usuario

- HU-1. Como organizador, quiero que si yo y otra persona sorteamos la misma fase a la vez solo quede un calendario, para no tener partidos duplicados.
- HU-2. Como organizador, quiero que el sistema rechace un calendario generado que repita enfrentamientos más de lo que permite el formato, para no publicar un calendario incoherente.
- HU-3. Como responsable técnico, quiero que la documentación diga con precisión qué protege contra duplicados, para no arrastrar un riesgo que ya no existe ni ocultar uno que sí.

## Definiciones

- **Sorteo o generación:** cualquier creación automática de partidos de una fase: liga, grupos, eliminación directa o doble, y cada ronda Swiss.
- **Partido generado:** partido creado por un sorteo o una generación; tiene código de partido. Los partidos creados a mano no lo tienen.
- **Sorteo en frío:** primer sorteo de una fase que todavía no tiene partidos.
- **Máximo de enfrentamientos por pareja:** el del formato persistido de la fase según R26 (spec 008): liga y grupos, uno o dos según las vueltas; Swiss, uno en toda la fase; eliminatorias, fuera de la regla.

## Requisitos funcionales

- **RF-001.** CUANDO lleguen a la vez dos o más sorteos o generaciones de la misma fase y versión, EL SISTEMA los procesará de uno en uno; al terminar, la fase tendrá como mucho un calendario generado completo y nunca partidos de dos sorteos mezclados.
- **RF-002.** CUANDO dos sorteos en frío de la misma fase coincidan sin pedir reemplazo, EL SISTEMA aplicará uno y responderá al otro 409 con el mensaje vigente de «la fase ya tiene partidos», sin escribir nada.
- **RF-003.** CUANDO dos sorteos de la misma fase coincidan pidiendo reemplazo, EL SISTEMA aplicará los dos de uno en uno, de modo que el último sustituye por completo al anterior (DA-4); ninguno deja partidos del otro. En Swiss el segundo recibe 409 de estado cambiado (aclaración de DA-4).
- **RF-004.** CUANDO dos peticiones de la misma ronda Swiss posterior a la primera coincidan, EL SISTEMA aplicará una y responderá a la otra 409 de estado cambiado, sin escribir nada.
- **RF-005.** CUANDO un sorteo coincida con el alta manual de un partido en la misma fase, EL SISTEMA los procesará de uno en uno: el alta manual posterior se valida con la regla R26 contando los partidos generados, y un sorteo sin reemplazo posterior responde 409 porque la fase ya tiene partidos.
- **RF-006.** ANTES de escribir un calendario generado, EL SISTEMA comprobará que no repite ningún código de partido en la fase y que ninguna pareja supera el máximo de enfrentamientos del formato, contando en Swiss las rondas anteriores; SI la comprobación falla, ENTONCES responderá 409 sin escribir nada (DA-3). La comprobación no muestra avisos nuevos en el Workspace.
- **RF-007.** EL SISTEMA impedirá en la base de datos que una misma fase y versión tenga dos partidos generados con el mismo código, también si una ruta futura omitiera el bloqueo (DA-1).
- **RF-008.** SI al aplicar la migración ya existen fases con partidos generados de código repetido, ENTONCES la migración se detendrá sin cambiar nada e indicará cuántas fases están afectadas y sus identificadores, para que se regeneren antes de reintentarla (DA-2).
- **RF-009.** EL SISTEMA no cambiará el comportamiento de los sorteos que no coinciden: mismos códigos, mismas respuestas, mismas validaciones y mismo resultado para la misma semilla.
- **RF-010.** EL SISTEMA aplicará todo lo anterior solo dentro de la organización activa; una petición sobre una fase de otra organización sigue respondiendo 404 y no bloquea ni escribe nada.
- **RF-011.** CUANDO F11 esté implementada, README, AGENTS y el manual dejarán de declarar H7 como riesgo aceptado y describirán la protección real: bloqueo de fase, comprobación previa a escribir y unicidad en la base de datos.

## Requisitos no funcionales

- **RNF-001.** Las pruebas de concurrencia usan PostgreSQL real con dos conexiones simultáneas (no dobles), cubren liga, grupos, eliminación directa, Swiss ronda 1 en frío, Swiss ronda posterior y sorteo frente a alta manual, y se ejecutan en la suite con base de CI.
- **RNF-002.** La espera de una petición por el bloqueo de otra no supera la duración de la transacción que la bloquea; no se añaden reintentos automáticos ni bloqueos globales por organización.
- **RNF-003.** La migración es idempotente y verificable sobre un volumen limpio y sobre uno ya migrado.

## Datos personales y privacidad

No aplica: solo intervienen fases, partidos, equipos y códigos de partido; no hay datos personales nuevos ni contenido público nuevo.

## Casos límite

- CL-1. Fase sin partidos y dos sorteos Swiss ronda 1 a la vez (el H7 original): RF-002.
- CL-2. Liga a dos vueltas: cada pareja aparece dos veces con local y visitante invertidos; no es duplicado.
- CL-3. Doble eliminación con repetición de la gran final (GF1/GF2): fuera de la regla de máximo por pareja; los códigos siguen siendo únicos.
- CL-4. Partidos manuales sin código: no cuentan para la unicidad de códigos; sí cuentan para el máximo por pareja de un alta manual (R26, sin cambios).
- CL-5. Reemplazo de una fase con partidos ya operados: sigue respondiendo 409 como hoy, también bajo concurrencia.
- CL-6. Partidos cancelados de un calendario anterior: el reemplazo los borra antes de insertar; la unicidad nunca choca con un calendario ya sustituido.
- CL-7. Versión publicada: sigue sin admitir sorteo salvo las rondas Swiss posteriores; F11 no lo cambia.

## Fuera de alcance

- Limitar enfrentamientos repetidos en eliminatorias (siguen fuera de R26).
- Cambiar los algoritmos de sorteo, los códigos de partido o las semillas.
- Detectar en el Workspace duplicados de altas manuales ya existentes (R26 ya los impide al crear).
- Un token de estado esperado para que el segundo reemplazo concurrente falle en lugar de aplicarse (alternativa descartada en DA-4).
- Formaciones por modalidad (F12) y cualquier cambio de `engine_version`.

## Criterios de finalización

- RF-001–RF-011 y RNF-001–RNF-003 verificados con pruebas: unitarias de la comprobación previa, de concurrencia con PostgreSQL real y de la migración (limpia, ya migrada, idempotente y con datos duplicados).
- README, AGENTS y manual sin H7 como riesgo aceptado y con la protección descrita.
- CI completa en verde y aceptación expresa del usuario.

## Dudas abiertas

Ninguna.
