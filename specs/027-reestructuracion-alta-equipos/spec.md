# Spec 027 — Reestructuración del alta de equipos: paso de selección de modo

Estado: borrador

## Contexto y objetivo

El asistente de equipos (spec 012, RF-003, RF-006, RF-011, RF-021) presenta hoy tres pasos visibles en su índice —`teams.details` (datos del equipo), `teams.individual` y `teams.bulk` (las dos vías alternativas de alta) y `teams.review` (revisión)—. La selección entre alta individual y carga masiva se realiza dentro de los pasos de cada vía, de modo que el índice no refleja un paso propio de decisión: el usuario llega a un paso alternativo ya sabiendo por cuál va, y los campos de nombre y código, que solo aplican a la vía individual, se declaran obligatorios en `teams.details` aunque el usuario haya elegido la carga masiva.

**Objetivo:** hacer que la **elección del modo de alta** (individual o masiva) sea un **paso propio y el primero** del asistente; retirar el paso «Carga masiva» del índice (sin botón en el índice); convertir `name` y `shortCode` en campos opcionales del modelo, validados únicamente cuando se ha elegido la vía individual; y mantener `teams.details` como paso separado posterior a la elección del modo individual. Se conservan por compatibilidad los ids de paso existentes (`teams.details`, `teams.individual`, `teams.bulk`, `teams.review`) y se añade un nuevo id al inicio (`teams.entry`).

No se altera ningún contrato del servidor, ninguna regla deportiva ni ningún permiso: el cambio se limita al asistente de equipos en el frontend y a su modelo puro.

## Usuarios

- **Administrador de organización con permiso de gestión de torneos:** configura el alta de equipos; es el usuario principal del asistente.
- **Observador (rol `viewer`):** consulta el asistente en solo lectura; los pasos y sus estados deben seguir siendo legibles.

## Roles y visibilidad

- **Público:** no aplica.
- **Miembro sin rol:** conserva el contrato vigente (**403** en toda ruta protegida). Ningún asistente nuevo le concede contexto.
- **Observador:** ve el asistente de equipos en modo lectura, con el mismo índice y los mismos estados, sin acciones de escritura (RF-038 de la spec 012).
- **Administrador y dueño:** sin cambio de permisos. Conservan el alta individual y la carga masiva.
- **Administrador de plataforma:** no aplica; `/admin` queda fuera del alcance.
- **Aislamiento:** sin cambios; el asistente reutiliza los contratos existentes, que ya filtran por organización.

## Historias de usuario

- **HU-1.** Como administrador, quiero que el primer paso del asistente me haga elegir explícitamente cómo daré de alta los equipos —uno a uno o en carga masiva—, para que el índice refleje esa decisión antes de pedirme datos.
- **HU-2.** Como administrador, quiero que, al elegir la carga masiva, el paso de datos del equipo deje de ser obligatorio y de bloquear la confirmación, para no tener que rellenar nombre y código que no usaré.
- **HU-3.** Como administrador, quiero que, al elegir alta individual, el asistente me lleve a un paso de datos separado para introducir nombre y código, para no mezclar la elección del modo con la captura de datos.
- **HU-4.** Como administrador, quiero que mis borradores anteriores sigan abriéndose sin perder lo escrito, para no tener que rehacer un alta empezada.

## Definiciones

