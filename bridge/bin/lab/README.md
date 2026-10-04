# Instrumentos de medición

Scripts que **miden**, no que operan: nada del operarlo los llama, y ninguno
necesita estar en el prompt de un modelo ni en un runbook de producción.

Se movieron aquí el 2026-10-04. Antes vivían mezclados en `bin/`, junto a
`probe-toolcall.sh` y `check-imports.py`, que sí son parte del operarlo: cualquiera
que abriera `bin/` para arrancar algo se tropezaba con cuatro scripts cuyo
propósito no era ése, y la pregunta «¿cuál de estos corre de verdad?» no tenía
respuesta en la propia carpeta.

- `medir-autopilot.py`, `medir-hermes.py` — comparan motores sobre el mismo encargo.
- `measure-models.py` — compara modelos del mismo encargo.
- `derivar-ficha.py` — genera una ficha a partir del repo, para arrancar de cero.

Un instrumento que no se usa también es código que se pudre. Si uno vuelve a
servir, se queda aquí y se dice por qué.
