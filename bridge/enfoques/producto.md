# Fase: producto

`metodo.md` ya te pide seis cosas antes de construir, y van en **todos** los
runs: qué problema resuelve, para qué se usa, quién lo usa, cómo se sabrá que
funcionó, qué alternativas hubo, qué queda fuera.

Este enfoque **no repite ninguna**. Solo añade las tres cosas que ahí faltan, y
cierra las herramientas de escritura mientras decides.

## Lo único que `metodo.md` no pregunta

- **¿Es un problema tuyo o un problema de la herramienta?** La prueba: si esto no
  existiera, ¿qué harías distinto mañana? Si la respuesta es "nada", dilo antes
  de escribir. Mucho de lo que se construye es para que quede bien, y eso no
  resuelve nada.
- **¿Cuándo lo dejarías de usar?** Qué señal te haría apagarlo. Un objetivo sin
  criterio de abandono solo sabe crecer.
- **¿Hay algo más pequeño?** La respuesta honesta a veces es un script, o una
  app que ya existe, o esperar tres meses a que el modelo mejore. Eso no es un
  fracaso del plan: es el plan.

## Por qué esto cierra las herramientas

Porque una lista de preguntas en el prompt es una petición, y una petición al
modelo se cumple o no según el día. Mientras decides *qué problema resuelves*,
llamar a `aegis_write_file` es construir sin saber qué construyes.

Se sale pasandole nombre vacío a `usar_enfoque`, cuando ya está decidido.

## Y la pregunta que decide el resto

Antes de proponer nada: **¿esto ya estaba decidido?** Mira `docs/decisiones/`.
Re-litigar una decisión tomada es la forma más cara de no avanzar, porque pagas
la discusión entera otra vez.

Si esto cambia el producto y no solo cómo se construye, actualiza
`docs/vision.md` y añade la entrada a `docs/decisiones/`.

## Cómo sales

1. El problema, en una frase.
2. Cómo sabrás que funcionó, y su fecha.
3. **Qué tendría que pasar en el mundo para que esto no valiera la pena.** La
   misma prueba que pide `arquitectura.md`, pero aplicada al objetivo: casi todas
   las decisiones técnicas no fallan por malas, fallan por **innecesarias**.