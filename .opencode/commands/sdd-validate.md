---
description: SDD · Valida la spec RF por RF (tests)
agent: build
---
Recorre specs/$1/spec.md requisito por requisito. Para cada RF indica qué test lo cubre y el resultado de ejecutarlo con los tests.

Si algún RF no está cubierto o falla, dilo claramente. NO arregles nada todavía. Después comprueba los criterios de finalización y dame un veredicto: ¿la spec está cumplida?