# Spec 002 — Cifrado de la fecha de nacimiento de jugadores

Estado: implementada (2026-10-19); T001-T010 hechas, validada funcionalmente por el reviewer con sus correcciones aplicadas y cerrada con la aprobación explícita del usuario

## Contexto y objetivo

La auditoría técnica integral del 2026-10-19 registra el hallazgo **R05 (MEDIO)**: la fecha de nacimiento de los jugadores se almacena en claro y el rol de aplicación puede leerla. El número de documento ya se cifra con `PLAYER_DATA_KEY` y se guarda como `national_id_encrypted`, fuera del alcance de lectura de la aplicación (patrón *write-only*), con un HMAC para deduplicación.

Esto incumple la constitución §3.4: «Los datos personales de jugadores se almacenan protegidos con `PLAYER_DATA_KEY` y nunca se incluyen en logs ni en proyecciones públicas». Las vistas públicas ya no exponen la fecha: exponen `public_age`. Pero el dato en reposo sigue en claro.

La spec 001 dejó los jugadores como tabla propiedad de la organización, con RLS forzado, unicidad por organización y claves foráneas compuestas; la migración más reciente es la 016. El cifrado debe convivir con ese aislamiento y no reabrirlo.

**Objetivo:** que la fecha de nacimiento se almacene exclusivamente cifrada con `PLAYER_DATA_KEY`, que el texto cifrado no sea legible por la aplicación, que no quede ninguna copia de la fecha completa en claro en la base de datos, y que la proyección pública y los flujos de alta, importación, Workspace, seed y consulta sigan funcionando sin exponer la fecha.

## Decisiones cerradas

1. **Workspace sin fecha de nacimiento, con edad solo en el listado.** La API no devuelve la fecha ni ofrece ninguna vía de descifrado. **Solo `GET /tournaments/{id}/rosters` incluye `age`** (edad materializada ajustada al torneo); las respuestas de alta e importación **no cambian**. La UI muestra `age` donde antes mostraría la fecha, con etiqueta i18n en español e inglés, y refresca la lista tras crear o importar. Es un cambio aditivo de contrato y el plan no puede alterarlo por su cuenta.
2. **Edad materializada en el jugador.** Al crear o importar un jugador se calcula y guarda su edad con la fecha enviada y el año de referencia usado. Todos sus rosters reutilizan esa edad aplicando el delta de años del torneo. Si un alta posterior envía otra fecha para un jugador ya existente en la misma organización, **se ignora**: prevalece la almacenada, porque la aplicación no puede descifrar ni comparar.
3. **Fechas obligatorias y válidas.** La fecha es obligatoria en alta e importación. El rango admitido es el del tipo fecha; se rechaza el futuro y la fecha posterior a la creación del jugador. La 017, la 018 y el alta/importación son transaccionales y no dejan datos a medias; el backfill por lotes es parcial por diseño y reanudable.
4. **Backfill en dos fases.** La migración **017** habilita el esquema intermedio y **revoca a la aplicación el `SELECT` y el `INSERT` de la fecha en claro**: entre la 017 y la 018 la fecha completa ya no es legible ni escribible por el rol de aplicación. El comando **`python -m scripts.encrypt_birth_dates`** cifra los datos históricos de forma idempotente y por lotes usando la conexión administrativa; la migración **018** elimina la fecha en claro y falla si queda algún pendiente. El despliegue se secuencia con `MIGRATION_TARGET` y una ventana de mantenimiento que detiene la aplicación antigua antes de la 017.
5. **Rotación de clave fuera de alcance.** La rotación de `PLAYER_DATA_KEY`, la re-encriptación masiva y la revisión de copias de seguridad o snapshots con la fecha en claro quedan como deuda separada.

## Trazabilidad de las correcciones del QA

| QA | Corrección aplicada | Dónde queda |
|---|---|---|
| 1 | Edad materializada en el jugador; alta posterior con otra fecha se ignora; prueba del caso | Decisión 2; RF-007; RF-011 |
| 2 | Servicio one-off con conexión administrativa y clave, `--no-deps`, orden real con la imagen nueva antes del backfill | RF-006; Verificación esperada |
| 3 | Verificación previa contra el documento cifrado y contraste de HMAC; se retira la detección por round-trip propio | RF-004; RF-011 |
| 4 | Permiso de inserción de los campos nuevos y prueba de alta de extremo a extremo; se corrige la afirmación sobre el `NOT NULL` | RF-003; RF-007; RF-011 |
| 5 | Saneo del cuerpo 422 y de los errores de PostgreSQL con valores | RF-012; RF-011 |
| 6 | Validación de fechas imposibles/futuras, incluidos jugadores sin roster, y su prueba | RF-010; RF-011 |
| 7 | Criterio único y completo de verificación del backfill | RF-004 |
| 8 | La edad pública conserva el tipo entero y el contrato de columnas | RF-008; RF-011 |
| 9 | Exposición real de las columnas derivadas declarada y probada | RF-002; RF-011 |
| 10 | Idempotencia acotada al estado intermedio; tras la 018, 017 falla por diseño | RF-003; RF-005; Casos 24-25 |
| 11 | «Sin datos a medias» aplica a 017/018 y alta/importación; el backfill es parcial y reanudable | RF-004; RF-005; RNF-002 |
| 12 | `MIGRATION_TARGET` valida los checksums de todos los archivos y solo omite la aplicación posterior | RF-006; RF-011 |
| 13 | Lote de 500, volumen esperado declarado y verificación completa de lo procesado | RF-004; RNF-003 |
| 14 | Rango admitido: el tipo fecha, sin límite inferior artificial; futuro rechazado | RF-010; Definiciones |
| 15 | Detalle de implementación trasladado al plan; la spec conserva requisitos, criterios, migraciones y comando | Módulos y áreas afectadas; redacción de los RF |
| 16 | Decisión 1 alineada: Workspace muestra `age` y no la fecha | Decisión 1; RF-009 |
| 17 | Solo variable de entorno `MIGRATION_TARGET`; no existe `--target` | RF-006; Definiciones |
| 18 | RF-002 habla de la fecha completa (día y mes) como lo no legible | RF-002 |
| 19 | Rama alcanzable del backfill posterior a la 018 | RF-004; Caso 9 |
| 20 | Premisa corregida: el pendiente es el campo cifrado, no una fecha nula | RF-004; RF-010; Casos 3 y 17 |
| 21 | Base constitucional explícita sin excepción §5.1 | «Base constitucional de la edad derivada» |

## Trazabilidad de la segunda QA

