"""Comparación de compatibilidad del contrato público v1 (spec 051, RF-006).

Funciones puras sobre dos documentos OpenAPI (referencia y actual). Un cambio es
compatible si un cliente escrito contra la referencia sigue funcionando:

- Entrada (parámetros): el actual debe aceptar todo lo que aceptaba la referencia.
- Salida (respuestas): el actual solo puede devolver lo que la referencia ya
  prometía, salvo campos nuevos no obligatorios.
"""

from __future__ import annotations

from typing import Any

Schema = dict[str, Any]
_MAX_DEPTH = 64


def incompatibilities(reference: Schema, current: Schema) -> list[str]:
    problems: list[str] = []
    current_paths = current.get("paths", {})
    for path, item in reference.get("paths", {}).items():
        for method, operation in item.items():
            where = f"{method.upper()} {path}"
            current_operation = current_paths.get(path, {}).get(method)
            if current_operation is None:
                problems.append(f"{where}: lectura eliminada")
                continue
            _compare_parameters(reference, operation, current, current_operation, where, problems)
            _compare_responses(reference, operation, current, current_operation, where, problems)
    return problems


def _deref(doc: Schema, schema: Schema) -> Schema:
    for _ in range(_MAX_DEPTH):
        ref = schema.get("$ref")
        if ref is None:
            return schema
        node: Any = doc
        for part in ref.removeprefix("#/").split("/"):
            node = node[part]
        schema = node
    raise ValueError("Referencia circular en el documento OpenAPI")


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def _enum(schema: Schema) -> list[Any] | None:
    if "const" in schema:
        return [schema["const"]]
    return schema.get("enum")


def _variants(doc: Schema, schema: Schema, depth: int = 0) -> dict[tuple[str, str], Schema]:
    if depth > _MAX_DEPTH:
        raise ValueError("Esquema demasiado anidado")
    schema = _deref(doc, schema)
    union = schema.get("anyOf") or schema.get("oneOf")
    if union:
        found: dict[tuple[str, str], Schema] = {}
        for sub in union:
            found.update(_variants(doc, sub, depth + 1))
        return found
    declared = schema.get("type")
    if declared is None:
        values = _enum(schema)
        if values:
            declared = sorted({_value_type(value) for value in values})
        elif "properties" in schema:
            declared = "object"
        else:
            return {("any", ""): schema}
    found = {}
    for kind in declared if isinstance(declared, list) else [declared]:
        if kind == "object":
            found[(kind, schema.get("title", ""))] = schema
        else:
            found[(kind, schema.get("format", ""))] = schema
    return found


def _label(key: tuple[str, str]) -> str:
    return f"{key[0]}:{key[1]}" if key[1] else key[0]


def _compare_parameters(
    ref_doc: Schema, ref_op: Schema, cur_doc: Schema, cur_op: Schema, where: str, problems: list[str]
) -> None:
    ref_params = {(p["in"], p["name"]): p for p in ref_op.get("parameters", [])}
    cur_params = {(p["in"], p["name"]): p for p in cur_op.get("parameters", [])}
    for key, cur in cur_params.items():
        name = f"{where}: parámetro {key[1]}"
        ref = ref_params.get(key)
        if ref is None:
            if cur.get("required"):
                problems.append(f"{name}: parámetro obligatorio nuevo")
            continue
        if cur.get("required") and not ref.get("required"):
            problems.append(f"{name}: pasa a ser obligatorio")
        if ref.get("schema", {}).get("default") != cur.get("schema", {}).get("default"):
            problems.append(f"{name}: cambia el valor por defecto")
        _compare_input(ref_doc, ref.get("schema", {}), cur_doc, cur.get("schema", {}), name, problems)
    for key in ref_params.keys() - cur_params.keys():
        problems.append(f"{where}: parámetro {key[1]}: eliminado")


