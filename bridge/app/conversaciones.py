"""El dataset de conversaciones: lo que hace posible decidir sobre un modelo.

## Por qué existe

La pregunta «¿puedo entrenar un modelo propio?» **no tiene respuesta sin
datos**. Es lo que bloquea la decisión, y no la GPU:

    RTX 3050, 6 GB   ->  QLoRA de un 7B en 4 bits: ~5,0-5,5 GB. Cabe.
    throughput       ->  ~300-800 tok/s con gradient checkpointing
    3.000 ejemplos   ->  ~2 h por epoca

Todo eso es viable. Lo que **no** existe son los 3.000 ejemplos: hay ~100
utilizables entre 953 eventos terminales. Falta un factor de 20, y ese factor
se rellena con conversaciones, no con GPU.

Por eso cada turno de `/chat` se guarda. No para entrenar hoy, sino para que
la pregunta sea respondible dentro de unos meses en vez de dentro de siempre.

## Que guarda y que no

Se guarda el turno: lo que se pregunto, lo que respondio Aegis, que clase de
latencia lo atrovejo, que tools se llamaron y con que veredicto.

**No se guarda fuera de tu disco** (`data/` esta en `.gitignore`), y se borra
entero desde la app. Es la invariante «la memoria es tuya», sin excepciones
nuevas: un dataset de entrenamiento es memoria, y la memoria es tuya.

## La correccion es la parte que ensena

Un ejemplo positivo —«esto esta bien»— ensena poco: solo la forma. Lo que
ensena es el par **respuesta mala + motivo**, porque el motivo es lo que dice
que se esperaba.

Por eso `corregir()` guarda el motivo y no solo un booleano, y por eso
`resumen()` cuenta las rechazadas sin motivo: sirven para contar, no para
entrenar.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

VERDICTO = Literal["sin_etiquetar", "buena", "mala"]

#: Cuantas conversaciones se guardan antes de empezar a podar. Un JSONL que
#: crece sin techo acaba entrando en la copia de seguridad sin que nadie lo
#: decida, y un dataset que se traga el disco no es local-first: es local y
#: fragil. El podado es por antiguedad, no por tamano: lo reciente es lo que
#: se esta usando.
MAX_CONVERSACIONES = 5_000

#: Cada cuantas escrituras se comprueba el tope. Ver `anadir`.
_CADA_CUANTAS_SE_PODA = 100


def _ahora() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


@dataclass
class Conversacion:
    """Un turno de `/chat`, con su veredicto y, si alguien lo dijo, el motivo.

    `id` se genera al guardar y no al crear: asi un turno que nunca llego al
    disco no ocupa sitio y no deja huecos en la secuencia.
    """

    turno: str
    respuesta: str
    clase: str = ""
    modelo: str = ""
    ms: float = 0.0
    primer_token_ms: float = 0.0
    run_id: str | None = None
    tools: list[str] = field(default_factory=list)
    veredicto: str = "sin_etiquetar"
    motivo: str = ""
    corregido: str = ""
    evidencia: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=_ahora)
    id: str = ""

    def a_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "turno": self.turno,
            "respuesta": self.respuesta,
            "clase": self.clase,
            "modelo": self.modelo,
            "ms": round(self.ms, 2),
            "primer_token_ms": round(self.primer_token_ms, 2),
            "run_id": self.run_id,
            "tools": self.tools,
            "veredicto": self.veredicto,
            "motivo": self.motivo,
            "corregido": self.corregido,
            "evidencia": self.evidencia,
            "ts": self.ts,
        }

    @classmethod
    def desde_dict(cls, d: dict[str, Any]) -> "Conversacion":
        c = cls(turno=str(d.get("turno", "")), respuesta=str(d.get("respuesta", "")))
        for campo in ("clase", "modelo", "run_id", "veredicto", "motivo",
                      "corregido", "ts", "id"):
            if d.get(campo) is not None:
                setattr(c, campo, d[campo])
        for campo in ("ms", "primer_token_ms"):
            if isinstance(d.get(campo), (int, float)):
                setattr(c, campo, float(d[campo]))
        if isinstance(d.get("tools"), list):
            c.tools = [str(t) for t in d["tools"]]
        if isinstance(d.get("evidencia"), dict):
            c.evidencia = dict(d["evidencia"])
        return c


class Conversaciones:
    """Un JSONL append-only en `data/`.

    Append-only por dos razones.

    La primera es que **reescribir** el dataset en cada correccion significa
    que una interrupcion a mitad de escritura pierde la conversacion entera.
    Un `open(..., "a")` con una sola linea por escritura no pierde nada: o esta
    o no esta.

    La segunda es que **un dataset de entrenamiento solo crece**. Recortarlo es
    una decision, y las decisiones dejan rastro. La excepcion es el podado por
    antiguedad, que esta en `MAX_CONVERSACIONES` y es lo unico que borra.

    ## Por que no SQLite

    Porque esto se lee con `jq`, con `tail` y a ojo en un fichero de texto, que
    es como se van a revisar las correcciones. Una tabla que hay que consultar
    con un cliente no se revisa, y un dataset que no se revisa no se corrige.
    """

    def __init__(self, ruta: Path | str) -> None:
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._escritos = 0

    # -- escritura ---------------------------------------------------------
    def anadir(self, conv: Conversacion) -> Conversacion:
        conv.id = conv.id or uuid.uuid4().hex[:12]
        with self.ruta.open("a", encoding="utf-8") as f:
            f.write(json.dumps(conv.a_dict(), ensure_ascii=False) + "\n")
        self._escritos += 1
        # Podar en cada escritura era O(n²): cada `podar` relee el fichero
        # entero. Medido —5.003 turnos tardaban 65 s. Comprobando de 100 en
        # 100 escrituras, el tope se respeta con un margen de 100 turnos y la
        # escritura se vuelve constante.
        if self._escritos % _CADA_CUANTAS_SE_PODA == 0:
            self.podar()
        return conv

    def registrar_chat(self, turno: str, respuesta: str, *, clase: str = "",
                       modelo: str = "", ms: float = 0.0,
                       primer_token_ms: float = 0.0,
                       run_id: str | None = None,
                       tools: list[str] | None = None,
                       evidencia: dict[str, Any] | None = None) -> Conversacion:
        """Guarda un turno recien conversado. Lo llama `main` al cerrar `/chat`.

        El `run_id` solo viene si la respuesta fue T2: ahi si hubo un run con
        traza, y es lo que permite enlazar la conversacion con lo que paso de
        verdad. En T0 y T1 no hay run, y no se inventa uno.
        """
        return self.anadir(Conversacion(
            turno=turno, respuesta=respuesta, clase=clase, modelo=modelo,
            ms=ms, primer_token_ms=primer_token_ms, run_id=run_id,
            tools=list(tools or []), evidencia=dict(evidencia or {}),
        ))

    def corregir(self, conv_id: str, veredicto: str, motivo: str = "",
                 corregido: str = "") -> bool:
        """Pone veredicto a una conversacion. Devuelve si la encontro.

        Se **anade** una linea con la correccion en vez de reescribir la
        anterior. Dos razones: el motivo de por que algo se corrigio se pierde
        al reescribir (y es lo mas valioso que hay), y un append es atomico.

        Al leer, la ultima correccion de una id gana. Es append-only con
        resolucion, no un log que hay que reconstruir.
        """
        if veredicto not in ("buena", "mala", "sin_etiquetar"):
            raise ValueError(f"veredicto desconocido: {veredicto}")
        if not conv_id or conv_id not in self.leer():
            # Se comprueba antes de escribir. Una correccion sobre algo que no
            # existe no es informacion: es un error de quien la manda, y
            # guardarla haria que un `corregir` fallido pareciera tener efecto.
            return False
        self.anadir(Conversacion(
            turno="", respuesta="", veredicto=veredicto,
            motivo=motivo.strip(), corregido=corregido.strip(),
            id=conv_id, ts=_ahora()))
        return True

    def podar(self) -> int:
        """Quita las mas antiguas si se pasa del tope. Devuelve cuantas quito."""
        por_id = self.leer()
        turnos = [c for c in por_id.values() if c.turno]
        if len(turnos) <= MAX_CONVERSACIONES:
            return 0
        turnos.sort(key=lambda c: c.ts)
        antiguas = {c.id for c in turnos[:-MAX_CONVERSACIONES]}
        # Solo se podan turnos. Una correccion sin turno es informacion que no
        # sale en ninguna parte y por tanto no se puede perder.
        lineas = [json.dumps(c.a_dict(), ensure_ascii=False)
                  for c in por_id.values()
                  if c.turno and c.id not in antiguas]
        self.ruta.write_text("\n".join(lineas) + ("\n" if lineas else ""),
                             encoding="utf-8")
        return len(antiguas)

    # -- lectura -----------------------------------------------------------
    def leer_crudas(self) -> list[dict[str, Any]]:
        if not self.ruta.exists():
            return []
        filas = []
        for linea in self.ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea:
                continue
            try:
                filas.append(json.loads(linea))
            except ValueError:
                # Una linea corrupta no tumba el dataset entero. Pasa: perder
                # un turno es mejor que no poder corregir ninguno.
                continue
        return filas

    def leer(self) -> dict[str, Conversacion]:
        """Por id, con la ultima correccion aplicada."""
        por_id: dict[str, Conversacion] = {}
        for d in self.leer_crudas():
            c = Conversacion.desde_dict(d)
            if not c.id:
                continue
            previa = por_id.get(c.id)
            if previa is not None and previa.turno:
                # Es una correccion sobre un turno: se le aplica encima.
                c.turno = previa.turno
                c.respuesta = previa.respuesta
                c.clase = previa.clase
                c.modelo = previa.modelo
                c.ms = previa.ms
                c.primer_token_ms = previa.primer_token_ms
                c.run_id = previa.run_id
                c.tools = previa.tools
                c.evidencia = previa.evidencia or c.evidencia
                c.ts = previa.ts
                # El motivo y la correccion no se sobrescriben con vacio: la
                # ultima correccion gana en veredicto, pero el porque se
                # conserva. Es un registro de por que, y vaciarlo tira lo
                # unico que no se puede volver a obtener.
                c.motivo = c.motivo or previa.motivo
                c.corregido = c.corregido or previa.corregido
            por_id[c.id] = c
        return por_id

    def sin_etiquetar(self, limite: int = 50) -> list[Conversacion]:
        pend = [c for c in self.leer().values()
                if c.turno and c.veredicto == "sin_etiquetar"]
        pend.sort(key=lambda c: c.ts)
        return pend[:limite]

    def resumen(self) -> dict[str, Any]:
        """Lo que hay, y si sirve para algo.

        `malas_sin_motivo` es el numero que importa: **rechazadas sin motivo no
        se pueden corregir con un ejemplo**. Sirven para contar, no para
        entrenar.
        """
        por_id = self.leer()
        turnos = [c for c in por_id.values() if c.turno]
        malas = [c for c in turnos if c.veredicto == "mala"]
        return {
            "total": len(turnos),
            "buenas": sum(1 for c in turnos if c.veredicto == "buena"),
            "malas": len(malas),
            "sin_etiquetar": sum(1 for c in turnos
                                 if c.veredicto == "sin_etiquetar"),
            "malas_sin_motivo": sum(1 for c in malas if not c.motivo),
            "corregidas": sum(1 for c in turnos if c.corregido),
            "clases": _cuenta(c.clase for c in turnos),
            "primera": turnos[0].ts if turnos else "",
            "ultima": turnos[-1].ts if turnos else "",
        }

    # -- borrado -----------------------------------------------------------
    def borrar(self) -> int:
        """Vacia el dataset. Devuelve cuantas filas habia.

        Existe por la invariante «la memoria es tuya». Un dataset de
        entrenamiento sigue siendo memoria, asi que el boton de borrar es el
        mismo que el de la memoria, no una excepcion.
        """
        n = len(self.leer_crudas())
        if self.ruta.exists():
            self.ruta.unlink()
        return n


def _cuenta(valores: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in valores:
        if v:
            out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


_INSTANCIA: Conversaciones | None = None


def dataset(ruta: Path | str | None = None) -> Conversaciones:
    """La instancia del proceso, o una explicita para tests."""
    global _INSTANCIA
    if ruta is not None:
        return Conversaciones(ruta)
    if _INSTANCIA is None:
        from .config import get_settings
        _INSTANCIA = Conversaciones(
            Path(get_settings().log_dir).parent / "conversaciones.jsonl")
    return _INSTANCIA