- **Paso de selección de modo (`teams.entry`):** primer paso del asistente de equipos, **obligatorio**, en el que se elige la vía de alta: individual o carga masiva. Registra la vía elegida en el campo `entryPath`. Hasta que no se elige una vía, no se considera completo.
- **Campo `entryPath`:** campo del paso `teams.entry` que registra la vía elegida (`'individual'` o `'bulk'`). Es el único campo del paso y es obligatorio.
- **Vía de alta:** `individual` (un equipo con nombre y código) o `bulk` (carga masiva por CSV).
- **Grupo de alternativas (`TEAM_ENTRY_GROUP`):** se mantiene sobre `teams.individual` y `teams.bulk`, que siguen siendo pasos `alternative` excluyentes. `teams.entry` **no** pertenece al grupo: es un paso `required` independiente que registra la elección.
- **Regla de derivación del estado de los alternativos:** el estado de `teams.individual` y `teams.bulk` se deriva de `entryPath`: el alternativo cuya vía coincide con `entryPath` se evalúa con sus reglas propias; el otro se marca como **omitido** (no bloquea la confirmación). Si no hay vía elegida, ambos se marcan como omitidos.
- **Paso de datos del equipo (`teams.details`):** paso en el que se introducen nombre y código; solo es obligatorio y se valida cuando la vía elegida es `individual`.
- **Paso de carga masiva (`teams.bulk`):** paso en el que viven los campos de la carga masiva (CSV pegado y/o archivo seleccionado). Es el paso declarado que aloja esos campos; su estado se deriva de `entryPath` y de la validez del CSV (ver RF-001/RF-003 y la regla de derivación). Tiene `showInIndex: false` y no aparece en el índice ni ofrece botón salvo cuando es el paso actual.
- **Índice de pasos:** lista ordenada de pasos del asistente con su estado (`completo`, `incompleto`, `con error`, `omitido`, `alternativo`). El paso de carga masiva (`teams.bulk`) **sigue existiendo como paso declarado** en el modelo (por compatibilidad de `?step=` e `isWizardStep`) y es **el paso en el que se realiza la carga masiva**; **no aparece en el índice** ni ofrece botón (`showInIndex: false`). Su ausencia del índice significa solo que no es un paso independiente en el índice, no que deje de existir ni de ejecutarse: sigue siendo accesible por `?step=teams.bulk` y su estado se sigue calculando.
- **Paso de selección de modo (`teams.entry`):** tiene `showInIndex: true` y aparece en el índice como primer paso, con botón, en todos los casos. Es un paso **obligatorio**, no alternativo.
- **Visibilidad en el índice (`showInIndex`):** bandera declarativa de cada paso que indica si aparece en el índice y tiene botón. `wizardSteps()` sigue devolviendo **todos** los pasos (incluidos los no visibles) para que las direcciones, los borradores y las pruebas sigan resolviéndose; el componente `WizardSteps` filtra por esta bandera y no renderiza botón para los pasos con `showInIndex: false`. **Excepción:** si un paso con `showInIndex: false` es el paso actual del asistente, el índice lo muestra y lo anuncia como paso actual (el filtrado por `showInIndex` no oculta el paso en curso). El estado del paso no visible se sigue calculando y puede bloquear o no la confirmación según su obligación.
- **Borrador de asistente:** estado de un asistente —paso actual y valores introducidos— que vive en el almacenamiento de sesión de la pestaña (spec 012). No se envía al servidor.

## Requisitos funcionales

- **RF-001.** CUANDO un usuario abra el asistente de equipos, EL SISTEMA presentará como primer paso un paso propio de selección del modo de alta, con las dos vías (individual y carga masiva) como alternativas excluyentes, y el índice lo mostrará antes que cualquier otro paso.
  *Criterios de aceptación:*
  - El paso nuevo (`teams.entry`) es el primero en el orden de declaración del asistente de equipos.
  - El paso nuevo es **obligatorio** (`required`) y tiene un único campo obligatorio `entryPath` que registra la vía elegida; no elegir ninguna vía impide confirmar.
  - **Estado del paso `teams.entry`:** cuando `entryPath` es un valor válido (`'individual'` o `'bulk'`), el paso se clasifica como **completo**; en caso contrario (ausente, `null` o cualquier otro valor), se clasifica como **incompleto** y bloquea la confirmación.
  - **Visibilidad en el índice:** `teams.entry` tiene `showInIndex: true` y aparece en el índice con botón en todos los casos (es el primer paso).
  - **Reconciliación con la definición de «Paso alternativo» de la spec 012:** `teams.entry` es un paso **obligatorio**, no alternativo. El grupo alternativo es `TEAM_ENTRY_GROUP` sobre `teams.individual`/`teams.bulk`. `canConfirm` exige **ambas** condiciones: `teams.entry` completo **y** exactamente una vía elegida en el grupo. Esto es coherente con la spec 012 (RF-006), que exige todos los obligatorios completos y exactamente una alternativa por grupo: `teams.entry` es el obligatorio y el grupo es la alternativa. No basta con que `teams.entry` esté completo si no hay vía elegida, ni basta con elegir una vía si `teams.entry` está incompleto.
  - Las dos vías siguen siendo un grupo de alternativas excluyentes (`TEAM_ENTRY_GROUP` sobre `teams.individual` y `teams.bulk`): elegir exactamente una es condición de confirmación, además de que `teams.entry` esté completo.
  - `canConfirm` exige `teams.entry` completo **y** exactamente una vía elegida en el grupo.
  - **Fuente de verdad:** `entryPath` (campo del paso `teams.entry`) es la única fuente de verdad de la vía elegida; `TEAM_ENTRY_GROUP` (sobre `teams.individual`/`teams.bulk`) se deriva de `entryPath` y no se edita de forma independiente. El índice y el estado de los alternativos se calculan a partir de `entryPath`, nunca al revés.
  - El índice muestra el nuevo paso con su estado y su etiqueta en el idioma activo.
  - La etiqueta del paso nuevo usa la clave i18n **`wizard.teams.entry`** (es/en).

