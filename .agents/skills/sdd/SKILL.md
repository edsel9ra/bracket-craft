---
name: sdd
description: Úsala siempre que trabajes con Spec-Driven Development en este proyecto (docs/constitution.md o cualquier archivo dentro de specs/) - redactar, revisar o cambiar specs, planes y tareas, o implementar y validar tareas de una spec.
---

# Spec-Driven Development (SDD) — Bracket Craft

## Fuentes de verdad

Antes de empezar cualquier fase, lee lo que aplique:

- `docs/constitution.md`: principios innegociables, reglas y criterios obligatorios. Tiene precedencia sobre todo lo demás.
- `AGENTS.md`: comandos, estructura y convenciones del repositorio.
- `README.md`: alcance del producto y modelo de acceso.
- `MEMORY.md` (raíz): estado y decisiones del trabajo SDD en curso.
- `specs/NNN-nombre/`: spec, plan y tareas de la funcionalidad en cuestión.

Si algo de la spec contradice la constitución, gana la constitución: se detiene el trabajo y se le informa al usuario.

## Flujo

Constitución → Spec → Clarificación → Plan → Tareas → Implementación → Validación → Cambio.

- Nunca pases a la siguiente fase sin la aprobación explícita del usuario.
- La spec manda: si algo no está en la spec, no se implementa. Si falta una decisión, para y pregunta.
- Un cambio de requisitos se hace primero en la spec, luego en el plan y las tareas, y por último en el código.
- Cada spec vive en su carpeta: `specs/NNN-nombre/` con `spec.md`, `plan.md` y `tasks.md`. `NNN` es el siguiente número libre, con tres dígitos.
- Al terminar cada fase, actualiza `MEMORY.md`.

## MEMORY.md

Archivo en la raíz del repositorio con el estado del trabajo SDD. Se actualiza al cerrar cada fase y se lee al comenzar cada sesión. Estructura:

```
# Memoria SDD

## Spec activa
- specs/NNN-nombre — fase actual: <fase> — estado: <borrador|aprobada|implementada>

## Decisiones tomadas
- AAAA-MM-DD · Spec NNN · <decisión y motivo breve>

## Pendiente
- <siguiente paso concreto o pregunta abierta>

## Historial de fases
- AAAA-MM-DD · Spec NNN · <fase> cerrada · aprobada por el usuario
```

Reglas: registra solo hechos y decisiones, no borradores ni especulación. Si `MEMORY.md` contradice a una spec aprobada, manda la spec y se corrige `MEMORY.md`. No guardes secretos ni datos personales.

## Fase 1 — Spec (spec.md)

Plantilla:

````
# Spec NNN — <Nombre>

Estado: borrador | aprobada | implementada

## Contexto y objetivo
## Usuarios
## Roles y visibilidad
- <rol>: qué ve y qué puede hacer (público, miembro de organización, administrador de organización, administrador de plataforma).
## Historias de usuario
- HU-1. Como <rol>, quiero <acción> para <beneficio>.
## Definiciones (solo si hay términos que puedan interpretarse de varias formas)
## Requisitos funcionales
## Requisitos no funcionales
## Datos personales y privacidad
- Datos personales involucrados, quién puede verlos y qué se expone públicamente.
## Casos límite
## Fuera de alcance
## Criterios de finalización
## Dudas abiertas
- [NECESITA ACLARACIÓN] <duda>
````

La spec describe el QUÉ y el POR QUÉ. Nada de stack, arquitectura ni nombres de archivos.

Si la funcionalidad no toca roles, datos personales ni contenido público, escribe "No aplica" en esas secciones en lugar de omitirlas.

### Requisitos en EARS (en español)

- RF-x: CUANDO <evento>, EL SISTEMA <respuesta>.
- RF-x: SI <condición no deseada>, ENTONCES EL SISTEMA <respuesta>.
- RF-x: MIENTRAS <estado>, EL SISTEMA <respuesta>.
- RF-x: EL SISTEMA <comportamiento permanente>.

Cada RF debe ser verificable: nada de "rápido", "intenso" o "bonito" sin un criterio medible. Todo requisito que afecte a datos de una organización debe dejar claro que ninguna otra organización puede ver ni modificar esos datos.

## Fase 2 — Clarificación

1. Lista todas las entradas `[NECESITA ACLARACIÓN]` de la spec y cualquier ambigüedad, contradicción o requisito no verificable que detectes.
2. Pregunta al usuario, agrupando las preguntas y ofreciendo opciones con tu recomendación cuando sea posible. Máximo cuatro preguntas por ronda.
3. Registra cada respuesta en la spec (en el requisito, caso límite o definición correspondiente) y elimina la marca de duda resuelta.
4. Si una respuesta contradice la constitución, informa al usuario y no la incorpores.
5. La fase termina cuando no quedan dudas abiertas y el usuario aprueba la spec. Entonces el estado pasa a `aprobada` y se actualiza `MEMORY.md`.