def _compare_input(
    ref_doc: Schema, ref: Schema, cur_doc: Schema, cur: Schema, where: str, problems: list[str]
) -> None:
    ref_variants = _variants(ref_doc, ref)
    cur_variants = _variants(cur_doc, cur)
    if ("any", "") not in cur_variants:
        for key in ref_variants.keys() - cur_variants.keys():
            problems.append(f"{where}: deja de aceptar el tipo {_label(key)}")
    for key in ref_variants.keys() & cur_variants.keys():
        ref_schema, cur_schema = ref_variants[key], cur_variants[key]
        ref_enum, cur_enum = _enum(ref_schema), _enum(cur_schema)
        if cur_enum is not None and (ref_enum is None or not set(ref_enum) <= set(cur_enum)):
            problems.append(f"{where}: deja de aceptar valores")
        for bound, narrower in (("maximum", min), ("minimum", max)):
            if bound in cur_schema and (
                bound not in ref_schema
                or narrower(cur_schema[bound], ref_schema[bound]) != ref_schema[bound]
            ):
                problems.append(f"{where}: {bound} más restrictivo")


def _compare_responses(
    ref_doc: Schema, ref_op: Schema, cur_doc: Schema, cur_op: Schema, where: str, problems: list[str]
) -> None:
    cur_responses = cur_op.get("responses", {})
    for code, ref_response in ref_op.get("responses", {}).items():
        cur_response = cur_responses.get(code)
        if cur_response is None:
            problems.append(f"{where}: respuesta {code} eliminada")
            continue
        cur_content = cur_response.get("content", {})
        for media, ref_media in ref_response.get("content", {}).items():
            cur_media = cur_content.get(media)
            if cur_media is None:
                problems.append(f"{where}: respuesta {code} sin {media}")
                continue
            _compare_output(
                ref_doc, ref_media.get("schema", {}), cur_doc, cur_media.get("schema", {}),
                f"{where} → {code}", problems, 0,
            )


def _compare_output(
    ref_doc: Schema, ref: Schema, cur_doc: Schema, cur: Schema, where: str, problems: list[str],
    depth: int,
) -> None:
    if depth > _MAX_DEPTH:
        raise ValueError("Esquema demasiado anidado")
    ref_variants = _variants(ref_doc, ref)
    cur_variants = _variants(cur_doc, cur)
    if ("any", "") not in ref_variants:
        for key in cur_variants.keys() - ref_variants.keys():
            if key[0] == "null":
                problems.append(f"{where}: se vuelve anulable")
            else:
                problems.append(f"{where}: tipo nuevo {_label(key)}")
    for key in ref_variants.keys() & cur_variants.keys():
        ref_schema, cur_schema = ref_variants[key], cur_variants[key]
        if key[0] == "object":
            _compare_object(ref_doc, ref_schema, cur_doc, cur_schema, where, problems, depth)
        elif key[0] == "array":
            _compare_output(
                ref_doc, ref_schema.get("items", {}), cur_doc, cur_schema.get("items", {}),
                f"{where} → []", problems, depth + 1,
            )
        else:
            ref_enum, cur_enum = _enum(ref_schema), _enum(cur_schema)
            if ref_enum is not None and (cur_enum is None or not set(cur_enum) <= set(ref_enum)):
                problems.append(f"{where}: valores nuevos")


def _compare_object(
    ref_doc: Schema, ref: Schema, cur_doc: Schema, cur: Schema, where: str, problems: list[str],
    depth: int,
) -> None:
    ref_properties = ref.get("properties", {})
    cur_properties = cur.get("properties", {})
    ref_required = set(ref.get("required", []))
    cur_required = set(cur.get("required", []))
    for name, ref_property in ref_properties.items():
        field = f"{where} → {name}"
        if name not in cur_properties:
            problems.append(f"{field}: campo eliminado")
            continue
        if name in ref_required and name not in cur_required:
            problems.append(f"{field}: deja de ser obligatorio")
        _compare_output(ref_doc, ref_property, cur_doc, cur_properties[name], field, problems, depth + 1)
    for name in cur_properties.keys() - ref_properties.keys():
        if name in cur_required:
            problems.append(f"{where} → {name}: campo obligatorio nuevo")