- **RF-002.** EL SISTEMA conservará por compatibilidad los ids de paso existentes (`teams.details`, `teams.individual`, `teams.bulk`, `teams.review`) y añadirá un nuevo id al inicio (`teams.entry`), de modo que las direcciones, los borradores y las pruebas que referencian los ids antiguos sigan resolviéndose.
  *Criterios de aceptación:*
  - Los ids antiguos siguen existiendo en el tipo de paso y en el orden de declaración (en sus posiciones actuales, salvo la inserción del nuevo al inicio).
  - Una dirección con `?step=teams.bulk` o cualquiera de los ids antiguos sigue abriendo el asistente sin error.
  - Un borrador guardado con un id de paso antiguo se normaliza al montar: si el id no es válido **o no se reconoce** (desconocido, de una versión futura o eliminado), se usa el primer paso. Ningún id desconocido se conserva ni genera error.

- **RF-003.** EL SISTEMA conservará `teams.bulk` en la declaración de pasos (por compatibilidad de `?step=` e `isWizardStep`) y le asignará **`showInIndex: false`** (o equivalente) para que el paso no aparezca en el índice ni ofrezca botón cuando no es el paso actual; la carga masiva se realiza en el propio paso `teams.bulk`, que existe como paso declarado y es accesible por `?step=teams.bulk`. Su ausencia del índice significa solo que no es un paso independiente en el índice, no que deje de existir ni de ejecutarse.
  *Criterios de aceptación:*
  - `teams.bulk` **sigue existiendo** en el tipo `TeamsStepId` y en el orden de declaración (en su posición actual), de modo que `?step=teams.bulk` e `isWizardStep` sigan resolviéndolo.
  - `wizardSteps()` sigue devolviendo **todos** los pasos, incluido `teams.bulk`, con su estado calculado.
  - El componente `WizardSteps` filtra por `showInIndex` y **no renderiza** botón ni entrada para `teams.bulk` **salvo cuando `teams.bulk` es el paso actual**, en cuyo caso lo muestra y lo anuncia como paso actual.
  - El paso `teams.bulk` no aparece en el índice del asistente cuando no es el paso actual.
  - No hay botón en el índice que enlace a `teams.bulk` cuando no es el paso actual.
  - Si `teams.bulk` es el paso actual, el índice lo muestra y lo anuncia como paso actual aunque `showInIndex` sea false.
  - Los campos de carga masiva (CSV, archivo) viven y siguen estando disponibles en el paso **`teams.bulk`** cuando la vía elegida es `bulk`.
  - La carga masiva sigue validándose con las reglas existentes (filas, columnas, topes) cuando la vía elegida es `bulk`.
  - **Estado del paso `teams.bulk`** (deriva de `entryPath` y de la validez del CSV):
    - Si `entryPath === 'bulk'`: **completo** si el CSV/archivo es válido (columnas, filas y topes cumplidos); **con error** si hay errores de validación; **incompleto** si no hay CSV/archivo cargado.
    - Si `entryPath !== 'bulk'` (incluido sin vía elegida): **alternativo** (no elegido; no bloquea la confirmación).
    - En todos los casos, `showInIndex` permanece `false` salvo cuando `teams.bulk` es el paso actual, en cuyo caso se muestra y se anuncia como paso actual.

