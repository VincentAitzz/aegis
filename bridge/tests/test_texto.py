"""El repo está escrito en español: lo que se escapa de ese alfabeto se ve.

## Por qué esto es un test

Escribir prosa en un idioma que no es el mío se cuelan cosas raras: un kanji, un
cirílico, un ancho. Pasan desapercibidas en un commit y aparecen en `lessons/`,
que es justo el fichero que el agente se lee para corregir su forma de trabajar.

Ya ha pasado dos veces (ver A-027), y en los dos casos un `git grep` rápido lo
habría visto. Convertirlo en un test hace que lo vea **el commit**, no quien
revisa.

## Lo que sí se permite

Dos excepciones, y son intencionadas:

- `app/autopilot.py` y `tests/test_autopilot.py` llevan marcadores de llamada a
  tool en chino y en japonés: son lo que escribe el modelo de 7 GB cuando se le
  corta la llamada. Hay que buscarlos para repararlos, así que están en el código
  a propósito.

Este fichero los describe **con palabras**, no con los caracteres: si los
escribiera, el test se denunciaría a sí mismo y no valdría para nada.
- Los caracteres de dibujo de caja (`─│└├╔`) están en los diagramas de
  `AGENTS.md`, `README.md` y `docs/architecture.md`. Son diagramas, no ruido.
"""

import unittest
from pathlib import Path
import unicodedata

RAIZ = Path(__file__).resolve().parents[2]

#: No se revisan: binarios, descargas y directorios generados.
EXCLUIDOS_DIR = {
    ".git", "build", ".venv", "node_modules", "__pycache__", ".dart_tool",
    ".gradle", "data", "quarantine",
}
EXCLUIDOS_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svgz", ".apk", ".ttf",
    ".otf", ".gz", ".xz", ".zip", ".so", ".pyc",
}

#: (inicio, fin) de lo que no debería aparecer nunca en este repo.
RANGOS = {
    "han": ("\u3400", "\u9fff"),
    "hiragana": ("\u3040", "\u309f"),
    "katakana": ("\u30a0", "\u30ff"),
    "hangul": ("\uac00", "\ud7af"),
    "cirilico": ("\u0400", "\u04ff"),
    "griego": ("\u0370", "\u03ff"),
    "arabe": ("\u0600", "\u06ff"),
    "hebreo": ("\u0590", "\u05ff"),
    "devanagari": ("\u0900", "\u097f"),
    "ancho": ("\uff00", "\uffef"),
    "matematicas": ("\U0001d400", "\U0001d7ff"),
    # Invisibles y de control bidi: no se ven, pero rompen el texto al copiar.
    "invisible": ("\u200b", "\u200f"),
    "bidi": ("\u202a", "\u202e"),
}

#: Ficheros donde un alfabeto ajeno es el objetivo y no un error.
PERMITIDO = {
    "bridge/app/autopilot.py": "detecta los placeholders de tool en chino/japonés "
                               "que escribe el modelo 7B",
    "bridge/tests/test_autopilot.py": "prueba esos mismos placeholders",
}


def _es_binario(ruta: Path) -> bool:
    try:
        with ruta.open("rb") as fh:
            return b"\x00" in fh.read(4096)
    except OSError:
        return True


def _inculpado(relativo: str) -> str | None:
    """Motivo por el que el fichero está permitido, o None."""
    return PERMITIDO.get(relativo)


class TestAlfabetoDelRepo(unittest.TestCase):
    """Que el repo esté en el idioma que dice estar."""

    def _ficheros(self):
        for ruta in RAIZ.rglob("*"):
            if not ruta.is_file():
                continue
            if any(parte in EXCLUIDOS_DIR for parte in ruta.parts):
                continue
            if ruta.suffix.lower() in EXCLUIDOS_EXT:
                continue
            if _es_binario(ruta):
                continue
            yield ruta

    def test_no_hay_alfabetos_ajenos(self) -> None:
        """Ningún fichero escrito fuera de la lista permitida se sale de Latin."""
        culpados: list[str] = []
        for ruta in self._ficheros():
            relativo = str(ruta.relative_to(RAIZ))
            if _inculpado(relativo):
                continue
            try:
                texto = ruta.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for numero, linea in enumerate(texto.splitlines(), 1):
                for nombre, (ini, fin) in RANGOS.items():
                    for ch in linea:
                        if ini <= ch <= fin:
                            try:
                                nombre_ch = unicodedata.name(ch)
                            except ValueError:
                                nombre_ch = "?"
                            culpados.append(
                                f"{relativo}:{numero}  [{nombre}] {ch!r} "
                                f"{nombre_ch}\n      {linea.strip()[:100]}")
                            break
        self.assertEqual([], culpados,
                         "caracteres de otro alfabeto en ficheros que no están "
                         "permitidos:\n  " + "\n  ".join(culpados))

    def test_el_guardarraíl_se_mira_a_sí_mismo(self) -> None:
        """Si el test acepta los rangos porque los tiene escritos, es inútil.

        Los rangos se comparan carácter a carácter, así que este fichero no
        puede contener literalmente un kanji ni escribirlo. Se comprueba que la
        lista de excepciones sigue siendo la que creo, no la que se coló.
        """
        self.assertEqual(set(PERMITIDO), {
            "bridge/app/autopilot.py",
            "bridge/tests/test_autopilot.py",
        })
        for nombre in PERMITIDO:
            self.assertTrue(PERMITIDO[nombre], f"{nombre} sin motivo")


if __name__ == "__main__":
    unittest.main()