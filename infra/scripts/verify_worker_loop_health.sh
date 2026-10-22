#!/bin/sh
# Verificación operativa de la salud del worker del outbox (spec 009, RF-011).
#
# Observa la transición real healthy -> unhealthy -> healthy del healthcheck de
# Docker congelando SOLO el proceso del bucle del worker (SIGSTOP al PID 1
# dentro del contenedor). El proceso del healthcheck se ejecuta en su propio
# ``exec`` y sigue evaluando la frescura del latido, así que Docker pasa a
# ``unhealthy`` cuando el bucle deja de completar vueltas y vuelve a ``healthy``
# en cuanto se reanuda con SIGCONT, sin reiniciar el contenedor. No se pausa el
# contenedor completo: eso congelaría también el healthcheck y la transición no
# sería observable. Se intenta primero con ``docker exec ... kill -STOP 1``; como
# el PID 1 de un namespace de PID ignora SIGSTOP enviado desde su propio
# namespace, si no se detiene se envía el mismo SIGSTOP al PID 1 desde el host.
#
# Además, tras la recuperación y sin reiniciar, la verificación inserta una
# sonda de outbox inocua con ``python -m scripts.outbox_probe insert`` y espera
# a que el worker la marque como ``processed`` (paso 7). La cola es la prueba
# persistida; el stream solo se cita como corroboración y nunca decide. La
# sonda se borra siempre en el trap de salida, tanto en éxito como en fallo.
#
# Antes de esperar o congelar nada, el paso 0 pregunta al propio worker su
# ``APP_ENV`` (``python -m scripts.outbox_probe guard``): la sonda escribe en la
# cola, así que fuera de desarrollo/local la verificación es NO EJECUTABLE
# (código 2) y no toca el worker. La utilidad repite el guard en cada comando.
# La sonda usa la organización y el propietario demo ya sembrados; si faltan o el
# propietario no es miembro activo, la utilidad responde 2 sin escribir y la
# verificación también es NO EJECUTABLE (código 2), tanto al insertar como si el
# caso aparece al consultar el estado.
#
# Uso:
#   sh infra/scripts/verify_worker_loop_health.sh [servicio|contenedor]
#
# Variables de entorno:
#   WORKER_TARGET                   servicio de Compose o contenedor
#                                   (defecto: bracket-craft-worker-1)
#   WORKER_HEALTH_READY_TIMEOUT     s de espera al estado sano inicial (defecto: 60)
#   WORKER_HEALTH_UNHEALTHY_TIMEOUT s de espera al estado insano (defecto: 180)
#   WORKER_HEALTH_RECOVERY_TIMEOUT  s de espera a la recuperación (defecto: 120)
#   WORKER_HEALTH_POLL_INTERVAL     s entre sondeos (defecto: 5)
#   WORKER_PROBE_TIMEOUT            s de presupuesto para la sonda (defecto: 120);
#                                   cubre los reintentos del outbox (5 x 5 s)
#   WORKER_PROBE_POLL_INTERVAL      s entre sondeos de la sonda (defecto: 2)
#
# Códigos de salida:
#   0  se observó la transición healthy -> unhealthy -> healthy y el worker
#      procesó la sonda
#   1  fallo de comportamiento: algún paso falló (se indica cuál), incluida la
#      sonda (failed, desaparecida o presupuesto agotado) y su borrado
#   2  no ejecutable: falta Docker, falta el contenedor, los argumentos o las
#      variables son inválidos, faltan los datos demo (organización y
#      propietario demo, o su membresía activa) o el worker no está en
#      desarrollo/local (no se escribe nada). La verificación queda declarada
#      como NO EJECUTADA.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=${REPO_ROOT:-$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)}
COMPOSE_FILE=${COMPOSE_FILE:-"$REPO_ROOT/docker-compose.yml"}
export COMPOSE_FILE

WORKER_TARGET=${WORKER_TARGET:-bracket-craft-worker-1}
WORKER_HEALTH_READY_TIMEOUT=${WORKER_HEALTH_READY_TIMEOUT:-60}
WORKER_HEALTH_UNHEALTHY_TIMEOUT=${WORKER_HEALTH_UNHEALTHY_TIMEOUT:-180}
WORKER_HEALTH_RECOVERY_TIMEOUT=${WORKER_HEALTH_RECOVERY_TIMEOUT:-120}
WORKER_HEALTH_POLL_INTERVAL=${WORKER_HEALTH_POLL_INTERVAL:-5}
WORKER_PROBE_TIMEOUT=${WORKER_PROBE_TIMEOUT:-120}
WORKER_PROBE_POLL_INTERVAL=${WORKER_PROBE_POLL_INTERVAL:-2}

