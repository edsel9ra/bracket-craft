#!/usr/bin/env python3
"""Filtro determinista de la auditoría del frontend (spec 003, RF-003).

Recibe por ``--input`` la salida JSON de
``pnpm audit --prod --json --audit-level low`` y por ``--pnpm-status`` el
estado de salida real de pnpm. Aplica una única política general, sin listas
de GHSA ni configuración persistente:

- código ``0``: no hay hallazgos accionables (``>= high`` con corrección
  publicada);
- código ``1``: al menos un hallazgo accionable;
- código ``2``: entrada, esquema, coherencia o estado de pnpm no
  interpretables.

La lógica de parsing y juicio es pura: no usa red, reloj, estado global ni el
sistema de archivos. Solo :func:`main` lee la entrada y escribe el resumen. El
filtro nunca escribe archivos.

Uso::

    python3 infra/scripts/audit_frontend.py --input <archivo|-> --pnpm-status <0|1>
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Severidades que reconoce la salida de pnpm.
KNOWN_SEVERITIES = frozenset({"info", "low", "moderate", "high", "critical"})
#: Severidades que se comparan con ``metadata.vulnerabilities``.
COUNTED_SEVERITIES = ("low", "moderate", "high", "critical")
#: Severidades que hacen fallar el filtro si tienen corrección publicada.
BLOCKING_SEVERITIES = frozenset({"high", "critical"})
#: Severidades que se listan aunque no bloqueen.
VISIBLE_SEVERITIES = frozenset({"high", "moderate", "low"})

_ABSENT = object()
_SEVERITY_ORDER = {"critical": 0, "high": 1, "moderate": 2, "low": 3, "info": 4}


@dataclass(frozen=True)
class Decision:
    """Resultado puro del filtro."""

    exit_code: int
    actionables: tuple[Mapping[str, Any], ...] = ()
    visible: tuple[Mapping[str, Any], ...] = ()
    info_count: int = 0
    dependencies: int | None = None
    errors: tuple[str, ...] = ()


def _is_int(value: Any) -> bool:
    """``bool`` es subclase de ``int``, pero no es un contador válido."""

    return isinstance(value, int) and not isinstance(value, bool)


def parse_report(raw: str) -> Mapping[str, Any]:
    """Convierte el texto de pnpm en un objeto JSON.

    Lanza ``ValueError`` si el JSON es inválido o si la raíz no es un objeto.
    """

    try:
        report = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("la entrada no es JSON válido") from error
    if not isinstance(report, Mapping):
        raise ValueError("la raíz del JSON no es un objeto")
    return report


def published_fix(advisory: Mapping[str, Any]) -> bool:
    """Indica si el advisory tiene al menos una versión corregida publicada."""

    patched = advisory.get("patched_versions")
    if not isinstance(patched, str) or not patched:
        return False
    return advisory.get("patched_versions_unpublished") is not True


def is_actionable(advisory: Mapping[str, Any]) -> bool:
    """Un hallazgo es accionable si es ``>= high`` y tiene corrección publicada."""

    return (
        advisory.get("severity") in BLOCKING_SEVERITIES
        and published_fix(advisory)
    )


def count_by_severity(
    advisories: Mapping[str, Mapping[str, Any]]
) -> dict[str, int]:
    """Cuenta entradas por severidad conocida."""

    counts = {severity: 0 for severity in KNOWN_SEVERITIES}
    for advisory in advisories.values():
        severity = advisory.get("severity")
        if severity in counts:
            counts[severity] += 1
    return counts


def validate_schema(report: Mapping[str, Any]) -> list[str]:
    """Valida la forma del JSON antes de emitir cualquier veredicto.

    ``advisories`` es obligatorio y debe ser un objeto: solo ``advisories: {}``
    representa «sin hallazgos». ``metadata`` y ``metadata.vulnerabilities``
    también son obligatorios. ``patched_versions`` ausente, ``null`` o cadena
    vacía no son errores de esquema.
    """

    errors: list[str] = []
    if not isinstance(report, Mapping):
        return ["la raíz del JSON debe ser un objeto"]

    advisories = report.get("advisories", _ABSENT)
    if advisories is _ABSENT:
        errors.append(
            "falta la clave obligatoria 'advisories'; solo 'advisories: {}' "
            "representa ausencia de hallazgos"
        )
    elif not isinstance(advisories, Mapping):
        errors.append("'advisories' debe ser un objeto")
    else:
        for key, advisory in advisories.items():
            label = str(key)
            if not isinstance(advisory, Mapping):
                errors.append(f"la entrada {label!r} de advisories debe ser un objeto")
                continue
            ghsa = advisory.get("github_advisory_id")
            if isinstance(ghsa, str) and ghsa:
                label = ghsa
            severity = advisory.get("severity")
            if not isinstance(severity, str) or severity not in KNOWN_SEVERITIES:
                errors.append(
                    f"advisory {label}: severidad desconocida o ausente"
                )
            if "patched_versions" in advisory:
                patched = advisory["patched_versions"]
                if patched is not None and not isinstance(patched, str):
                    errors.append(
                        f"advisory {label}: 'patched_versions' debe ser texto o null"
                    )

    metadata = report.get("metadata", _ABSENT)
    if metadata is _ABSENT:
        errors.append("falta la clave obligatoria 'metadata'")
    elif not isinstance(metadata, Mapping):
        errors.append("'metadata' debe ser un objeto")
    else:
        vulnerabilities = metadata.get("vulnerabilities", _ABSENT)
        if vulnerabilities is _ABSENT:
            errors.append("falta la clave obligatoria 'metadata.vulnerabilities'")
        elif not isinstance(vulnerabilities, Mapping):
            errors.append("'metadata.vulnerabilities' debe ser un objeto")
        else:
            for name, value in vulnerabilities.items():
                if not _is_int(value):
                    errors.append(
                        f"'metadata.vulnerabilities.{name}' debe ser un entero"
                    )
        if "dependencies" in metadata and not _is_int(metadata["dependencies"]):
            errors.append("'metadata.dependencies' debe ser un entero")

    return errors


def validate_metadata(
    advisories: Mapping[str, Mapping[str, Any]],
    metadata: Mapping[str, Any],
) -> list[str]:
    """Comprueba que ``advisories`` cuadre con ``metadata``.

    Las claves ausentes de ``metadata.vulnerabilities`` cuentan como cero.
    ``info`` no se exige en ``advisories`` porque ``--audit-level low`` lo
    excluye de la salida detallada; solo se registra su contador. Un
    ``metadata.dependencies`` igual a cero con advisories es incoherente.
    """

    vulnerabilities = metadata.get("vulnerabilities")
    if not isinstance(vulnerabilities, Mapping):
        return ["'metadata.vulnerabilities' debe ser un objeto"]

    errors: list[str] = []
    counts = count_by_severity(advisories)
    for severity in COUNTED_SEVERITIES:
        expected = vulnerabilities.get(severity, 0)
        actual = counts.get(severity, 0)
        if expected != actual:
            errors.append(
                "desajuste entre advisories y metadata.vulnerabilities para "
                f"{severity}: advisories={actual}, metadata={expected}"
            )

    dependencies = metadata.get("dependencies", _ABSENT)
    if dependencies is not _ABSENT and dependencies == 0 and advisories:
        errors.append(
            "metadata.dependencies es 0 pero 'advisories' tiene "
            f"{len(advisories)} entrada(s)"
        )
    return errors


def _advisory_sort_key(advisory: Mapping[str, Any]) -> tuple[int, str, str]:
    severity = advisory.get("severity")
    return (
        _SEVERITY_ORDER.get(severity, len(_SEVERITY_ORDER)),
        str(advisory.get("github_advisory_id") or ""),
        str(advisory.get("module_name") or ""),
    )


def decide(report: Mapping[str, Any], pnpm_status: Any) -> Decision:
    """Aplica esquema, coherencia y política de accionables.

    Es una función pura: recibe el reporte ya parseado y el estado de pnpm.
    Un estado distinto de 0 y 1 no se puede interpretar y devuelve código 2;
    el estado no decide el veredicto por sí mismo.
    """

    if not _is_int(pnpm_status) or pnpm_status not in (0, 1):
        return Decision(
            exit_code=2,
            errors=("estado de pnpm ausente o inválido; se esperaba 0 o 1",),
        )

    errors = validate_schema(report)
    if errors:
        return Decision(exit_code=2, errors=tuple(errors))

    advisories = report["advisories"]
    metadata = report["metadata"]
    errors = validate_metadata(advisories, metadata)
    if errors:
        return Decision(exit_code=2, errors=tuple(errors))

    vulnerabilities = metadata["vulnerabilities"]
    info_count = vulnerabilities.get("info", 0)
    dependencies = metadata.get("dependencies")

    actionables: list[Mapping[str, Any]] = []
    visible: list[Mapping[str, Any]] = []
    for advisory in advisories.values():
        if is_actionable(advisory):
            actionables.append(advisory)
        elif advisory.get("severity") in VISIBLE_SEVERITIES:
            visible.append(advisory)

    actionables.sort(key=_advisory_sort_key)
    visible.sort(key=_advisory_sort_key)

    return Decision(
        exit_code=1 if actionables else 0,
        actionables=tuple(actionables),
        visible=tuple(visible),
        info_count=info_count,
        dependencies=dependencies if _is_int(dependencies) else None,
    )


def _advisory_id(advisory: Mapping[str, Any]) -> str:
    ghsa = advisory.get("github_advisory_id")
    if isinstance(ghsa, str) and ghsa:
        return ghsa
    return "sin GHSA"


def _field(advisory: Mapping[str, Any], name: str) -> str:
    value = advisory.get(name)
    if isinstance(value, str) and value:
        return value
    return "desconocido"


def _render_actionable(advisory: Mapping[str, Any]) -> str:
    return (
        f"ACCIONABLE {_advisory_id(advisory)} "
        f"paquete={_field(advisory, 'module_name')} "
        f"severidad={_field(advisory, 'severity')} "
        f"versiones_afectadas={_field(advisory, 'vulnerable_versions')} "
        f"corregido_en={_field(advisory, 'patched_versions')}"
    )


def _render_visible(advisory: Mapping[str, Any]) -> str:
    if published_fix(advisory):
        motivo = "severidad por debajo del umbral"
    else:
        motivo = "sin corrección publicada"
    return (
        f"NO ACCIONABLE {_advisory_id(advisory)} "
        f"paquete={_field(advisory, 'module_name')} "
        f"severidad={_field(advisory, 'severity')} "
        f"versiones_afectadas={_field(advisory, 'vulnerable_versions')} "
        f"motivo={motivo}"
    )


def render_decision(decision: Decision) -> str:
    """Devuelve el resumen legible, sin rutas del sistema ni JSON crudo."""

    if decision.errors:
        lines = ["ERROR: la entrada de la auditoría no es válida:"]
        lines.extend(f"- {error}" for error in decision.errors)
        return "\n".join(lines)

    lines: list[str] = []
    if decision.actionables:
        lines.append(
            "Hallazgos accionables (>= high con corrección publicada): "
            f"{len(decision.actionables)}"
        )
        lines.extend(
            f"- {_render_actionable(advisory)}"
            for advisory in decision.actionables
        )
    else:
        lines.append(
            "Sin hallazgos accionables (>= high con corrección publicada)."
        )

    if decision.visible:
        lines.append(
            f"Hallazgos no accionables visibles: {len(decision.visible)}"
        )
        lines.extend(
            f"- {_render_visible(advisory)}" for advisory in decision.visible
        )
    else:
        lines.append("Sin hallazgos no accionables visibles.")

    if decision.dependencies is not None:
        lines.append(f"Dependencias auditadas: {decision.dependencies}")
    lines.append(f"Informativos contabilizados: {decision.info_count}")
    lines.append(
        "Resultado: FALLA" if decision.exit_code == 1 else "Resultado: OK"
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Filtra la salida JSON de 'pnpm audit --prod --json "
            "--audit-level low': falla solo ante hallazgos >= high con "
            "corrección publicada."
        )
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Ruta del JSON de pnpm audit; usa - para leer por stdin",
    )
    parser.add_argument(
        "--pnpm-status",
        required=True,
        type=int,
        dest="pnpm_status",
        help="Estado de salida real de pnpm audit (0 o 1)",
    )
    args = parser.parse_args(argv)

    try:
        if args.input == "-":
            raw = sys.stdin.read()
        else:
            raw = Path(args.input).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        print(
            "ERROR: no se pudo leer la entrada de pnpm audit",
            file=sys.stderr,
        )
        return 2

    try:
        report = parse_report(raw)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    decision = decide(report, args.pnpm_status)
    print(render_decision(decision))
    return decision.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
