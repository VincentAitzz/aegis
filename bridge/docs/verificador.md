# El verificador

`bridge/app/verifier.py` convierte «el modelo dijo que lo hizo» en «lo comprobamos».

## Por qué existe

Un run de autopilot termina cuando el modelo deja de pedir tools, y eso no dice
nada sobre si el código funciona. Se midió algo peor: el modelo llegó a reportar
*«el archivo `verifier.py` ha sido creado y verificado exitosamente»* sin haber
escrito nunca nada (A-013). Su respuesta es una opinión; la del proceso que
ejecuta el comando es un dato.

## Qué hace

| Función | Para qué |
|---|---|
| `ejecutar(proyecto, what)` | corre el verificador declarado en `projects.py` y devuelve un `Verdict`. Nunca lanza: si no puede correr, lo dice en `Verdict.error` |
| `contar_problemas(texto)` | cuántas líneas de la salida parecen un problema |
| `firmas_de(texto)` | firmas de error normalizadas (sin rutas, números ni hashes), para comparar dos corridas |
| `delta(antes, despues)` | si este paso **mejoró** lo anterior o solo lo repitió |
| `es_repetido(historial, tool, args)` | si esta llamada idéntica ya falló dos veces |
| `gate(proyecto, what)` | la puerta que se le pasa a `run_autopilot(gate=...)` |

## La puerta

`run_autopilot` acepta `gate(step, tool, argumentos, resultado)`. La puerta:

- **solo juzga lo que el agente escribió** (`aegis_write_file`,
  `aegis_patch_file`). Verificar en cada lectura sería ruido, y `build_apk` ya se
  verifica a sí mismo;
- compara contra la corrida anterior, así que distingue *mejoró* de *volvió a
  hacerlo*;
- pone `stop: True` cuando el verificador sigue en rojo **y el número de
  problemas no baja**: a partir de ahí, seguir gastando pasos es peor que
  devolver el control.

Se activa por HTTP con `verificar: true`:

```bash
curl -X POST http://127.0.0.1:8000/autopilot \
  -H 'Content-Type: application/json' \
  -d '{"project":"aegis","verificar":true,"que":"check",
       "prompt":"..."}'
```

## Lo que devuelve un run

Además de la traza, cada run dice **por qué terminó**: `sin_tools`,
`respuesta_vacia`, `max_steps` o `puerta`. Sin ese dato, «agotó los pasos» se
confundía con «el modelo respondió» y el motivo real se perdía.