| QA | Corrección aplicada | Dónde queda |
|---|---|---|
| 1 | Contraste de HMAC **siempre** contra el documento cifrado; si no puede hacerse, aborta | RF-004; RF-011 |
| 2 | Mecanismo concreto: `DATABASE_ADMIN_URL` y `PLAYER_DATA_KEY` en el servicio one-off con `--no-deps`; `MIGRATION_TARGET` en el entorno del servicio de migraciones | RF-006; Verificación esperada |
| 3 | Prueba explícita de jugador histórico **sin roster** con fecha futura rechazado por 017/backfill | RF-010; RF-011; Caso 17 |
| 4 | «Sin datos a medias» aplica a 017/018 (transaccionales) y alta/importación, no al backfill | RF-004; RF-005; RNF-002 |
| 5 | Referencia histórica por `registered_at` (desempate por id) y año UTC de `created_at` para jugadores sin roster | Definiciones; RF-003 |
| 6 | Fecha posterior a la creación del jugador declarada imposible y rechazada | Definiciones; RF-010; RF-011 |
| 7 | Rama sin documento cifrado solo con tabla vacía; no-op, sin confirmación | RF-004; Caso 6 |
| 8 | Etiqueta i18n de `age` (es/en) y refresco de la lista tras alta/importación | RF-009; Alcance; Verificación esperada |

## Ronda de validación de la spec (2026-10-19)

La validación de la spec devolvió **cambios necesarios**; el implementador los aplicó y la validación funcional quedó aprobada, sin cambios en los requisitos. Correcciones de esta ronda: el seed **falla cerrado** ante una fecha imposible sin ejecutar ninguna escritura; se añadieron las **cuatro pruebas exigidas por RF-011** (29 de febrero, seed imposible, delta de `public_age` y paridad completa de claves i18n); la 018 detecta también los **índices** dependientes de la fecha; la vista pública se verifica **sin descifrado ni subconsultas**; se comprueba la **edad ajustada del jugador reutilizado** en cada torneo y que su valor almacenado no cambia; y se retiró la **rama de confirmación no aprobada** del backfill (con filas y sin documento cifrado, aborta). La spec no se marca como implementada del todo hasta el cierre y la aprobación final del usuario.

## Alcance

- Cifrado en reposo de la fecha de nacimiento de todos los jugadores existentes y futuros, en dos migraciones (017 y 018) y un comando de backfill; la 017 revoca a la aplicación la lectura y la escritura de la fecha en claro.
- Eliminación de la fecha completa en claro del esquema y de cualquier índice, vista o exposición que la revele.
- Edad materializada a nivel de jugador y ajustada por torneo, sin descifrar en lectura ni en la proyección pública.
- `age` **solo** en la respuesta de `GET /tournaments/{id}/rosters` y el cambio mínimo de UI: etiqueta i18n en español e inglés y refresco de la lista tras alta o importación. Las respuestas de alta e importación no cambian.
- Adaptación del alta individual, la importación CSV/TXT con ZIP opcional y el seed de desarrollo.
- Secuenciación reproducible del despliegue con `MIGRATION_TARGET` y un runbook de dos fases.
- Pruebas de base de datos en CI que detecten regresiones de exposición, permisos, aislamiento, migración, edad y saneo de errores.

## Fuera de alcance

- Cifrado de otros campos (nombre, apellidos, dorsal, foto) o cambios en la política de fotos y consentimiento.
- **Rotación de `PLAYER_DATA_KEY`**, re-encriptación masiva por cambio de clave y tratamiento de copias de seguridad o snapshots con la fecha en claro. Deuda separada.
- Cambios en el cifrado, HMAC o deduplicación del número de documento.
- Nuevas rutas de descifrado o cualquier vía para que la organización recupere la fecha completa.
- Reglas deportivas de elegibilidad por edad más allá de mostrar la edad.
- Corrección o normalización de fechas históricas: las imposibles se reportan y bloquean; no se corrigen automáticamente.
- Cambios de RLS, de claves foráneas o del modelo multi-tenant de la spec 001.
- Edición de migraciones ya aplicadas (001-016).

## Usuarios

- **Administrador u operador de una organización:** registra e importa plantillas con fecha de nacimiento, consulta rosters y ahora ve la edad en el Workspace.
- **Visitante público:** consulta torneos publicados y sigue viendo la edad derivada, nunca la fecha ni datos de otra organización.
- **Administrador de plataforma:** no obtiene acceso a la fecha ni al texto cifrado por ninguna vía.
- **Responsable de privacidad o cumplimiento:** necesita que la fecha completa esté cifrada en reposo y que no aparezca en logs, errores ni proyecciones.
- **Operador de base de datos o despliegue:** ejecuta 017, el backfill y 018 en orden, con la clave verificada y sin exponerla.
- **Desarrollador o revisor:** necesita pruebas que fallen si la fecha reaparece en claro, si se concede acceso indebido o si cambia el contrato público.

## Roles y visibilidad

- **Público:** ve únicamente la edad derivada. Nunca la fecha, el texto cifrado ni la clave.
- **Miembro de organización:** ve la edad en el listado de rosters del Workspace (`GET /tournaments/{id}/rosters`) y en la UI; nunca la fecha completa.
- **Administrador de organización:** puede registrar e importar la fecha, pero no puede leerla después ni descifrarla, y no accede a datos de otra organización.
- **Administrador de plataforma:** sin acceso a la fecha ni al texto cifrado.
- **Operador de base de datos:** ejecuta migraciones y backfill sin dejar la clave ni la fecha en logs, historial de shell ni archivos versionados.

## Historias de usuario

- **HU-1.** Como responsable de privacidad, quiero que la fecha completa esté cifrada en reposo, para que una lectura directa de la base de datos no revele día ni mes de nacimiento.
- **HU-2.** Como administrador de organización, quiero seguir registrando e importando jugadores con fecha sin cambiar mi flujo y ver su edad en el Workspace.
- **HU-3.** Como visitante público, quiero seguir viendo la edad de los jugadores sin que el sistema revele su fecha.
- **HU-4.** Como operador de base de datos, quiero una migración en dos fases con un backfill verificable, idempotente y reintentable, para cifrar los datos históricos sin pérdida ni clave equivocada.
- **HU-5.** Como desarrollador o revisor, quiero pruebas automáticas que fallen si la fecha reaparece en claro, si se filtra en un error de validación o si cambia el contrato público.

## Definiciones

- **Fecha completa en claro:** día, mes y año legibles en cualquier columna, índice, vista materializada, tabla temporal persistente o proyección. Es lo que esta spec elimina.
- **Texto cifrado (*write-only*):** dato que la aplicación puede insertar pero no leer.
- **Edad del jugador:** edad calculada al crear o importar el jugador con la fecha enviada y el año de referencia usado. Es un dato derivado y público por diseño, no la fecha completa.
- **Año de referencia:** año usado al calcular la edad del jugador. Para altas e importaciones, el año de inicio del torneo en cuyo contexto se crea. Para filas históricas, el del torneo del roster más antiguo, determinado por `rosters.registered_at` ascendente y, en caso de empate, por el identificador del roster; el año se extrae de `tournaments.start_date`, que es una fecha sin zona horaria. Si el jugador no tiene roster, se usa el año de `players.created_at` en UTC.
- **Edad ajustada al torneo:** `edad del jugador + (año de inicio del torneo − año de referencia)`. Equivale a `año del torneo − año de nacimiento`.
- **Estado intermedio:** periodo entre la 017 y la 018. La aplicación no puede leer ni insertar la fecha en claro; la app nueva escribe solo el campo cifrado y la antigua está detenida.
- **Backfill:** proceso que cifra las filas históricas pendientes y verifica que descifran a su valor original antes de la migración 018.
- **Comando de backfill:** `python -m scripts.encrypt_birth_dates`, ejecutado como servicio one-off con `DATABASE_ADMIN_URL` y `PLAYER_DATA_KEY`.
- **`MIGRATION_TARGET`:** variable de entorno del servicio de migraciones que limita la aplicación hasta una versión concreta. No existe una bandera `--target`; el mecanismo es solo la variable.
- **Ventana de mantenimiento:** periodo en el que `api` y `worker` están detenidos y no se aceptan escrituras; se inicia antes de la 017 para que ninguna instancia antigua intente escribir la fecha.
- **Volumen limpio / migrado:** base creada desde cero con inicialización y migraciones / base existente que ya aplicó hasta la 016.
- **Fecha imposible:** fecha no representable por el tipo fecha, posterior a la fecha actual o posterior a la fecha de creación del jugador (en UTC). El rango admitido es el del propio tipo fecha; el futuro y la fecha posterior a la creación se rechazan siempre.