## Fase 3 — Plan (plan.md)

Contenido obligatorio:

- Archivos y responsabilidades.
- Funciones puras: toda función que dependa del tiempo recibe la fecha como parámetro; nada de leer el reloj dentro de la lógica.
- Algoritmo en pseudocódigo, cuando haya lógica no trivial (por ejemplo, desempates o clasificación).
- Interfaz: endpoints, contratos y pantallas.
- Decisiones justificadas, cada una con su alternativa descartada.
- Estrategia de tests.
- Qué RF cubre cada parte.

Apartados específicos del proyecto, cuando apliquen:

- **Base de datos:** número de la nueva migración, tablas, políticas RLS y cómo se verifica sobre un volumen limpio y uno ya migrado.
- **Backend:** módulo bajo `backend/app/modules/` y registro de su router en `backend/app/main.py`; uso de `set_rls_context()` dentro de la transacción.
- **Eventos asíncronos:** eventos de outbox, procesamiento en el worker y efecto en tiempo real (Socket.IO).
- **Frontend:** uso de `frontend/composables/useApi.ts`, rutas públicas o del Workspace.
- **Exposición pública:** campos exactos que expondrá cualquier proyección pública, confirmando que no incluyen documentos ni fechas de nacimiento, y que las fotos dependen del consentimiento de imagen.
- **Configuración y secretos:** variables nuevas y su default solo en `.env.example`.

### Verificación de constitución

Todo plan termina con una tabla que revisa cada principio innegociable de `docs/constitution.md` y cada criterio obligatorio de la sección 4 que aplique:

```
| Principio o criterio | Aplica | Cómo se cumple |
|----------------------|--------|----------------|
```

Si algún principio no se cumple, el plan no se presenta como listo: se rediseña o se le informa al usuario. Los principios innegociables no admiten excepción; las reglas y criterios solo con una excepción válida según la sección 5.1 de la constitución.

## Fase 4 — Tareas (tasks.md)

```
- [ ] **Tn. <Descripción>.** RF-x, RF-y
- Hecho cuando: <comprobación verificable>.
```

- Máximo 20-30 min por tarea, en orden de dependencia.
- Si salen más de 10 tareas, propón dividir la spec.
- "Hecho cuando" cita comandos concretos del proyecto, por ejemplo: `cd backend && pytest -q`, `cd frontend && pnpm test`, `cd frontend && pnpm run typecheck`, `sh -n infra/postgres/migrate.sh`.
- Las pruebas de invitaciones requieren PostgreSQL con datos demo y se ejecutan con `RUN_DATABASE_TESTS=1`, como indica `AGENTS.md`.
- Toda tarea que cambie el esquema es una migración nueva numerada; nunca la edición de una existente.

## Fase 5 — Implementación

Una sola tarea cada vez:

1. Escribe los tests primero y confírmalos en rojo.
2. Escribe el código mínimo necesario.
3. Ejecuta los tests hasta que estén en verde.
4. Marca la tarea en `tasks.md` y para.

No implementes nada que no esté en la spec. Si descubres una necesidad no cubierta, detente y pregúntale al usuario (véase Fase 7).

## Fase 6 — Validación

Cuando todas las tareas estén marcadas:

1. Ejecuta los jobs de CI que apliquen al cambio: `backend`, `frontend`, `infrastructure` y `security`, con los comandos de `AGENTS.md`.
2. Recorre los criterios obligatorios de la sección 4 de `docs/constitution.md` y confirma cada uno.
3. Comprueba cada RF y cada criterio de finalización de la spec, citando la prueba o evidencia que lo respalda.
4. Informa con honestidad: si algo no pudo ejecutarse o falla, dilo; nunca declares una verificación no realizada.
5. Con la aprobación del usuario, el estado de la spec pasa a `implementada` y se actualiza `MEMORY.md`.

## Fase 7 — Cambio

Si cambian los requisitos o aparece una necesidad nueva sobre una spec aprobada o implementada:

1. Registra el cambio primero en `spec.md` y vuelve a pasarla por Clarificación si hay dudas.
2. Actualiza `plan.md` y `tasks.md`, incluida la verificación de constitución.
3. Obtén la aprobación del usuario antes de tocar el código.
4. Implementa solo las tareas nuevas o modificadas, siguiendo la Fase 5.
5. Anota el cambio y su motivo en `MEMORY.md`.

Si un cambio implica enmendar la constitución, se hace como un cambio propio, siguiendo la sección 5.2 de `docs/constitution.md`, y nunca mezclado con cambios funcionales.