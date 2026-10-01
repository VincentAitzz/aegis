---
kind: herramienta
---

# Ficha · aegis

## Qué es

La consola local de trabajo del freelance: un agente que vive en su propia laptop
y ejecuta sobre el workspace. Un cliente Flutter habla con un Bridge FastAPI, que
a su vez habla con Hermes y con los MCP `aegis-ops` / `aegis-memory`, sobre un
Ollama local. No es un servicio: son tres procesos que hay que levantar a mano.

- `bridge/` — API FastAPI, memoria, telemetría, los MCP y el autopilot.
- `mobile/` — cliente Flutter (`aegis_console`).
- `infra/` — scripts de arranque de Ollama, Hermes y la cola del móvil.
- `docs/` — arquitectura y runbook.

## Por qué existe

Para poder trabajar a distancia sobre varios sistemas sin depender de una nube
que pueda caerse. Todo lo que Aegis necesita para decidir está en disco: la
ficha de cada proyecto, sus lecciones, su memoria y la traza de cada run.

Existe porque el día 2026-09-30 se comprobó que un agente con memoria contaminada
no llama a ninguna herramienta y aun así reporta éxito. Esa clase de fallo —el
sistema mintiendo sobre sí mismo— es la que justifica que aquí importen tanto la
traza como el veredicto.

## Invariantes

- **Aegis no es punto único de falla.** Si la laptop se apaga, el negocio sigue.
  Nada de lo que un cliente necesita puede depender de estos procesos.
- **El veredicto de un run sale de la traza, nunca del texto del modelo.** Sin
  tool ejecutada el resultado es `sin_evidencia`. Medido: 3 episodios falsos
  bajaban el tool calling de 7/8 a 0/8 (A-016).
- **Los guardarraíles de `app/mcp_ops.py` no se debilitan.** Si uno bloquea algo
  legítimo, se amplía el guardarraíl; nunca se desactiva.
- **Los guardarraíles duros corren antes que los de trámite.** El escaneo de
  secretos va antes que la puerta de fichas, para que una ficha ausente nunca
  enmascare un secreto.
- **Producción jamás se toca desde el Bridge.**
- **Una corrección sin lección escrita es trabajo incompleto.** Si no está en
  `lessons/aegis.md`, el agente lo va a repetir.

## Cómo se verifica

```bash
cd bridge && .venv/bin/python -m unittest discover -s tests -q
cd bridge && bash bin/probe-toolcall.sh qwen2.5:7b     # capacidad de tool-calling
cd mobile  && flutter analyze && flutter test
```

`probe-toolcall.sh` mide una sola tool con un prompt mínimo: sirve para detectar
que el modelo **dejó** de emitir tool calls, y **no** para declarar que el flujo
real funciona. Eso se mide end-to-end (A-016).

## Qué no toca

- **No es la fuente de verdad del negocio.** El estado de clientes, dinero y
  plazos vive fuera de aquí. Aegis es vista y acelerador, no dependencia.
- **No manda nada a un cliente.** Redacta; el envío lo hace otro. Nunca fija
  precios ni habla con el cliente por su usuario (método, §identidad).
- **No despliega nada** ni levanta túneles o contenedores de preview.
- **No elige la base de datos.** Quien llama no elige proyecto, ni rama, ni host.
- **No guarda datos de cliente en su memoria.** La memoria es de trabajo del
  agente; los datos comerciales viven fuera (ver `fichas-privadas/`, fuera de git).