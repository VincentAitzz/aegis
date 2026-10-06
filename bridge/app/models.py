"""Esquemas Pydantic del API del bridge.

## Por qué este módulo ya no tiene los esquemas del API
Hasta la Fase 1 era el contrato del WebSocket: `WsMessageIn`, `EventOut`,
`TaskIn`, `TaskOut`, `TaskStatus`, `ApprovalIn`, `NotaIn`, `TareaIn` vivían aquí.
El WebSocket se fue en la Fase 1 (era el segundo motor de tools; ver
`docs/motores.md` §6 y el commit `2f1fccb`), y con él sus esquemas. Un esquema
sin ruta detrás no es un contrato, es una pista.

Y `NotaIn`/`TareaIn` estaban **duplicados**: aquí y en `main.py`. Dos
definiciones del mismo cuerpo de petición es una divergible esperando a
su fecha: la app manda un campo que una acepta y la otra no, y el 422 sale en
el móvil con un mensaje que no explica por qué.

La regla que queda, y que `main.py` cumple: **el esquema vive junto a la ruta
que lo usa**. Cuando un esquema lo usan dos rutas, se sube aquí. Hasta ahora
ninguno lo cumple las dos, así que aquí no hay nada.

`SteerIn` también tiene su sitio natural en este fichero (lo usan
`POST /autopilot/{run_id}/steer`), pero se deja en `main.py` de momento para no
mover más de lo necesario en esta fase.
"""

# Este módulo se mantiene por contrato (los imports lo referencian y
# `check-imports.py` lo verifica), pero no expone ningún esquema.
__all__: list[str] = []