LOOP_FROZEN=0
PROBE_ID=""
PROBE_MARKER=""

info() {
    printf '\n== %s\n' "$*"
}

progress() {
    printf '   %s\n' "$*"
}

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

not_executable() {
    printf 'NO EJECUTADA (no ejecutable): %s\n' "$*" >&2
    exit 2
}

now_seconds() {
    date +%s
}

is_positive_integer() {
    case "$1" in
        ''|*[!0-9]*) return 1 ;;
    esac
    [ "$1" -gt 0 ]
}

usage() {
    printf 'uso: %s [servicio|contenedor]\n' "$0" >&2
}

if [ "$#" -gt 1 ]; then
    usage
    not_executable "demasiados argumentos; solo se admite un servicio o contenedor"
fi

if [ "$#" -eq 1 ]; then
    WORKER_TARGET=$1
fi

if [ -z "$WORKER_TARGET" ]; then
    usage
    not_executable "el servicio o contenedor del worker no puede estar vacío"
fi

for setting in \
    "WORKER_HEALTH_READY_TIMEOUT=$WORKER_HEALTH_READY_TIMEOUT" \
    "WORKER_HEALTH_UNHEALTHY_TIMEOUT=$WORKER_HEALTH_UNHEALTHY_TIMEOUT" \
    "WORKER_HEALTH_RECOVERY_TIMEOUT=$WORKER_HEALTH_RECOVERY_TIMEOUT" \
    "WORKER_HEALTH_POLL_INTERVAL=$WORKER_HEALTH_POLL_INTERVAL" \
    "WORKER_PROBE_TIMEOUT=$WORKER_PROBE_TIMEOUT" \
    "WORKER_PROBE_POLL_INTERVAL=$WORKER_PROBE_POLL_INTERVAL"
do
    name=${setting%%=*}
    value=${setting#*=}
    if ! is_positive_integer "$value"; then
        not_executable "$name debe ser un entero positivo; recibido: $value"
    fi
done

command -v docker >/dev/null 2>&1 ||
    not_executable "docker no está disponible en PATH"

docker info >/dev/null 2>&1 ||
    not_executable "el demonio de Docker no responde"

# Resuelve el destino como contenedor por nombre o como servicio de Compose.
CONTAINER=""
CONTAINER_ID=""
if docker inspect --format '{{.Id}}' "$WORKER_TARGET" >/dev/null 2>&1; then
    CONTAINER=$WORKER_TARGET
    CONTAINER_ID=$(docker inspect --format '{{.Id}}' "$CONTAINER")
else
    CONTAINER_ID=""
    if [ -f "$COMPOSE_FILE" ]; then
        CONTAINER_ID=$(cd "$REPO_ROOT" && docker compose ps -q "$WORKER_TARGET" 2>/dev/null | sed -n '1p') || CONTAINER_ID=""
    fi
    [ -n "$CONTAINER_ID" ] ||
        not_executable "no existe el contenedor ni el servicio en ejecución: $WORKER_TARGET"
    CONTAINER=$CONTAINER_ID
fi

# ``docker exec`` directo o ``docker compose exec`` cuando el contenedor
# pertenece al proyecto de Compose de este repositorio (misma garantía, con el
# servicio como referencia estable).
EXEC_MODE=container
COMPOSE_PROJECT=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$CONTAINER_ID" 2>/dev/null || true)
COMPOSE_SERVICE=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$CONTAINER_ID" 2>/dev/null || true)
if [ -n "$COMPOSE_PROJECT" ] && [ -n "$COMPOSE_SERVICE" ] && [ -f "$COMPOSE_FILE" ]; then
    resolved_id=$(cd "$REPO_ROOT" && docker compose -p "$COMPOSE_PROJECT" ps -q "$COMPOSE_SERVICE" 2>/dev/null | sed -n '1p') || resolved_id=""
    if [ "$resolved_id" = "$CONTAINER_ID" ]; then
        EXEC_MODE=compose
    fi
fi

worker_exec() {
    if [ "$EXEC_MODE" = compose ]; then
        ( cd "$REPO_ROOT" && exec docker compose -p "$COMPOSE_PROJECT" exec -T "$COMPOSE_SERVICE" "$@" )
    else
        docker exec "$CONTAINER" "$@"
    fi
}

health_status() {
    status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER" 2>/dev/null) || status=missing
    printf '%s' "$status"
}

container_running() {
    running=$(docker inspect --format '{{.State.Running}}' "$CONTAINER" 2>/dev/null) || running=false
    [ "$running" = true ]
}

# Instantánea para demostrar que la recuperación no depende de un reinicio.
container_snapshot() {
    docker inspect --format '{{.RestartCount}}|{{.State.StartedAt}}|{{.State.Pid}}' "$CONTAINER" 2>/dev/null
}

# Estado del PID 1 (``T`` o ``t`` = detenido por señal).
pid1_state() {
    worker_exec sh -c 'while read -r key value rest; do
        if [ "$key" = "State:" ]; then
            printf "%s" "$value"
            break
        fi
    done < /proc/1/status'
}

pid1_stopped() {
    state=$(pid1_state 2>/dev/null || printf '')
    case "$state" in
        T|t) return 0 ;;
    esac
    return 1
}

