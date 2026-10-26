"""Contrato de error estable de la operación del partido (P5, RF-032).

La resolución no habilitada por la configuración efectiva de la fase se rechaza
igual al crear un segmento, al interrumpirlo y al cerrar el acta: **409** con
un ``detail`` común —una cadena que el cliente ya muestra como respaldo— y un
``code`` estable y aditivo. El manejador único vive en ``app/main.py``:
Starlette resuelve por MRO, así que las rutas solo lanzan la excepción.

La asistencia inválida (spec 015, RF-008) sigue el mismo patrón: el motor puro
del replay lanza su propio error de dominio y el cierre lo traduce a
:class:`AssistPlayerInvalid`, un **409** con ``detail`` de cadena y el ``code``
aditivo ``ASSIST_PLAYER_INVALID``.

La coherencia de la doble amarilla (spec 017, RF-006) añade el tercer código:
una roja marcada como ``double_yellow_red`` sin **exactamente dos** amarillas
previas del mismo jugador en el mismo partido es :class:`DoubleYellowInconsistent`,
un **409** con ``detail`` de cadena (el minuto, nunca un nombre) y el ``code``
aditivo ``DOUBLE_YELLOW_INCONSISTENT``. No hay un paso nuevo de validación
estructural ni una migración: lo decide el acta de la petición.

La spec 016 añade los tres códigos del walkover: el estado que no admite la
declaración (:class:`WalkoverStateNotAllowed`), el marcador informado que no
coincide con el derivado de ``walkover_score``
(:class:`WalkoverScoreMismatch`) y la pareja efectiva que no da la victoria al
ganador declarado (:class:`WalkoverConfigInconsistent`). Los tres son **409**
con ``detail`` de cadena y ``code`` aditivo. Los mensajes se construyen con
valores **del servidor** —el estado del partido y la pareja configurada—, nunca
con texto del cliente, y no llevan datos personales.
"""

from fastapi import HTTPException, status

RESOLUTION_NOT_ENABLED = "RESOLUTION_NOT_ENABLED"
ASSIST_PLAYER_INVALID = "ASSIST_PLAYER_INVALID"
DOUBLE_YELLOW_INCONSISTENT = "DOUBLE_YELLOW_INCONSISTENT"
WALKOVER_STATE_NOT_ALLOWED = "WALKOVER_STATE_NOT_ALLOWED"
WALKOVER_SCORE_MISMATCH = "WALKOVER_SCORE_MISMATCH"
WALKOVER_CONFIG_INCONSISTENT = "WALKOVER_CONFIG_INCONSISTENT"

# Texto único de los tres puntos. No nombra la resolución para que el mensaje
# sea el mismo en todos los casos ni se traduce en el servidor: el cliente usa
# ``code`` para mostrar el mensaje del idioma activo.
RESOLUTION_NOT_ENABLED_DETAIL = (
    "La resolución no está habilitada por la configuración de la fase"
)


class ResolutionNotEnabled(HTTPException):
    """409 de dominio con un motivo estable en ``code``."""

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail or RESOLUTION_NOT_ENABLED_DETAIL,
        )
        self.code = RESOLUTION_NOT_ENABLED


def resolution_not_enabled_body(exc: ResolutionNotEnabled) -> dict[str, str]:
    """Cuerpo del 409: ``detail`` sigue siendo una cadena y ``code`` se añade."""

    return {"detail": str(exc.detail), "code": exc.code}


# Texto por defecto del asistente inválido. No nombra jugadores: el motor puede
# aportar un detalle más concreto, pero ningún mensaje lleva datos personales.
ASSIST_PLAYER_INVALID_DETAIL = (
    "El asistente no pertenece al mismo equipo que el goleador o no está en "
    "campo en el minuto del gol"
)


class AssistPlayerInvalid(HTTPException):
    """409 de dominio del asistente con un motivo estable en ``code``.

    Lo lanza el servicio de cierre al traducir el ``ASSIST_PLAYER_INVALID`` del
    motor puro; el manejador único de ``app/main.py`` añade el ``code`` al
    ``detail`` de cadena (D-8).
    """

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail or ASSIST_PLAYER_INVALID_DETAIL,
        )
        self.code = ASSIST_PLAYER_INVALID