## Requisitos funcionales

### RF-001 — Cifrado en reposo y ausencia de la fecha completa en claro

CUANDO se registra, importa o migra un jugador con fecha de nacimiento, EL SISTEMA almacena esa fecha exclusivamente cifrada con `PLAYER_DATA_KEY` y no deja ninguna copia de la fecha completa en claro en la base de datos.

*Criterios de aceptación:*
- Tras la migración 018 no existe ninguna columna de fecha de nacimiento en claro en el esquema, ni en tablas, índices, vistas o proyecciones.
- Cada fila con fecha descifra con la `PLAYER_DATA_KEY` correcta exactamente al valor original (incluidos años bisiestos y el 29 de febrero).
- Ninguna consulta del esquema devuelve día ni mes de nacimiento.
- La migración conserva el número de filas de jugadores, rosters, alineaciones, eventos y suspensiones y no deja referencias huérfanas.
- El cifrado no altera la deduplicación por HMAC ni la unicidad por organización de la spec 001.
- No se añade una columna de año de nacimiento ni se expone la fecha completa por ningún camino.

### RF-002 — Acceso *write-only* a la fecha, aislamiento y exposición real de la edad

EL SISTEMA mantiene el texto cifrado fuera del alcance de lectura de la aplicación, conserva el aislamiento por organización y hace explícita la exposición de la edad derivada.

*Criterios de aceptación:*
- La aplicación puede insertar los campos nuevos que el alta, la importación y el seed necesitan, y no puede leer el texto cifrado.
- La aplicación no tiene `UPDATE` ni `DELETE` sobre la fila del jugador, como hoy.
- La tabla mantiene RLS habilitado y forzado; sin contexto de organización no devuelve filas y una organización no puede leer ni modificar datos de otra.
- La API nunca devuelve el texto cifrado en una respuesta, error o traza.
- **Exposición real declarada:** las columnas derivadas de edad y año de referencia sí son legibles por la aplicación y, junto con el año del torneo, permiten reconstruir el año de nacimiento, igual que la proyección pública actual. Esta spec no afirma lo contrario. Lo que nunca es legible es la fecha completa (día y mes) ni el texto cifrado.
- Existe una prueba que confirma que el texto cifrado no es seleccionable por el rol de aplicación y que las columnas derivadas sí lo son, con la exposición anterior documentada.
- No se crea ninguna ruta, función ni pantalla de descifrado.

### RF-003 — Migración 017: esquema intermedio operativo

CUANDO se aplica la migración 017 sobre un volumen limpio o sobre uno ya migrado hasta la 016, EL SISTEMA habilita un esquema intermedio en el que la aplicación nueva opera sin la fecha en claro, y materializa la edad de los jugadores históricos.

*Criterios de aceptación:*
- La migración es la **017** y no edita ninguna migración aplicada.
- Agrega el campo cifrado de fecha, todavía nullable, y deja la fecha en claro existente en un estado que permite insertar jugadores y rosters sin ella, para que la imagen nueva funcione durante la transición.
- **Revoca a `bracket_app` el `SELECT` y el `INSERT` de la fecha en claro.** En el estado intermedio, la aplicación no puede leer ni escribir la fecha completa; la app antigua se detiene antes de la 017 y la nueva escribe solo el campo cifrado. Existe una prueba específica de que el rol de aplicación no puede leerla en ese estado.
- Agrega la edad del jugador y el año de referencia, los rellena para todos los jugadores existentes y los deja obligatorios. Para filas históricas, el año de referencia es el del torneo del roster más antiguo, determinado por `rosters.registered_at` ascendente y, en caso de empate, por el identificador del roster; el año se extrae de `tournaments.start_date` (fecha sin zona horaria). Si el jugador no tiene roster, se usa el año de `players.created_at` en UTC.
- La aplicación puede insertar el campo cifrado y las columnas derivadas en el mismo camino que ya usa para el alta, la importación y el seed; sin ese permiso, esas operaciones fallan con «permission denied». La migración concede lo necesario y una prueba de alta de extremo a extremo lo verifica.
- La proyección pública conserva el mismo conjunto, orden y tipo de columnas, incluida la edad pública como entero; la recreación no puede cambiar tipos ni romper el contrato.
- Sobre una base en 016 con jugadores históricos, la edad del jugador reproduce la fórmula actual para el torneo de referencia.
- Sobre un volumen limpio, la migración se aplica sin errores.
- La migración es idempotente **en el estado intermedio**: reejecutarla antes de la 018 no duplica ni falla por objetos existentes. Después de la 018 la fecha en claro ya no existe y reejecutar 017 falla por diseño; el requisito no cubre ese caso.
- Los checksums se respetan.

### RF-004 — Comando de backfill `encrypt_birth_dates`

CUANDO se ejecuta `python -m scripts.encrypt_birth_dates` entre la 017 y la 018, EL SISTEMA verifica la clave, cifra por lotes las filas históricas pendientes y permite reintentar sin corromper datos.

*Criterios de aceptación:*
- **Verificación previa de la clave:** antes de escribir nada, el comando descifra al menos una fila con documento cifrado usando la clave configurada y **contrasta siempre** el HMAC almacenado. El HMAC del documento es obligatorio, así que el contraste es viable para cualquier fila con documento. Si el descifrado falla o el HMAC no coincide, aborta sin escribir y con un mensaje claro; no hay una variante «cuando sea posible».
- La rama sin filas con documento cifrado **solo es alcanzable con la tabla de jugadores vacía**, porque el documento es obligatorio. En ese caso no hay nada que verificar ni cifrar y el comando termina con éxito sin hacer nada; no se pide confirmación al operador.
- Procesa solo filas pendientes (texto cifrado nulo). Si una fila pendiente no tiene fecha en claro de origen, falla y la reporta: no inventa ni omite.
- Procesa en **lotes de 500 filas**, con commit por lote y sin mantener bloqueos entre lotes. El volumen esperado es el catálogo de jugadores de un despliegue real (miles de filas); el comando informa progreso y es reanudable.
- **Verificación única y completa de las filas procesadas:** cada fila que el backfill cifró debe descifrar exactamente al valor en claro de origen, y no debe quedar ninguna fila pendiente. No se acepta un muestreo como criterio.
- Es idempotente: una segunda ejecución no re-cifra lo ya cifrado y termina con éxito.
- Un fallo a mitad deja los lotes anteriores cifrados y permite reanudar sin duplicar. **Parcial es esperable y reanudable por diseño.** La exigencia de «sin datos a medias» aplica a las migraciones 017 y 018 (transaccionales) y al alta y la importación, no al backfill.
- **Política de recuperación:** con la verificación previa no puede existir cifrado con clave equivocada; si una ejecución se interrumpe, se reanuda con la misma clave correcta. El comando no intenta adivinar ni re-cifrar con otra clave.
- Si se ejecuta cuando la fecha en claro ya no existe (después de la 018), detecta el esquema final y termina con éxito sin hacer nada: no hay pendientes posibles porque el campo cifrado es obligatorio.
- Los logs y la salida solo contienen conteos, números de lote y duración; nunca nombre, documento, fecha, texto cifrado ni clave.