# Sondea el estado del PID 1 durante unos segundos (la señal es asíncrona).
wait_pid1_stopped() {
    attempts=0
    while [ "$attempts" -lt 6 ]; do
        if pid1_stopped; then
            return 0
        fi
        attempts=$((attempts + 1))
        sleep 1
    done
    return 1
}

heartbeat_mtime() {
    worker_exec python -c 'import os
from app.workers.heartbeat import heartbeat_path
print(int(os.stat(heartbeat_path()).st_mtime))'
}

cleanup() {
    status=$?
    trap - EXIT HUP INT TERM
    if [ "$LOOP_FROZEN" -eq 1 ]; then
        printf '\n== Restaurando el worker antes de salir (SIGCONT al PID 1)\n' >&2
        if worker_exec sh -c 'kill -CONT 1' >/dev/null 2>&1; then
            resumed=1
        elif docker kill --signal=CONT "$CONTAINER" >/dev/null 2>&1; then
            resumed=1
        else
            resumed=0
        fi
        if [ "$resumed" -eq 1 ] && ! pid1_stopped; then
            printf '   bucle reanudado\n' >&2
        else
            printf 'AVISO: no se pudo reanudar el bucle del worker; revisa el contenedor %s\n' "$CONTAINER" >&2
        fi
    fi
    if [ -n "$PROBE_ID" ]; then
        printf '\n== Borrando la sonda del outbox (id=%s marcador=%s)\n' \
            "$PROBE_ID" "$PROBE_MARKER" >&2
        if delete_output=$(worker_exec python -m scripts.outbox_probe delete \
            --id "$PROBE_ID" --marker "$PROBE_MARKER" 2>&1); then
            printf '   %s\n' "$delete_output" >&2
            PROBE_ID=""
        else
            delete_status=$?
            printf 'FAIL: no se pudo borrar la sonda id=%s marcador=%s: %s\n' \
                "$PROBE_ID" "$PROBE_MARKER" "$delete_output" >&2
            if [ "$delete_status" -eq 2 ]; then
                # El borrado tampoco es ejecutable (sin datos demo o fuera de
                # desarrollo/local): la verificación no se puede ejecutar. Si ya
                # había un fallo de comportamiento (1), ese veredicto prevalece.
                if [ "$status" -eq 0 ]; then
                    status=2
                fi
            else
                status=1
            fi
        fi
    fi
    exit "$status"
}
trap cleanup EXIT HUP INT TERM

# Espera a que el healthcheck reporte ``wanted`` dentro de ``timeout`` segundos.
# Deja el tiempo transcurrido en ``WAIT_ELAPSED`` y devuelve 0 o 1.
wait_for_status() {
    wanted=$1
    timeout=$2
    step=$3
    WAIT_ELAPSED=0
    started=$(now_seconds)
    while :; do
        elapsed=$(( $(now_seconds) - started ))
        WAIT_ELAPSED=$elapsed
        current=$(health_status)
        progress "[${elapsed}s] $step: $current"
        if [ "$current" = "$wanted" ]; then
            return 0
        fi
        if [ "$current" = missing ]; then
            fail "$step: el contenedor $CONTAINER desapareció"
        fi
        container_running || fail "$step: el contenedor $CONTAINER ya no está en ejecución"
        if [ "$elapsed" -ge "$timeout" ]; then
            printf '   último estado: %s\n' "$current" >&2
            return 1
        fi
        sleep "$WORKER_HEALTH_POLL_INTERVAL"
    done
}