- **RF-004.** EL SISTEMA hará que los campos `name` y `shortCode` sean opcionales en el modelo de pasos, validándose únicamente cuando la vía elegida sea `individual`.
  *Criterios de aceptación:*
  - En la declaración del paso `teams.details`, los campos `name` y `shortCode` pasan de obligatorios a opcionales.
  - Cuando la vía elegida es `bulk`, la ausencia de nombre y código no marca `teams.details` como incompleto ni bloquea la confirmación.
  - Cuando la vía elegida es `individual`, la ausencia de nombre o código marca `teams.details` como incompleto y bloquea la confirmación, igual que hoy.
  - La validación de formato (longitud, patrón) sigue aplicándose cuando se introduce un valor, con independencia de la vía elegida.
  - **Errores de formato en vía masiva no bloquean:** si `entryPath !== 'individual'` y `teams.details` tiene errores de formato en `name`/`shortCode`, esos errores se **reportan** en el paso (estado `error` del paso, mensaje junto al campo) pero **no cuentan** en `canConfirm` para esa vía: la confirmación queda disponible con CSV válido. El paso `teams.details` no bloquea la confirmación en vía masiva aunque tenga errores de formato.
  - **Clasificación del estado de `teams.details` en vía masiva:** cuando `entryPath !== 'individual'`, el estado del paso `teams.details` se clasifica explícitamente a partir del estado de cada campo (`vacío` / `válido` / `inválido` por formato), en este orden de precedencia:
    - **con error** si al menos uno de los dos campos está relleno pero tiene error de formato (incluido el caso de un campo válido y el otro inválido);
    - **omitido** si `name` y `shortCode` están ambos vacíos y ninguno tiene error de formato;
    - **completo** si ambos campos están rellenos y válidos;
    - **incompleto** si exactamente uno de los dos campos está relleno y válido y el otro está vacío, sin errores de formato.
    En todos los casos el paso no bloquea la confirmación en vía masiva (no cuenta en `canConfirm` para esa vía).
  - **Conservación sin envío:** en vía masiva, los valores de `name`/`shortCode` introducidos en `teams.details` se **conservan** en el borrador (como hoy, RF-004 de la spec 012), pero **no se envían al servidor** al confirmar: el alta masiva no usa esos campos.

- **RF-005.** CUANDO la vía elegida sea la individual, EL SISTEMA mantendrá `teams.details` como paso separado posterior al paso de selección de modo, en el que se introducen nombre y código, y `teams.individual` como paso alternativo de esa vía.
  *Criterios de aceptación:*
  - El orden de pasos es: selección de modo (`teams.entry`), datos del equipo (`teams.details`), vías alternativas (`teams.individual`/`teams.bulk`), revisión (`teams.review`).
  - **Contenido de `teams.individual`:** es el paso alternativo de la vía individual; no captura datos nuevos (los datos vienen de `teams.details`), sino que confirma que la vía individual es la elegida y lista el equipo a registrar (nombre y código) a partir de los valores de `teams.details`. Su estado es `completo` cuando `entryPath === 'individual'` y `name`/`shortCode` son válidos, y `alternativo` en caso contrario.
  - **Flujo de avance en vía individual:** `teams.entry` → `teams.details` → `teams.individual` (que queda completo automáticamente al tener datos válidos) → `teams.review`. Si `teams.details` no es válido, el avance se detiene en `teams.details`. Un paso ya completo puede saltarse (avance directo a `teams.review`).
  - **Flujo de avance en vía masiva:** `teams.entry` → `teams.bulk` → `teams.review`, omitiendo `teams.details` y `teams.individual` (ambos `omitido`/`alternativo`).
  - El selector de vía se **reubica** en `teams.entry`: es el único lugar donde se elige la vía. No se repite en `teams.details` ni en `teams.bulk`.
  - En `teams.details` y `teams.bulk` no se repite el selector; solo se muestra un aviso si la vía elegida no coincide con el paso («como hoy»).
  - El paso de datos del equipo solo muestra sus campos cuando la vía elegida es `individual`; en caso contrario, muestra el aviso de que se eligió la otra vía, como hoy.
  - **Estado de `teams.details` en vía masiva:** cuando `entryPath !== 'individual'`, `teams.details` no es obligatorio y su estado se clasifica según RF-004 (puede ser `completo` si ambos campos están rellenos y válidos, `con error`, `omitido` o `incompleto`); en ningún caso bloquea la confirmación. El estado real posible incluye `completo`, por lo que el índice puede mostrarlo así aunque la vía sea masiva.
  - **Cambio de vía desde un paso de vía:** desde `teams.details`, `teams.individual` o `teams.bulk` el usuario puede volver a `teams.entry` (mediante el índice o el botón atrás) para cambiar la vía; los valores de la vía anterior se conservan (RF-006) pero dejan de bloquear la confirmación.