### RF-005 — Migración 018: cierre seguro y eliminación de la fecha en claro

CUANDO se aplica la migración 018 después del backfill, EL SISTEMA verifica que no queda ningún pendiente, hace obligatorio el campo cifrado, elimina la fecha en claro y deja los permisos definitivos.

*Criterios de aceptación:*
- La migración es transaccional: cualquier fallo deja la base en el estado anterior.
- Si existe al menos una fila con el campo cifrado nulo, la migración falla con un error explícito y no elimina la fecha en claro ni deja cambios parciales.
- Si no hay pendientes, hace obligatorio el campo cifrado y elimina la fecha en claro.
- Antes de eliminar, comprueba que ninguna vista o índice depende de la fecha en claro; la 017 ya recreó la proyección pública.
- Los permisos finales permiten insertar el campo cifrado y el resto de campos que ya se insertaban, sin lectura del texto cifrado y sin actualización ni borrado de la fila.
- Sobre un volumen limpio sin jugadores, la migración se aplica correctamente.
- Sobre una base en estado 017 con backfill completo, se aplica correctamente y conserva conteos y referencias.
- Es idempotente ante reejecución directa mediante guardas; después de aplicada, una reejecución directa no falla por objetos existentes.

### RF-006 — Secuenciación del despliegue y ejecución one-off del backfill

CUANDO se despliega esta funcionalidad sobre una base con datos históricos, EL SISTEMA permite aplicar 017, desplegar la imagen nueva, ejecutar el backfill y aplicar 018 en pasos reproducibles, sin que el runner por defecto ni el comando vuelvan a disparar migraciones fuera de orden.

*Criterios de aceptación:*
- El runner de migraciones acepta **`MIGRATION_TARGET`** (versión de tres dígitos) y **no** una bandera `--target`. Sin la variable, aplica todas las pendientes como hoy.
- Con `MIGRATION_TARGET=017` sobre una base en 016, aplica la 017 y la registra; reejecutar el mismo target no la vuelve a aplicar. Con `MIGRATION_TARGET=018` después del backfill, aplica solo la 018.
- **Checksums:** el runner sigue validando los checksums de **todos** los archivos de migración. El target solo omite la aplicación de los posteriores; la recorrida no se interrumpe ni deja sin validar los archivos posteriores.
- Un target con formato inválido, inexistente o posterior al último falla con un mensaje claro; un target anterior al último aplicado no desaplica nada.
- **Runbook y orden real:** ventana de mantenimiento con `api` y `worker` detenidos **y la aplicación antigua sin posibilidad de escribir la fecha antes de la 017** (parada del servicio), más copia de seguridad; `MIGRATION_TARGET=017`; despliegue de la imagen nueva del backend (que contiene el comando y opera con el esquema intermedio); ejecución del backfill como **servicio one-off sobre la imagen del backend, con `DATABASE_ADMIN_URL` y `PLAYER_DATA_KEY` inyectadas en su entorno y con `--no-deps`** para no reejecutar el servicio de migraciones con el target por defecto; `MIGRATION_TARGET=018`; verificación y arranque de `api`/`worker`.
- **Configuración concreta:** `MIGRATION_TARGET` es una variable no secreta del servicio de migraciones, documentada en la configuración de ejemplo, con valor por defecto vacío (todas las migraciones). El servicio one-off recibe `DATABASE_ADMIN_URL` y `PLAYER_DATA_KEY` por entorno; no se guardan valores en el repositorio. El comando exacto del backfill queda en la verificación esperada de esta spec y en el runbook.
- En una instalación nueva sin filas, el flujo por defecto (todas las migraciones) funciona sin ejecutar el backfill.
- En una base con datos históricos, el flujo por defecto no se usa sin el backfill: la 018 falla de forma cerrada y el runbook explica cómo reanudar.
- El job de CI con PostgreSQL prueba el target, sus errores y la reejecución.

### RF-007 — Alta, importación, jugador reutilizado y seed

CUANDO un administrador registra un jugador o importa una plantilla CSV/TXT con ZIP opcional, EL SISTEMA valida la fecha, la cifra, calcula y guarda la edad del jugador, y reutiliza al jugador existente sin modificar su fecha ni su edad.

*Criterios de aceptación:*
- El alta individual acepta la fecha con el mismo formato y las mismas reglas actuales; la importación exige la fecha y rechaza el archivo completo con el número de fila si falta o es inválida.
- Al crear o importar un jugador se calcula y guarda su edad con la fecha enviada y el año de referencia del torneo en cuyo contexto se crea.
- **Jugador reutilizado:** si la misma organización registra el mismo documento con otra fecha, el sistema reutiliza el jugador existente y **no modifica** su edad ni su año de referencia. La respuesta y la edad pública siguen correspondiendo a la primera fecha almacenada. Existe una prueba que crea el jugador con una fecha, lo reutiliza con otra y verifica que prevalece la almacenada.
- Tras el alta o la importación no queda ninguna copia de la fecha completa en claro.
- La importación con ZIP y consentimiento de foto es atómica: un fallo de fecha o de foto no deja un jugador ni un roster a medio crear.
- El alta y la importación funcionan con el rol de aplicación: si faltan los permisos de inserción de los campos nuevos, fallan con «permission denied». Existe una prueba de que el alta funciona de extremo a extremo.
- Los mensajes de error no incluyen la fecha ni el documento.
- La respuesta del alta y de la importación mantiene su forma actual y no incorpora la fecha, el texto cifrado ni `age`. `age` solo se expone en `GET /tournaments/{id}/rosters` (RF-009), y el modelo compartido de alta/importación no cambia.
- El seed de desarrollo cifra la fecha, materializa la edad, calcula la edad ajustada y sigue siendo idempotente y sin jugadores sin referencia.
- Cualquier otro camino de inserción incluye la edad y el año de referencia; los permisos de inserción de los campos nuevos están concedidos al rol de aplicación.

### RF-008 — Proyección pública: contrato estable y edad ajustada

MIENTRAS un torneo está publicado, EL SISTEMA expone en las proyecciones públicas la edad ajustada al torneo, nunca la fecha completa ni el texto cifrado, y conserva el contrato público existente.