info "Comprobando Docker y el worker"
progress "docker: $(docker --version 2>/dev/null || printf 'disponible')"
progress "destino: $WORKER_TARGET"
progress "contenedor: $CONTAINER"

info "Paso 0: comprobando el entorno del worker (sin escribir nada)"
if ! guard_output=$(worker_exec python -m scripts.outbox_probe guard 2>&1); then
    printf '   %s\n' "$guard_output" >&2
    not_executable "el worker no está en desarrollo/local (la sonda no se ejecuta ni escribe)"
fi
progress "sonda permitida: $guard_output"

initial_status=$(health_status)
if [ "$initial_status" = none ]; then
    fail "el contenedor $CONTAINER no tiene healthcheck; no se puede verificar la transición"
fi
if [ "$initial_status" = missing ]; then
    fail "el contenedor $CONTAINER no existe"
fi
container_running || fail "el contenedor $CONTAINER no está en ejecución"

info "Paso 1: esperando el estado sano inicial (máximo ${WORKER_HEALTH_READY_TIMEOUT}s)"
if ! wait_for_status healthy "$WORKER_HEALTH_READY_TIMEOUT" "estado inicial"; then
    fail "no se alcanzó healthy en ${WORKER_HEALTH_READY_TIMEOUT}s (paso 1)"
fi
ready_elapsed=$WAIT_ELAPSED
progress "sano tras ${ready_elapsed}s"
ready_elapsed_saved=$ready_elapsed

snapshot_before=$(container_snapshot)
mtime_before=$(heartbeat_mtime || printf '')

info "Paso 2: congelando el proceso del bucle (SIGSTOP al PID 1)"
worker_exec sh -c 'kill -STOP 1'
LOOP_FROZEN=1
if wait_pid1_stopped; then
    progress "PID 1 detenido por señal (State: T)"
else
    # El PID 1 de un namespace de PID ignora las señales de kernel (SIGSTOP y
    # SIGKILL) enviadas desde su propio namespace. Se envía desde el host: sigue
    # siendo SIGSTOP al PID 1, no una pausa del contenedor, así que el proceso
    # del healthcheck continúa y la transición es observable.
    progress "SIGSTOP desde dentro del contenedor no detuvo el PID 1; se envía desde el host"
    docker kill --signal=STOP "$CONTAINER" >/dev/null
    wait_pid1_stopped || fail "no se pudo congelar el PID 1 del contenedor $CONTAINER"
    progress "PID 1 detenido por señal (State: T, sin pausar el contenedor)"
fi
frozen_at=$(now_seconds)

info "Paso 3: esperando la transición a unhealthy (máximo ${WORKER_HEALTH_UNHEALTHY_TIMEOUT}s)"
if ! wait_for_status unhealthy "$WORKER_HEALTH_UNHEALTHY_TIMEOUT" "congelado"; then
    fail "no se observó unhealthy en ${WORKER_HEALTH_UNHEALTHY_TIMEOUT}s con el bucle congelado (paso 3)"
fi
unhealthy_elapsed=$WAIT_ELAPSED
progress "insano tras ${unhealthy_elapsed}s desde la congelación"

info "Paso 4: reanudando el bucle (SIGCONT al PID 1)"
worker_exec sh -c 'kill -CONT 1'
if pid1_stopped; then
    docker kill --signal=CONT "$CONTAINER" >/dev/null
    pid1_stopped && fail "el PID 1 sigue detenido tras SIGCONT"
fi
LOOP_FROZEN=0
progress "PID 1 en ejecución"

info "Paso 5: esperando la vuelta a healthy (máximo ${WORKER_HEALTH_RECOVERY_TIMEOUT}s)"
if ! wait_for_status healthy "$WORKER_HEALTH_RECOVERY_TIMEOUT" "reanudado"; then
    fail "no se recuperó a healthy en ${WORKER_HEALTH_RECOVERY_TIMEOUT}s (paso 5)"
fi
recovered_elapsed=$WAIT_ELAPSED
progress "sano tras ${recovered_elapsed}s desde la reanudación"

info "Paso 6: comprobando que la recuperación no reinició el contenedor"
snapshot_after=$(container_snapshot)
if [ "$snapshot_before" != "$snapshot_after" ]; then
    fail "el contenedor se reinició durante la verificación ($snapshot_before -> $snapshot_after)"
fi
progress "sin reinicio: $snapshot_after"

