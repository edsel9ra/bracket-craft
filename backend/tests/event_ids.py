"""Identificadores de cliente con forma de UUID para las pruebas (spec 015).

Desde RF-015 el esquema exige que ``client_event_id`` tenga forma de UUID. Las
pruebas conservan sus etiquetas legibles y las convierten aquí: la derivación es
determinista, así que dos usos de la misma etiqueta siguen siendo el mismo
evento (idempotencia) y un fallo sigue siendo reconocible por su nombre.
"""

from uuid import NAMESPACE_URL, uuid5


def event_id(label: str) -> str:
    """Un `client_event_id` estable con forma de UUID a partir de una etiqueta."""
    return str(uuid5(NAMESPACE_URL, f"bracket-craft-test:{label}"))