- **RF-006.** EL SISTEMA conservará en el borrador de la pestaña el paso actual y los valores introducidos, incluidos los de la vía no elegida, de modo que un borrador anterior siga restaurándose sin pérdida.
  *Criterios de aceptación:*
  - Un borrador guardado antes de este cambio (con paso `teams.details`, `teams.individual`, `teams.bulk` o `teams.review`) se restaura al montar: si su paso ya no es válido o no existe, se usa el primer paso.
  - **Normalización de borradores legacy:** si un borrador no tiene `entryPath` válido (ausente, `null`, o un valor distinto de `'individual'`/`'bulk'`), se infiere la vía a partir de los datos presentes:
    - **valores aceptados de `entryPath`:** solo `'individual'` y `'bulk'`; cualquier otro valor se trata como ausente y se infiere.
    - **señal individual:** existe `name` y/o `shortCode` con contenido no vacío (tras `trim`), sin importar su validez de formato.
    - **señal de carga masiva («datos de carga masiva»):** existe `bulkCsv` con contenido no vacío (tras `trim`) **o** `bulkFileName` con contenido no vacío.
    - si hay señal individual y **no** hay señal de carga masiva → `entryPath = 'individual'`;
    - si hay señal de carga masiva y **no** hay señal individual → `entryPath = 'bulk'`;
    - si ambas señales están presentes o ninguna → `entryPath = 'individual'`.
    En todos los casos los valores se conservan (incluidos los inválidos). Un `entryPath` inválido se descarta antes de inferir (no genera error).
  - Los valores del borrador (nombre, código, vía elegida, CSV, archivo) se restauran tal cual.
  - **Normalización de `entryPath` y paso actual:** la inferencia de `entryPath` en borradores legacy **no reescribe el paso actual** del borrador si ese paso es válido (existe y es reconocido por la versión actual); solo se normaliza `entryPath`. Si el paso actual es inválido o no se reconoce, se usa el primer paso, como ya establece RF-002. Los valores se conservan en ambos casos.
  - El borrador no contiene datos personales ni se envía al servidor.
  - Al recargar la página con el asistente abierto, se vuelve al mismo paso con los mismos datos.

- **RF-007.** EL SISTEMA mantendrá el comportamiento de confirmación: la confirmación exige que la vía elegida esté completa, que no haya errores **en la vía elegida** (y en `teams.details` únicamente cuando la vía es individual) y que, si la vía es individual, los datos del equipo estén completos y válidos. Los errores de formato de `teams.details` en vía masiva no cuentan para la confirmación.
  *Criterios de aceptación:*
  - Con vía `individual` y datos válidos, la confirmación está disponible.
  - Con vía `bulk` y CSV válido, la confirmación está disponible aunque `teams.details` esté vacío.
  - Sin vía elegida, la confirmación está bloqueada y el primer bloqueo reportado es el paso de selección de modo.
  - Con vía `individual` y datos inválidos, la confirmación está bloqueada y se reporta `teams.details`.