if [ -n "$mtime_before" ]; then
    mtime_after=$(heartbeat_mtime) || fail "no se pudo leer el latido tras la recuperación"
    if [ "$mtime_after" -le "$mtime_before" ]; then
        fail "el latido no avanzó tras la recuperación ($mtime_before -> $mtime_after)"
    fi
    progress "el bucle completó una vuelta tras la recuperación (latido $mtime_before -> $mtime_after)"
fi

info "Paso 7: sonda de outbox procesada por el worker (máximo ${WORKER_PROBE_TIMEOUT}s)"
PROBE_MARKER="worker-probe-$(date +%s)-$$-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \r\n')"
probe_started=$(now_seconds)
if insert_output=$(worker_exec python -m scripts.outbox_probe insert --marker "$PROBE_MARKER" 2>&1); then
    insert_status=0
else
    insert_status=$?
fi
if [ "$insert_status" -eq 2 ]; then
    # Sin datos demo (usuario/organización demo ausentes o propietario sin
    # membresía activa) la sonda no se escribe: no es un fallo de comportamiento.
    printf '   %s\n' "$insert_output" >&2
    not_executable "datos demo ausentes en el worker (organización y propietario demo, o su membresía activa); la sonda no se escribió (paso 7)"
fi
if [ "$insert_status" -ne 0 ]; then
    fail "no se pudo insertar la sonda (paso 7): $insert_output"
fi
PROBE_ID=$(printf '%s' "$insert_output" | awk '{print $1}')
if [ -z "$PROBE_ID" ]; then
    fail "la sonda no devolvió su identificador (paso 7): $insert_output"
fi
progress "sonda insertada: id=$PROBE_ID marcador=$PROBE_MARKER"
probe_deadline=$(( $(now_seconds) + WORKER_PROBE_TIMEOUT ))
while :; do
    probe_elapsed=$(( $(now_seconds) - probe_started ))
    if probe_output=$(worker_exec python -m scripts.outbox_probe status \
        --id "$PROBE_ID" --marker "$PROBE_MARKER" 2>&1); then
        probe_status=0
    else
        probe_status=$?
    fi
    probe_state=$(printf '%s\n' "$probe_output" | sed -n '1p' | cut -d' ' -f1)
    case "$probe_state" in
        status=processed)
            progress "[${probe_elapsed}s] procesada: $probe_output"
            break
            ;;
        status=failed)
            fail "la sonda agotó sus reintentos (paso 7): $probe_output"
            ;;
        status=retrying)
            progress "[${probe_elapsed}s] sigue esperando: $probe_output"
            ;;
        status=missing)
            fail "la sonda desapareció de la cola (paso 7): id=$PROBE_ID marcador=$PROBE_MARKER"
            ;;
        *)
            if [ "$probe_status" -eq 2 ]; then
                # La utilidad dejó de poder ejecutarse a mitad de la verificación
                # (por ejemplo, desaparecieron los datos demo): NO EJECUTABLE.
                printf '   %s\n' "$probe_output" >&2
                not_executable "la sonda dejó de ser ejecutable durante la verificación (paso 7)"
            fi
            fail "la sonda devolvió una salida inesperada (código $probe_status; paso 7): $probe_output"
            ;;
    esac
    if [ "$(now_seconds)" -ge "$probe_deadline" ]; then
        fail "la sonda no llegó a processed en ${WORKER_PROBE_TIMEOUT}s (paso 7): id=$PROBE_ID marcador=$PROBE_MARKER"
    fi
    sleep "$WORKER_PROBE_POLL_INTERVAL"
done
probe_elapsed=$(( $(now_seconds) - probe_started ))
progress "sonda procesada en ${probe_elapsed}s; el stream solo corrobora, la cola decide"

total_elapsed=$(( $(now_seconds) - frozen_at ))
info "Transición verificada: healthy -> unhealthy -> healthy"
progress "estado sano inicial: ${ready_elapsed_saved}s de espera"
progress "congelación -> unhealthy: ${unhealthy_elapsed}s"
progress "reanudación -> healthy: ${recovered_elapsed}s"
progress "tiempo total congelado/sondeando: ${total_elapsed}s"
progress "contenedor: $CONTAINER (sin reinicio)"
progress "sonda de outbox: id=$PROBE_ID marcador=$PROBE_MARKER (se borra al salir)"
printf '\nOK: el healthcheck del worker refleja el bucle detenido y su recuperación,\ny el worker procesó la sonda de outbox sin reiniciar el contenedor\n'
exit 0