*Criterios de aceptación:*
- Las proyecciones públicas conservan el mismo conjunto, orden y tipo de columnas. En particular, la edad pública sigue siendo **entero**; la nueva expresión no puede cambiar el tipo aunque la recreación sea sustitutiva.
- La edad pública se calcula como `edad del jugador + (año de inicio del torneo − año de referencia)` y equivale a `año del torneo − año de nacimiento` en todos los casos.
- Si el año de inicio del torneo cambia antes o después de publicar, la edad pública cambia exactamente en el delta de años; si cambia dentro del mismo año, no cambia. No se actualizan jugadores ni rosters por ese cambio.
- Las proyecciones no exponen la fecha completa ni el texto cifrado, ni directa ni indirectamente.
- Funcionan sin contexto de organización y sin que el visitante anónimo necesite la clave.
- La consulta pública no descifra y no ejecuta una consulta adicional por jugador.
- La foto sigue apareciendo solo con consentimiento y el resto de columnas públicas no cambia.

### RF-009 — Workspace: `age` solo en el listado y en la UI

EL SISTEMA incluye `age` **solo** en la respuesta de `GET /tournaments/{id}/rosters`, mantiene sin cambios las respuestas de alta e importación y muestra la edad en la UI sin exponer la fecha.

*Criterios de aceptación:*
- `GET /tournaments/{id}/rosters` incluye `age` como edad ajustada al torneo (mismo cálculo que la proyección pública) y no incluye la fecha ni el texto cifrado.
- Las respuestas de alta individual y de importación **no cambian**: no incorporan `age`, ni la fecha, ni el texto cifrado. El modelo compartido no se modifica; si el plan separa el modelo del listado, no puede cambiar el contrato acordado por su cuenta.
- La UI muestra `age` en el Workspace donde antes habría mostrado la fecha, con etiqueta i18n en español e inglés, y refresca la lista de rosters después de crear o importar. No se añade ningún control para introducir o revelar la fecha después del alta.
- El alta y la importación siguen enviando la fecha como hoy; la UI no la muestra después.
- Ningún endpoint del Workspace devuelve datos de un jugador de otra organización.
- Errores de validación y respuestas no repiten la fecha.
- Los checks de frontend (`pnpm test`, `pnpm run typecheck`, `pnpm run build`) pasan con el cambio, incluida la paridad de las claves i18n es/en y el refresco de la lista.

### RF-010 — Rango de fechas, validación y fallo cerrado

SI una fecha no es válida (no representable por el tipo fecha, posterior a la fecha actual o posterior a la creación del jugador), ENTONCES EL SISTEMA la rechaza en el alta, en la importación y en las migraciones 017/018, sin datos a medias y sin exponer el valor; el backfill rechaza la fila imposible y permite corregirla y reanudar.

*Criterios de aceptación:*
- El rango admitido es el del tipo fecha; no se impone un límite inferior artificial. Se rechaza siempre el futuro y la fecha posterior a la creación del jugador (en UTC).
- La validación se aplica en el alta individual, en la importación y en la migración/backfill, **incluidos jugadores sin roster**.
- Una fila histórica con fecha futura o posterior a la creación del jugador bloquea la migración o el backfill con un reporte verificable que no incluye el valor. Existe una prueba explícita de un jugador histórico **sin roster** con fecha futura rechazado por la 017/el backfill.
- La importación rechaza el archivo completo si alguna fila no tiene fecha o es imposible; no inserta las válidas.
- El alta individual rechaza una fecha futura sin repetir el valor en el mensaje; en el alta nueva, la fecha posterior a la creación coincide con el futuro y se rechaza por la misma regla.
- Las filas históricas válidas conservan su identificador y sus referencias.
- El seed falla si se le inyecta una fecha imposible.

### RF-011 — Pruebas de base de datos en CI y no regresión

EL SISTEMA ejecuta en integración continua pruebas contra PostgreSQL real que fallan si la fecha reaparece en claro, si se concede o deniega un permiso incorrecto, si se rompe el aislamiento, si la migración en dos fases falla, si la edad cambia o si un error filtra la fecha.

*Criterios de aceptación:*
- Prueba de que no queda ninguna columna con la fecha completa en claro ni en las vistas tras la 018.
- Prueba de permisos: el rol de aplicación no puede leer el texto cifrado, sí puede insertarlo y no puede actualizar ni borrar la fila; y el alta funciona de extremo a extremo (sin «permission denied»).
- Prueba del **estado intermedio**: tras la 017, el rol de aplicación no puede leer ni insertar la fecha en claro; la app nueva escribe solo el campo cifrado.
- Prueba de aislamiento: con dos organizaciones A y B, el contexto de B no devuelve ni descifra datos de A, y ninguna vista pública los expone.
- Prueba de ida y vuelta del cifrado, incluido el 29 de febrero.
- Prueba de la secuencia 016 → 017 → backfill → 018 sobre una base con datos: conteos, referencias, verificación completa del backfill, fallo cerrado sin backfill e idempotencia en el estado intermedio.
- Prueba de la secuencia sobre un volumen limpio.
- Prueba del backfill: lotes, reanudación tras fallo, segunda ejecución idempotente, verificación previa de clave con documento cifrado y **contraste de HMAC siempre**, tabla vacía como no-op sin confirmación, y salida sin PII.
- Prueba de `MIGRATION_TARGET`: 017 solo, 018 solo, target inválido, target posterior al último, reejecución y verificación de que los checksums de todos los archivos se siguen validando.
- Prueba de la proyección pública: mismo nombre, orden y tipo de columnas (edad como entero), edad correcta y cambio de año de inicio.
- Prueba del Workspace: solo `GET /tournaments/{id}/rosters` incluye `age` con el valor esperado; alta e importación no incluyen `age`; ninguna respuesta incluye la fecha.
- Prueba de frontend: etiqueta i18n de `age` en español e inglés, paridad de claves y refresco de la lista tras alta/importación; `pnpm test`, `pnpm run typecheck` y `pnpm run build`.
- Prueba del jugador reutilizado con otra fecha: prevalece la primera.
- Prueba de saneo de errores: el cuerpo 422 y los logs no contienen la fecha ni el documento.
- Prueba de alta, importación y seed con fechas imposibles.
- Prueba de jugador histórico **sin roster** con fecha futura y con fecha posterior a su creación: la 017/el backfill los rechazan.
- Todo se ejecuta con `RUN_DATABASE_TESTS=1` y el harness de la spec 001, de forma determinista y aislada; la suite sin base sigue funcionando sin la variable.

### RF-012 — Saneo de errores de validación y de base de datos

EL SISTEMA no incluye la fecha ni el documento en las respuestas de error de validación ni en los mensajes de error de base de datos registrados.

*Criterios de aceptación:*
- La respuesta 422 de alta e importación no repite el valor rechazado de la fecha ni del documento.
- Los errores de PostgreSQL que puedan contener la fila («Failing row contains») no se registran en logs ni se devuelven, o se sanean antes.
- Los mensajes de la migración, del backfill y de la importación no incluyen la fecha ni el documento.
- Existe una prueba que valida el cuerpo 422 y que revisa los logs capturados en busca de la fecha y el documento.
- El saneo es un comportamiento permanente de los endpoints afectados, no un caso especial del alta.

## Requisitos no funcionales