## Requisitos no funcionales

- **RNF-001.** El cambio no modifica ningún contrato del servidor, ninguna migración ni ningún endpoint. No se añaden dependencias nuevas.
- **RNF-002.** El modelo puro (`teamsWizard.ts`, `wizardModel.ts`) sigue sin leer el reloj, el entorno, el almacenamiento ni la red; la validación sigue siendo determinista y sin efectos secundarios.
- **RNF-003.** Los tests existentes de modelo (`wizard-model.test.ts`, `stage-teams.test.ts`, los tests de `teamsWizard`) se actualizan para reflejar el nuevo orden y la nueva obligación de los campos, sin debilitar las aserciones: no se eliminan casos, se adaptan al nuevo contrato.
- **RNF-004.** La accesibilidad del índice se conserva: el paso nuevo se anuncia a lector de pantalla con su estado, y la navegación con teclado sigue funcionando.
- **RNF-005.** La compatibilidad con borradores antiguos se verifica con un caso de prueba que restaure un borrador con paso `teams.bulk` y otro con paso `teams.details`.

## Datos personales y privacidad

No aplica: el cambio no toca datos personales, proyecciones públicas ni almacenamiento de identidad.

## Casos límite

- Un borrador guardado con `step: 'teams.bulk'` antes del cambio: al montar, si `teams.bulk` sigue siendo un id válido, se conserva; si no, se usa el primer paso. Los valores se restauran.
- Un borrador guardado con un id de paso que la versión actual no reconoce (incluido `teams.entry` en una versión anterior que no lo conocía, o cualquier id futuro o eliminado): se normaliza al primer paso disponible, sin error y sin conservar el id desconocido.
- Un borrador legacy sin `entryPath`: al montar se infiere la vía (`individual` si hay `name`/`shortCode`, `bulk` si hay datos de carga masiva; si ambas o ninguna, `individual`); los valores se conservan.
- En vía masiva, `teams.details` con errores de formato en `name`/`shortCode`: los errores se reportan pero no bloquean la confirmación (no cuentan en `canConfirm` para esa vía).
- El usuario elige `individual`, rellena nombre y código, y luego cambia a `bulk`: los valores individuales se conservan (como hoy) y `teams.details` deja de bloquear la confirmación.
- El usuario elige `bulk`, pega un CSV inválido y cambia a `individual`: el CSV se conserva y la validación de la vía bulk deja de aplicarse; la confirmación queda bloqueada hasta que se rellenen nombre y código.
- El usuario no elige ninguna vía: la confirmación está bloqueada y el primer bloqueo es el paso de selección de modo.
- Una versión no editable o un usuario sin permiso de gestión: el asistente se muestra en solo lectura, con el mismo índice y los mismos estados, sin acciones de escritura (RF-038 de la spec 012).
- Una dirección antigua con `?step=teams.review` sigue abriendo el asistente en ese paso.

## Fuera de alcance

- Cambios en el backend, en migraciones o en contratos del servidor.
- Cambios en el asistente de fases o en el de reglas.
- Cambios en la carga masiva (parseo, validación, topes, mensajes) más allá de su reubicación en el índice.
- Cambios en la persistencia del borrador (sigue en sessionStorage de la pestaña).
- Nuevas traducciones más allá de la etiqueta del paso nuevo y los mensajes existentes.

## Tests afectados

- **`frontend/tests/wizard-model.test.ts` (líneas 96–302):** el barrido de estados de pasos, `canConfirm` y navegación (`firstStepId`, `nextStepId`, `previousStepId`) debe adaptarse al nuevo orden con `teams.entry` al inicio y a `teams.bulk` con `showInIndex: false`. Los casos de `blockedBy` que hoy esperan `['teams.individual', 'teams.bulk']` pasan a incluir también `teams.entry` cuando no hay vía elegida. Los casos de `firstStepId('teams')` pasan de `teams.details` a `teams.entry`, y `nextStepId`/`previousStepId` se renumeran.
- **`frontend/tests/stage-teams.test.ts`:** los casos de `showsEntryPathStep` y de estados por vía se mantienen; se añaden casos para `teams.entry` como paso `required` con `entryPath`.
- **Casos nuevos obligatorios:**
  - `teams.bulk` sigue declarado y `wizardSteps()` lo devuelve, pero con `showInIndex: false`; `WizardSteps` no lo renderiza.
  - En vía masiva, errores de formato en `teams.details` se reportan pero no bloquean `canConfirm`.
  - Normalización de borrador legacy: se infiere `entryPath` (`individual`/`bulk`) a partir de los datos presentes; si ambas señales o ninguna, `individual`.
  - Flujo de avance: individual → `teams.details`; bulk → `teams.bulk`.

