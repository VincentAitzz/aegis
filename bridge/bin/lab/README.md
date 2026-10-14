# Instrumentos de medición

Scripts que **miden**, no que operan: nada del operarlo los llama, y ninguno
necesita estar en el prompt de un modelo ni en un runbook de producción.

Se movieron aquí el 2026-10-04. Antes vivían mezclados en `bin/`, junto a
`probe-toolcall.sh` y `check-imports.py`, que sí son parte del operarlo: cualquiera
que abriera `bin/` para arrancar algo se tropezaba con cuatro scripts cuyo
propósito no era ése, y la pregunta «¿cuál de estos corre de verdad?» no tenía
respuesta en la propia carpeta.

- `medir-autopilot.py` — mide el bucle sobre un encargo real: tools ejecutadas,
  `fin` y latencia. **Arreglado el 2026-10-14**: desde el 2026-10-04 pedía
  `/autopilot/start` sin `X-Aegis-Token` y moría con `KeyError: 'run_id'`. La
  línea de abajo advierte de este caso exacto.
- `medir-prompt-ab.py` — **A/B de dos prompts, alternando**, levantando un
  segundo proceso del bridge que se parchea a sí mismo. No toca el código de
  producción. Es el instrumento detrás de `docs/medidas.md` §4.
- `measure-models.py` — compara modelos del mismo encargo.

> **Un instrumento que mide contra un contrato que ya no está no mide.** Eso le
> pasó a `medir-autopilot.py` durante diez días sin que nadie lo notara, porque
> fallaba en vez de mentir. Los instrumentos se ejecutan de vez en cuando; uno
> que lleva semanas sin probarse está sin probar, no «funcionando».

> `medir-hermes.py` se borró en la Fase 1 (2026-10-04): comparaba los dos motores
> sobre el mismo encargo, y ya solo había uno. Antes de esto ya estaba roto —
> llamaba a `GET /tasks/{id}`, ruta que nunca existió, así que su último caller era
> un 404 que él leía como estado del run. Un instrumento que mide contra un
> contrato que ya no está no mide: da un número.
- `derivar-ficha.py` — genera una ficha a partir del repo, para arrancar de cero.

Un instrumento que no se usa también es código que se pudre. Si uno vuelve a
servir, se queda aquí y se dice por qué.

Y el peor caso de un instrumento es el que **parece** que mide: `medir-hermes.py`
seguía en la carpeta seis meses después de que su ruta desapareciera, porque
borrarlo no era urgente y nadie se acordaba de que estaba ahí. Un script de
medición que ejecuta contra un contrato retirado no es ruido: es un número falso
con la misma pinta que un número bueno.
