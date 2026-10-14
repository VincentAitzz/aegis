# Hardware de referencia

Aegis está diseñado alrededor de una restricción: **un modelo de 7 GB en una GPU
de 6 GB**. Casi todo lo raro que hace este repo —el autopilot, el camino rápido
con un modelo pequeño, el recorte del prompt, el veredicto desde la traza— sale
de que esa máquina existe y no se puede subir de gama sin cambiar el diseño.

Por eso este documento da números, no ejemplos.

## La máquina de referencia

Medida el 2026-10-13 con `lscpu`, `free`, `nvidia-smi` y `df`. No es un entorno
de prueba: es un portátil de uso diario, con la batería y el trackpad puestos.

| | |
|---|---|
| **SO** | CachyOS Linux (Arch), kernel `7.2.9-1-cachyos` |
| **CPU** | Intel Core i5-12450HX — 6 núcleos de rendimiento + 4 de eficiencia, 12 hilos, 4,40 GHz de tope |
| **RAM** | 15 GiB |
| **GPU** | NVIDIA GeForce RTX 3050 6 GB Laptop GPU (6144 MiB), driver 615.71.09 |
| **Disco** | NVMe 238 GB |

## Qué cabe, y qué no

La cuenta no es «¿cabe el modelo?». Es **pesos + KV cache**, y el KV cache a
64 000 de contexto es lo que se come la VRAM:

| Componente | Tamaño |
|---|---|
| `qwen2.5-coder:7b` Q4_K_M | 4,7 GB |
| KV cache a `num_ctx=64000` | ≈ 3,6 GB (RAM) |
| `nomic-embed-text` (embeddings de la memoria) | 274 MB |

**Un 14b a 64k no entra**: 9 GB de pesos más unos 12 GB de KV son 21 GB, contra
los 6 GB de la tarjeta. Está documentado como ruta a hardware futuro en
`docs/architecture.md`, no como algo que funcione aquí.

Y hay un detalle que no es de tamaño sino de **prompt**: a 35 835 caracteres el
run tardaba 49,1 s, y a 22 847 tardaba 18,5 s. Un 36 % menos de prompt, un 62 %
menos de tiempo. El prompt es la palanca, no el modelo. Ver
`docs/decisiones/002-camino-rapido.md`.

## El mínimo y lo recomendado

| | VRAM | RAM | SO |
|---|---|---|---|
| **Mínimo** | 6 GB | 16 GB | Linux |
| **Cómodo** | 8–12 GB | 32 GB | Linux o macOS |
| **Holgado** | 16 GB+ | 32 GB+ | cualquiera |

- **Con 6 GB**: un solo modelo, `qwen2.5-coder:7b`, 64k de contexto. El
  orquestador y el worker son **roles lógicos** sobre el mismo modelo, no dos
  modelos cargados a la vez.
- **Con 8–12 GB**: `qwen2.5-coder:14b` Q4 a 32k, o el 7b a 64k con margen para
  dejar el modelo de embeddings residente. Empieza a poder cargarse T1 y T2 a
  la vez.
- **Con 16 GB+**: 14b a 64k, o embeddings más grandes, o dos modelos.

## Lo que hace falta aparte del modelo

Lo que no es GPU y sí es requisito:

- **Flutter 3.x + JDK + Android SDK**, solo para la app. El bridge funciona sin
  ninguno de los tres: `bridge/tests` pasa entero en una máquina sin toolchain
  móvil, y eso está comprobado en el CI.
- **RAM para ChromaDB y el grafo**: ~300 MB in-process cuando corre. La memoria
  degrada sola si falta Chroma —el grafo SQLite sigue dando contexto léxico—.
- **Disco**: el repo son unos pocos MB. Lo que crece son los logs
  (`bridge/data/logs/`) y la memoria, y ninguno de los dos se versiona.

## La prueba de que esto funciona

Medido en esta máquina exacta, y es la razón de que el diseño sea como es:

- **20/20 runs** con la tool realmente ejecutada y 0 falsos éxitos, en tres
  rondas.
- **3 episodios falsos en memoria bastan para hundir el tool-calling**: 0/8
  con ellos, 7/8 sin el bloque de memoria. Ablación n=8, intercalada.

Lo segundo es la que importa para quien vaya a modificarlo. El 7B no es un modelo
que falle por ser pequeño: es un modelo que **aprende de la memoria lo que ve en
ella**. Con episodios etiquetados como éxito que no lo eran, contesta sin llamar
a nada y aun así reporta que ha terminado. De ahí el invariante de
`app/veredicto.py`: *el veredicto sale de la traza, nunca del texto del modelo*.

## Lo que la máquina **no** cambia

Estos invariantes no dependen del hardware y no se relajan si el modelo es mejor:

1. **Nada irreversible sin tu OK.** Ninguna acción con consecuencia pasa sin
   aprobación de un solo uso.
2. **El veredicto sale de la traza.** Sin tool ejecutada, `sin_evidencia`.
3. **Los guardarraíles no se debilitan.** Si uno bloquea algo legítimo, se
   amplía; nunca se desactiva.
4. **Una corrección sin lección escrita es trabajo incompleto.**

Un modelo más grande hace que Aegis sea más útil. No hace que pueda saltarse la
puerta.