## Criterios de finalización

- El asistente de equipos muestra `teams.entry` como primer paso en el índice, con las dos vías como alternativas excluyentes.
- `teams.bulk` no aparece en el índice ni tiene botón.
- `name` y `shortCode` son opcionales en el modelo; la validación se aplica solo con vía `individual`.
- `teams.details` es un paso separado posterior a la elección del modo individual.
- Los ids antiguos se conservan y los borradores antiguos se normalizan al montar.
- `cd frontend && pnpm test` pasa, incluidos los tests de modelo y de `teamsWizard`.
- `cd frontend && pnpm run typecheck` pasa.
- `cd frontend && pnpm run typecheck:e2e` pasa si se tocan utilidades compartidas por el arnés E2E.
- No se introduce ningún cambio de contrato del servidor ni migración.

## Dudas abiertas

Todas las dudas registradas quedan resueltas por la implementación actual del frontend; no quedan puntos abiertos.

- Resuelto — Terminología: la vía no elegida se marca como `alternativo`; `omitido` se reserva a `teams.details` vacío en vía masiva. Implementado en `frontend/app/utils/wizardModel.ts` (`stepState`) y en `teamWizardStatuses` de `frontend/app/utils/teamsWizard.ts`.
- Resuelto — Estado de `teams.details` en vía masiva: clasificación completa (completo/error/omitido/incompleto) implementada en `teamWizardStatuses` (`frontend/app/utils/teamsWizard.ts`). `teams.bulk` con `showInIndex: false` se muestra en el índice solo cuando es el paso actual (componente `WizardSteps`).
- Resuelto — Navegación: `firstStepId`, `nextStepId` y `previousStepId` operan sobre todos los pasos declarados, incluidos los de `showInIndex: false`, por lo que `teams.bulk` es alcanzable por navegación. Implementado en `frontend/app/utils/wizardModel.ts` (operan sobre `declarations(wizard)`).
- Resuelto — `teams.individual` es un paso informativo que lista el equipo a registrar a partir de `teams.details`, sin campos editables propios. Implementado en `frontend/app/utils/teamsWizard.ts` (`reviewTeams`/`teamWizardValues`) y en la página `frontend/app/pages/workspace/tournaments/[id]/teams.vue`.
- Resuelto — «Sin errores» en RF-007: `teamConfirmation` (`frontend/app/utils/teamsWizard.ts`) filtra `teams.details` de `blockedBy` cuando la vía no es individual, de modo que no bloquea la confirmación en vía masiva.
- Resuelto — Normalización legacy: `inferTeamEntryPath` (`frontend/app/utils/teamsWizard.ts`, T005) infiere `individual` si hay `name`/`shortCode`, `bulk` si hay CSV/archivo, con prioridad a `individual` cuando ambas o ninguna señal están presentes. `restoreTeamValues` conserva el paso actual válido sin reubicar al usuario.
- Resuelto — Condición de confirmación: `teams.entry` es `required` y el grupo `TEAM_ENTRY_GROUP` exige exactamente una vía elegida; `canConfirm` exige ambas condiciones. Implementado en `frontend/app/utils/wizardModel.ts` y `teamConfirmation` (`frontend/app/utils/teamsWizard.ts`).
- Resuelto — Revisión en vía masiva: `reviewTeams` (`frontend/app/utils/teamsWizard.ts`) genera el resumen con `count` y la lista de equipos (`teams`, filas del CSV parseado) tanto para la vía individual como para la masiva.
