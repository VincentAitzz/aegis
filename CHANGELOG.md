# Changelog

Formato inspirado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/),
con los commits de Git como fuente. El historial completo está en
`git log`; este fichero es para quien lee sin clonar.

## Sin versión todavía

El proyecto no tiene versión todavía, y eso es deliberado: aún no hay una API
pública cuya compatibilidad se pueda romper. La fecha es lo que importa.

## 2026-10 — Abrir a la comunidad

Lo que se añadió para que este repo pueda ser clonado y usado por alguien que no
es quien lo escribió:

- **Las rutas dejan de estar escritas a mano.** La raíz del repo se deriva de
  `bridge/app/entorno.py`; el toolchain (Flutter, JDK, SDK de Android) se busca en
  las variables de entorno, en el `PATH` y en las rutas estándar. Antes eran
  literales de una máquina concreta, así que el repo no arrancaba en ninguna otra.
- **El material personal sale del repo**, a `~/aegis-privado/`:
  `quien-eres.md`, las fichas de proyectos, el registro y las lecciones de otros
  proyectos. `.gitignore` los excluye y `quien-eres.ejemplo.md` y
  `registro/_plantilla.json` los sustituyen.
- **Los tests dejan de depender de la máquina de nadie.** 17 tests afirmaban
  cosas sobre proyectos que no existen fuera de un disco concreto. Ahora
  comprueban la regla con proyectos de mentira, y hay un test nuevo que comprueba
  que la suite pasa sin `bridge/.env`.
- **`infra/setup.sh`**: un comando para la puesta en marcha. Antes eran seis
  pasos manuales, uno de los cuales requería tener algo que quizá no tienes.
- **CI** con tres jobs: el bridge en Python 3.12 y 3.14 **sin toolchain móvil a
  propósito**, el móvil solo cuando el PR lo toca, e higiene del repo (secretos,
  licencia, y que el README no vuelva a documentar APIs muertas).
- **Documentación nueva**: `docs/hardware.md` con los números medidos de la
  máquina de referencia, `README.en.md`, `CONTRIBUTING.md`, `SECURITY.md`,
  `CODE_OF_CONDUCT.md` y `NOTICE.md`.
- **Licencia AGPL-3.0.** Hasta esta fecha no había ninguna, y sin licencia un
  repositorio público es, en la práctica, de todos los derechos reservados.
- **Historial reescrito** con `git-filter-repo` para quitar rutas, direcciones y
  nombres de la máquina original.

### Correcciones que salieron de hacer esto

Hacer el repo portable destapó fallos que en la máquina de quien lo escribió no
existían. No son detalles menores:

- **Sin `adb`, `subprocess.run([""])` lanzaba `PermissionError`, no
  `FileNotFoundError`.** El `except FileNotFoundError` natural no lo pillaba, y
  `dispositivos.dispositivos()` reventaba con un traceback que no mencionaba adb.
  Ahora hay `adb_ausente()`, que es además el texto único para el mismo problema.
- **El guardarraíl de sintaxis Dart no comprobaba que `dart` existiera**, y con
  `flutter_dir()` vacío construía la ruta `/dart`. Ahora degrada como el de
  TypeScript, que ya lo hacía bien: no bloquea, y lo dice en el log.
- **`build_apk` no distinguía «no tienes Flutter» de «el build falló»**: hacía
  `subprocess` sobre una ruta vacía. Ahora lo dice antes, con qué variable poner.
- **El registro de proyectos declaraba cuatro entradas más** con rutas e ids de
  Neon de una máquina concreta. Un registro que apunta a sitios que no existen
  hace creer a Aegis que puede operar algo que no.

## 2026-10 — El autopilot se queda solo

- Se borra el motor de conversación de Hermes entero: `POST /tasks`, el
  WebSocket `/ws`, `relay.py`, `hooks.py` y `graphiti.py`. No le quedaban
  llamadores —los runs de Hermes paran el 2026-10-03— y `docs/architecture.md`
  seguía documentándolos como API viva en quince sitios.
- **El veredicto de un run pasa a salir de la traza**, nunca de `final_text`.
  Vive en `app/veredicto.py`, y `run_autopilot` lo calcula en un envoltorio
  porque el bucle a secas tiene seis `return` y en cada uno eran seis copias de
  la misma regla.
- **Al prompt solo suben episodios `success` con tools nombradas.** Medido:
  tres episodios falsos bajaban el tool-calling de 7/8 a 0/8.
- **Reetiquetados los 133 runs del histórico** con la regla actual, porque
  `fin: sin_tools` con una tool ejecutada y una respuesta buena **es** un run
  terminado, y se contabilizaba como fracaso.

## 2026-09 — Empieza

- Bridge FastAPI, memoria episódica (Chroma + SQLite), telemetría JSONL.
- Registro único de proyectos con guardarraíles de escritura.
- Consola Flutter con tema, proyectos, aprobaciones y trazas.
- El hallazgo que lo ordena todo: un agente con memoria contaminada no llama a
  ninguna herramienta y aun así reporta éxito. De ahí que el veredicto salga de
  la traza.