- **RNF-001. Compatibilidad de API:** el único cambio de contrato es aditivo: `age` **solo** en `GET /tournaments/{id}/rosters`. Las respuestas de alta e importación no cambian, y la forma de la proyección pública se mantiene.
- **RNF-002. Atomicidad:** las migraciones 017 y 018 se ejecutan en una transacción y no dejan datos a medias. El alta y la importación son atómicas. El backfill confirma por lote: un fallo deja lo ya cifrado y se reanuda; la 018 no elimina la fecha en claro hasta verificar que no quedan pendientes. El parcial es esperable solo en el backfill.
- **RNF-003. Rendimiento:** la lectura pública y la del Workspace no descifran y no añaden consultas por jugador; el ajuste de edad es aritmética entera. El backfill usa lotes de 500 filas y no mantiene bloqueos entre lotes.
- **RNF-004. Sin secretos nuevos:** se reutiliza `PLAYER_DATA_KEY`; no se agregan defaults de desarrollo fuera de la configuración de ejemplo ni secretos en migraciones, scripts o documentación.
- **RNF-005. No exposición en logs:** ni la fecha, ni el documento, ni el texto cifrado, ni la clave aparecen en logs, trazas, mensajes de error, historial de shell o archivos versionados.
- **RNF-006. Append-only:** se agregan las migraciones 017 y 018; no se editan 001-016.
- **RNF-007. Sin regresiones de aislamiento:** el rol de aplicación sigue sin ser superusuario y sin saltarse RLS; el cifrado no abre ninguna vía cross-tenant.
- **RNF-008. Volumen limpio y migrado:** la solución se verifica en ambos escenarios y respeta la relación entre inicialización y migraciones descrita en `AGENTS.md`.
- **RNF-009. Determinismo:** las pruebas usan fechas fijas y datos propios; no dependen del reloj, del orden ni del seed de demo. Las reglas con año de referencia no leen el reloj salvo el caso declarado de jugadores sin roster, donde se usa el año de `created_at` en UTC.
- **RNF-010. Verificación honesta:** lo que no pueda ejecutarse se declara como no ejecutado, con su motivo.
- **RNF-011. Reversibilidad operativa:** antes de la 017 existe una copia de seguridad verificada o un mecanismo equivalente para restaurar el estado 016.
- **RNF-012. Claridad operativa:** el runbook de dos fases, el servicio one-off con `DATABASE_ADMIN_URL`, `PLAYER_DATA_KEY` y `--no-deps`, y `MIGRATION_TARGET` en el entorno del servicio de migraciones quedan documentados con comandos exactos y criterios para reanudar.

## Datos personales y privacidad

- **Datos involucrados:** fecha de nacimiento de jugadores, además de los ya tratados por la spec 001 (nombre, apellidos, documento cifrado, HMAC, país emisor, foto y consentimiento).
- **Quién puede verlos:** la organización propietaria registra e importa la fecha y ve la edad en el listado del Workspace; no ve la fecha completa ni puede descifrarla. La administración de plataforma no obtiene acceso. El visitante público ve solo la edad.
- **Estado intermedio:** entre la 017 y la 018 la aplicación no puede leer ni insertar la fecha en claro; la única copia legible queda del lado administrativo para el backfill.
- **Qué se expone públicamente y en el Workspace:** la edad derivada, solo en el listado del Workspace y en la proyección pública. Nunca la fecha completa, el texto cifrado, el documento ni el HMAC. Las respuestas de alta e importación no exponen la edad.
- **En reposo:** la fecha completa se almacena cifrada con `PLAYER_DATA_KEY`. En claro solo quedan la edad del jugador y el año de referencia, que son el mismo dato público que la proyección ya exponía por diseño.
- **Exposición declarada:** la edad y el año de referencia permiten reconstruir el año de nacimiento, no el día ni el mes. La spec lo declara y lo prueba; no afirma que el año sea inaccesible.
- **En tránsito y en logs:** la fecha viaja en alta e importación, pero no se registra en logs, errores ni respuestas de validación.
- **Retención y backups:** los snapshots anteriores pueden contener la fecha completa en claro; su tratamiento y la rotación de clave son deuda separada.
- **Acceso cross-tenant:** ninguna otra organización puede ver ni descifrar datos de un jugador ajeno; se verifica con pruebas.

## Base constitucional de la edad derivada (sin excepción §5.1)

- El principio 5 rige **la proyección pública**, y la proyección ya expone la edad por diseño; esta spec no amplía lo que el público ve.
- §3.4 exige proteger con `PLAYER_DATA_KEY` los datos personales de jugadores. La **fecha completa** (día y mes) queda cifrada y fuera del alcance de la aplicación; lo que se materializa en claro es la edad y el año de referencia, que son el mismo dato derivado que la proyección pública ya publicaba.
- La ventana intermedia no amplía la exposición: tras la 017 la aplicación no puede leer ni insertar la fecha en claro, y la única copia legible queda del lado administrativo para el backfill.
- Por tanto no se necesita una excepción §5.1: no se relaja ningún principio innegociable ni se omite una regla. Sí se documenta la exposición real del año de nacimiento, ya presente antes de este cambio.
- Si en el futuro se exigiera que ni el año sea inferible, sería una spec aparte con descifrado controlado y una decisión constitucional expresa.

## Casos límite

1. **Jugador histórico con fecha válida:** se cifra; su edad y año de referencia se materializan; conserva identificador y referencias.
2. **Jugador histórico con fecha imposible (futura o posterior a su creación):** bloquea migración o backfill con reporte sin el valor.
3. **Fila pendiente de cifrado sin fecha en claro de origen:** el backfill falla y la reporta; no inventa ni omite.
4. **29 de febrero:** el cifrado y descifrado preservan el día exacto en años bisiestos.
5. **Clave incorrecta:** la verificación previa contra el documento cifrado falla —incluido el contraste de HMAC— y el comando aborta sin escribir.
6. **Tabla de jugadores vacía (sin ninguna fila con documento cifrado):** no hay nada que verificar ni cifrar; el comando termina sin hacer nada y no pide confirmación.
7. **Reejecución del backfill:** no re-cifra lo ya cifrado y termina con éxito.
8. **Fallo a mitad del backfill:** lo ya cifrado queda; al reanudar solo se procesan pendientes.
9. **Ejecución del backfill después de la 018:** detecta el esquema final y termina sin hacer nada.
10. **Jugador reutilizado con otra fecha:** prevalece la primera; edad y fecha pública no cambian por la segunda alta.
11. **Jugador reutilizado en torneos de años distintos:** la edad ajustada usa el delta de cada torneo.
12. **Cambio del año de inicio del torneo antes o después de publicar:** la edad cambia en el delta; dentro del mismo año, no cambia.
13. **Fecha de inicio anterior al nacimiento:** se conserva el resultado de la fórmula; esta spec no añade elegibilidad.
14. **Importación sin fecha o con fecha imposible:** se rechaza el archivo completo; no se insertan las válidas.
15. **Cuerpo 422 con la fecha rechazada:** no repite el valor; el saneo se prueba.
16. **Error de base de datos con «Failing row contains»:** no se registra ni se devuelve con valores.
17. **Jugador sin roster:** se valida su fecha y se le asigna el año de `created_at` en UTC; si la fecha es futura o posterior a su creación, la 017/el backfill la rechazan. Existe una prueba explícita.
18. **Volumen limpio:** inicialización + migraciones funcionan y el flujo por defecto no requiere backfill.
19. **Consulta pública sin contexto de organización:** sigue devolviendo filas publicadas y solo la edad.
20. **Lectura por el rol de aplicación:** `SELECT *` no devuelve el texto cifrado; en el estado intermedio tampoco devuelve la fecha en claro, y el rol no puede insertarla. Las columnas derivadas sí son legibles.
21. **Backfill largo:** lotes de 500, sin bloqueos entre lotes, reanudable; el volumen esperado es el catálogo de miles de jugadores.
22. **Escrituras durante el despliegue:** el runbook detiene `api`/`worker` antes de la 017; si aparece un jugador nuevo, se cifra con la aplicación nueva y no queda pendiente.
23. **Target de migración mal escrito o posterior al último:** falla antes de aplicar nada.
24. **Reejecución de 017 en el estado intermedio:** no duplica ni falla; tras la 018, falla por diseño y el runbook no la reejecuta.
25. **Reejecución de 018:** las guardas evitan fallos por objetos existentes.
26. **Roster nuevo en el esquema intermedio sin fecha en claro:** permitido por la 017; la aplicación inserta solo el campo cifrado y la edad, porque no tiene `INSERT` de la fecha en claro.
27. **Fecha posterior a la creación del jugador en una fila histórica:** se considera imposible; 017/backfill la rechazan y la reportan sin exponer el valor.