# Texto por defecto de la doble amarilla inconsistente (RF-006). El servicio
# añade el minuto de la roja; ningún mensaje nombra jugadores (RNF-002).
DOUBLE_YELLOW_INCONSISTENT_DETAIL = (
    "La roja por doble amarilla no tiene exactamente dos amarillas previas del "
    "mismo jugador"
)


class DoubleYellowInconsistent(HTTPException):
    """409 de dominio de la coherencia disciplinaria del acta (RF-006).

    Lo lanza el servicio de cierre en el paso 10 del orden, sobre los eventos de
    la **petición** y sin escribir nada; el manejador único de ``app/main.py``
    añade el ``code`` al ``detail`` de cadena (RF-010). Una roja directa no lo
    provoca y una segunda amarilla no deriva en roja (DU-10).
    """

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail or DOUBLE_YELLOW_INCONSISTENT_DETAIL,
        )
        self.code = DOUBLE_YELLOW_INCONSISTENT


# Texto por defecto del estado que no admite un walkover (RF-001). El servicio
# añade el estado leído del servidor; ningún texto viene del cliente.
WALKOVER_STATE_NOT_ALLOWED_DETAIL = (
    "El estado del partido no admite la declaración de un walkover"
)

# Texto por defecto del marcador informado que no coincide con el derivado
# (RF-005). El servicio añade la pareja efectiva, que sale de ``rules_config``.
WALKOVER_SCORE_MISMATCH_DETAIL = (
    "El marcador de walkover informado no coincide con la configuración"
)

# Texto por defecto de la pareja efectiva que no da la victoria al ganador
# declarado (RF-008). Nombra la salida documentada: la resolución administrativa.
WALKOVER_CONFIG_INCONSISTENT_DETAIL = (
    "El marcador de walkover configurado no da la victoria al ganador "
    "declarado; declara el resultado como resolución administrativa"
)


class WalkoverStateNotAllowed(HTTPException):
    """409 de dominio del estado del partido para declarar un walkover (RF-001).

    ``match_status`` es el estado **leído del servidor** —``finished``,
    ``cancelled``, ``administrative_resolution`` o ``suspended``— y solo se
    nombra en el mensaje del idioma del servidor: el cliente usa ``code``. No
    es una transición de estado ni un texto del cliente.
    """

    def __init__(self, match_status: str | None = None) -> None:
        if match_status:
            detail = (
                f"El estado «{match_status}» no admite la declaración de un "
                "walkover"
            )
        else:
            detail = WALKOVER_STATE_NOT_ALLOWED_DETAIL
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)
        self.code = WALKOVER_STATE_NOT_ALLOWED


class WalkoverScoreMismatch(HTTPException):
    """409 de dominio del marcador informado frente al derivado (RF-005).

    Lo lanza la rama del cierre cuando el cliente informa un marcador que no es
    la pareja efectiva de ``walkover_score``; la pareja que se nombra es la
    **configurada**, nunca los valores enviados.
    """

    def __init__(self, winner: int | None = None, loser: int | None = None) -> None:
        if winner is not None and loser is not None:
            detail = (
                "El marcador de walkover informado no coincide con la "
                f"configuración ({winner}-{loser})"
            )
        else:
            detail = WALKOVER_SCORE_MISMATCH_DETAIL
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)
        self.code = WALKOVER_SCORE_MISMATCH


class WalkoverConfigInconsistent(HTTPException):
    """409 de dominio de la pareja efectiva incoherente (RF-008, D-5).

    Una versión publicada antes de D-3 puede tener ``winner <= loser``. Sin la
    guarda el acta escribiría un resultado cuya clasificación daría la victoria
    al otro equipo, así que el cierre se rechaza y se documenta la vía
    administrativa en lugar de reescribir la configuración publicada.
    """

    def __init__(self, winner: int | None = None, loser: int | None = None) -> None:
        if winner is not None and loser is not None:
            detail = (
                f"El marcador de walkover configurado ({winner}-{loser}) no da "
                "la victoria al ganador declarado; declara el resultado como "
                "resolución administrativa"
            )
        else:
            detail = WALKOVER_CONFIG_INCONSISTENT_DETAIL
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)
        self.code = WALKOVER_CONFIG_INCONSISTENT