## Criterios de finalización

1. No queda ninguna copia de la fecha completa en claro en tablas, índices, vistas ni proyecciones; todas las filas están cifradas con `PLAYER_DATA_KEY`.
2. La aplicación puede insertar los campos nuevos y no puede leer el texto cifrado; en el estado intermedio tampoco puede leer ni insertar la fecha en claro; el alta, la importación y el seed funcionan de extremo a extremo.
3. Las migraciones 017 y 018 se aplican en orden sobre volumen limpio y sobre base en 016, con backfill, verificación completa, fallo cerrado sin backfill e idempotencia en el estado intermedio.
4. `python -m scripts.encrypt_birth_dates` verifica siempre la clave y el HMAC contra el documento cifrado, cifra por lotes, es idempotente y reanudable, y no deja PII en logs.
5. La edad materializada vive en el jugador, se calcula con la fecha enviada, se ajusta por torneo y un alta posterior con otra fecha no la modifica.
6. La proyección pública conserva columnas, orden y tipos (edad como entero) y devuelve la edad correcta.
7. `GET /tournaments/{id}/rosters` incluye `age` y la UI la muestra con etiqueta i18n es/en y refresco de lista; las respuestas de alta e importación no cambian y no se expone la fecha.
8. Los errores de validación y de base de datos no filtran la fecha ni el documento.
9. `MIGRATION_TARGET` limita la aplicación sin romper la validación de checksums y el runbook de dos fases está documentado y probado.
10. Las pruebas de BD en CI cubren exposición, permisos, estado intermedio, aislamiento, migración, backfill, target, edad, Workspace, jugadores sin roster, fecha imposible y saneo de errores.
11. La documentación afectada y la configuración de ejemplo reflejan el nuevo estado, y los jobs de CI aplicables están en verde; lo no ejecutado se declara.

## Impacto en la constitución

| Principio, regla o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento por tenant garantizado por la base de datos | Sí | La tabla conserva RLS forzado; el cifrado no abre ninguna vía cross-tenant y se prueba con dos organizaciones. |
| §2.2 La aplicación no puede saltarse RLS | Sí | No se eleva el rol ni se desactiva RLS; las pruebas se ejecutan con el rol de aplicación. |
| §2.4 Historial de esquema append-only | Sí | Se agregan las migraciones 017 y 018; no se editan 001-016. |
| §2.5 Lo público es una proyección mínima | Sí | La proyección pública conserva su forma y solo expone la edad; no añade fecha ni datos sensibles. |
| §2.6 Ningún secreto por defecto fuera de desarrollo | Sí | Se reutiliza `PLAYER_DATA_KEY`; no se agregan secretos ni defaults. |
| §2.8 Nada se da por terminado sin verificación | Sí | Pruebas de BD en CI y secuencia 017 → backfill → 018 sobre volumen limpio y migrado. |
| §3.1 RLS y migraciones | Sí | Migraciones nuevas con checksum; ambos volúmenes verificados. |
| §3.2 Backend asíncrono | Sí | Alta, importación y backfill usan el acceso asíncrono y transacciones acotadas. |
| §3.4 Seguridad y datos personales | Sí (núcleo) | La fecha completa se almacena cifrada con `PLAYER_DATA_KEY` y no aparece en logs, errores ni proyecciones públicas; se cierra R05. La edad derivada es el dato público ya existente. |
| §4 Criterios para cambios de BD y backend | Sí | Migraciones nuevas, pruebas, permisos revisados, endpoints públicos sin campos sensibles. |
| §4 Criterios para cambios de frontend | Sí | Cambio mínimo para mostrar `age`; `pnpm test`, `typecheck` y `build`. |
| §5 Excepciones | No | No se requiere excepción: ver «Base constitucional de la edad derivada». |
| §6 Definición de cumplimiento | Sí | CI en verde, revisión humana distinta del autor y verificación honesta. |

## Módulos y áreas afectadas (el plan detallará archivos y tipos)

- **Migraciones 017 y 018** del historial numerado: esquema intermedio con revocación del `SELECT`/`INSERT` de la fecha en claro, cifrado y edad del jugador, permisos, proyección pública y eliminación de la fecha en claro.
- **Runner de migraciones** con `MIGRATION_TARGET` y la configuración de ejemplo/compose que lo exponen al servicio de migraciones.
- **Comando de backfill** ejecutable como servicio one-off con `DATABASE_ADMIN_URL`, `PLAYER_DATA_KEY` y `--no-deps`.
- **Backend de torneos:** alta individual e importación (cálculo de la edad y reutilización del jugador), consulta de rosters del Workspace con `age` solo en el listado, seed de desarrollo.
- **Proyección pública:** recreada con la edad ajustada y el contrato de columnas y tipos intacto.
- **Frontend:** `age` en el listado del Workspace, etiqueta i18n es/en y refresco de la lista tras alta/importación; las respuestas de alta e importación no cambian.
- **Pruebas de base de datos** del harness existente y pruebas de contrato de API/UI, incluida la paridad i18n y el refresco de lista.
- **Documentación:** runbook de dos fases, `MIGRATION_TARGET`, cifrado y exposición declarada de la edad.
- **Sin cambios:** configuración de RLS, claves foráneas, cifrado del documento y migraciones 001-016.

## Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Clave incorrecta en el backfill | Cifrado irrecuperable si se elimina la fecha | Verificación previa contra el documento cifrado con **contraste de HMAC siempre**; aborta sin escribir; la tabla vacía es un no-op; copia de seguridad previa. |
| Aplicación antigua todavía escribiendo tras la 017 | Intento de insertar la fecha en claro sin permiso o datos inconsistentes | Ventana de mantenimiento que detiene `api`/`worker` antes de la 017; la app nueva opera con el esquema intermedio y escribe solo el campo cifrado. |
| Orden de despliegue incorrecto o servicio de migraciones disparado por dependencias | Aplicar 018 sin backfill | Runbook con `MIGRATION_TARGET` y `--no-deps` en el one-off; la 018 falla de forma cerrada. |
| Falta el permiso de inserción de los campos nuevos | «Permission denied» en alta, importación y seed | Permisos concedidos al rol de aplicación y prueba de alta de extremo a extremo. |
| La recreación de la vista cambia el tipo de la edad | Ruptura del contrato público | Requisito de conservar nombre, orden y tipo (entero) y prueba de columnas/tipos. |
| Fuga de la fecha en un 422 o en un error de base de datos | Exposición de dato personal | Saneo de respuestas y de logs, con pruebas del cuerpo 422 y de los logs. |
| Edad obsoleta al cambiar el año de inicio del torneo | Edad pública incorrecta | Regla de delta por año; pruebas antes y después de publicar. |
| Alta posterior con otra fecha modifica al jugador existente | Inconsistencia o intento de descifrado | La reutilización no toca la fecha ni la edad; prueba específica. |
| El plan añade `age` a alta/importación o cambia el listado por su cuenta | Ruptura del contrato aditivo acordado | El contrato está fijado: `age` solo en `GET /tournaments/{id}/rosters`; se revisa contra RF-009. |
| La edad y el año de referencia permiten inferir el año de nacimiento | Exposición declarada | Es el dato público ya existente; no se guarda día ni mes; la fecha completa sigue cifrada; documentado y probado. |
| Fecha histórica imposible (futura o posterior a la creación), incluidos jugadores sin roster | Migración bloqueada | Fallo cerrado con reporte sin valores; el operador corrige y reintenta; prueba específica. |
| Backfill largo o bloqueo de la tabla | Impacto operativo | Lotes de 500 sin bloqueos entre lotes, ventana de mantenimiento y reanudación. |
| Volumen limpio roto por orden de vistas | Error tipo «cannot drop columns from view» | Respetar inicialización + migraciones, recrear la vista antes de eliminar la fecha y probar el volumen limpio. |
| Tests y helpers siguen insertando la fecha en claro | Suite roja o falsa cobertura | Actualizar helpers y pruebas; la suite falla si reaparece. |
| `MIGRATION_TARGET` mal configurado en producción | Migraciones incompletas | Validación de formato y existencia, default vacío y mensajes claros; `--target` no existe. |
| Backups y snapshots con la fecha completa | Exposición fuera de la base activa | Deuda separada documentada junto con la rotación de clave. |

## Verificación esperada

- **Backend unitario:** `cd backend && pytest -q` y `cd backend && python -m compileall -q app`.
- **Backend con PostgreSQL:** job de CI con PostgreSQL 17 y `RUN_DATABASE_TESTS=1`, rol administrador para migraciones y rol de aplicación para pruebas, con el harness de la spec 001.
- **Cifrado y permisos:** el rol de aplicación no puede seleccionar el texto cifrado, sí puede insertarlo, no puede actualizar ni borrar la fila, y el alta funciona de extremo a extremo.
- **Estado intermedio:** tras la 017, el rol de aplicación no puede leer ni insertar la fecha en claro; la app nueva escribe solo el campo cifrado.
- **Secuencia de migración:** sobre base en 016 con datos: `MIGRATION_TARGET=017`, backfill, `MIGRATION_TARGET=018`; verificar conteos, referencias, verificación completa del backfill, ausencia de fecha en claro y contrato de la vista. Repetir sobre volumen limpio.
- **Comando del backfill (one-off, con `--no-deps`):** con `DATABASE_ADMIN_URL` y `PLAYER_DATA_KEY` inyectadas en el entorno del servicio, `docker compose run --rm --no-deps api python -m scripts.encrypt_birth_dates`; comprobar verificación previa de clave con contraste de HMAC siempre, tabla vacía como no-op, lotes, reanudación, idempotencia y salida sin PII. El comando exacto y el entorno quedan en el runbook.
- **Fallo cerrado:** ejecutar 018 sin backfill y comprobar que falla sin borrar nada; ejecutar el backfill con clave incorrecta o HMAC manipulado y comprobar que aborta antes de escribir.
- **`MIGRATION_TARGET`:** con PostgreSQL, 017 solo, 018 solo, target inválido, target posterior al último, reejecución y validación de los checksums de todos los archivos; `sh -n infra/postgres/migrate.sh`.
- **Aislamiento:** dos organizaciones; el contexto de B no lee ni descifra datos de A; sin contexto no hay filas; las vistas públicas no exponen la fecha.
- **Alta e importación:** alta, CSV con y sin ZIP, fila sin fecha, fecha imposible y fecha futura; comprobar cifrado, edad materializada, jugador reutilizado con otra fecha, atomicidad y respuestas sin fecha ni `age`.
- **Jugador sin roster:** fecha futura y fecha posterior a su creación rechazadas por la 017/el backfill; año de referencia de `created_at` en UTC.
- **Workspace:** solo `GET /tournaments/{id}/rosters` incluye `age` correcto y no incluye la fecha; alta e importación no incluyen `age`; la UI refresca la lista y tiene la etiqueta i18n es/en; `pnpm test`, `pnpm run typecheck` y `pnpm run build`.
- **Errores:** el cuerpo 422 y los logs capturados no contienen la fecha ni el documento.
- **Seed:** `python -m scripts.seed_demo` tras la secuencia; idempotencia, referencias, fechas cifradas y edades correctas.
- **Proyección pública:** mismo nombre, orden y tipos (edad entero), edad correcta, cambio de año de inicio y acceso sin contexto.
- **Migraciones:** `sh -n infra/postgres/migrate.sh`; ninguna migración aplicada modificada; secuencia 001-018 sin huecos.
- **Compose:** `docker compose config -q` en desarrollo y en el merge de producción con `MIGRATION_TARGET` opcional.

## Dudas abiertas

Ninguna. Las cinco decisiones están cerradas y se incorporaron las 21 correcciones de la primera QA, las 8 de la segunda y las de la ronda de validación funcional (véase «Ronda de validación de la spec»). En particular: la 017 revoca el `SELECT` y el `INSERT` de la fecha en claro y la ventana de mantenimiento detiene la app antigua; `age` está solo en `GET /tournaments/{id}/rosters`, con etiqueta i18n es/en y refresco de lista, sin cambios en alta/importación; el backfill contrasta **siempre** el HMAC y la tabla vacía es un no-op; el mecanismo concreto es `DATABASE_ADMIN_URL`/`PLAYER_DATA_KEY` en el servicio one-off con `--no-deps` y `MIGRATION_TARGET` en el servicio de migraciones; la referencia histórica usa `registered_at` (desempate por id) y `created_at` en UTC para jugadores sin roster; la fecha posterior a la creación se considera imposible; y «sin datos a medias» aplica a 017/018 y alta/importación, no al backfill.
