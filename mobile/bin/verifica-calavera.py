#!/usr/bin/env python3
"""Comprueba que el arte sigue siendo **la misma calavera** que el JPG.

## Por qué un número y no un «lo he mirado»
Porque la generación pone el vocabulario real donde lo tenía la imagen, y eso es
una afirmación que se puede **medir**: se compara celda a celda dónde hay texto en
el arte y dónde lo había en el raster. Sin esto, «transcrito» y «parecido» son la
misma palabra.

## Qué mide
- **IoU de celdas**: intersección sobre unión, entre las celdas con texto del arte
  y las que tenían tinta en el JPG.
- **Cobertura**: cuántas celdas del original están cubiertas. Es el número que
  importa, porque el original manda.
- **Exceso**: cuántas celdas del arte caen donde el original no tenía nada. Un
  arte que cubre el 91 % del original pero se sale un 30 % se ve más lleno, y por
  arriba la calavera engorda.
- **Ancho por línea**: la serie de anchos es lo que dibuja la frente, las sien y
  los dientes. Se comparan las dos listas.

## Umbrales
Están puestos **bajo lo que se midió** a propósito. Un 0,80 de IoU es lo que da
hoy; si algún día baja a 0,70 el script avisa. Prefiere un umbral que se pueda
cumplir durante años a uno que obliga a reconstruir el arte cada vez que se toca
un parámetro.

    python3 mobile/bin/verifica-calavera.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
ORIGEN = RAIZ / "assets/brand/aegis_mark_source.jpg"
ARTE = RAIZ / "assets/brand/glifos/calavera_jazz.txt"
PGM = Path("/tmp/opencode/vga/o.pgm")

#: La rejilla que `extrae-calavera.py` ajustó contra la imagen. Si cambias una,
#: cambias las dos, o el check mide contra una rejilla que el arte no usa.
PITCH, FASE, AVANCE = 9, 2, 9.7

IOU_MIN = 0.70
COBERTURA_MIN = 0.85
EXCESO_MAX = 0.20


def leer_pgm(ruta: Path) -> np.ndarray:
    with open(ruta, "rb") as f:
        if f.readline().strip() != b"P5":
            raise SystemExit("no es un PGM")
        d = f.readline().split()
        w, h = int(d[0]), int(d[1])
        f.readline()
        return np.frombuffer(f.read(w * h), dtype=np.uint8).reshape(h, w)


def main() -> int:
    if not PGM.exists():
        raise SystemExit(
            f"Falta {PGM}. Genéralo con:\n"
            "  magick assets/brand/aegis_mark_source.jpg -colorspace Gray "
            "-depth 8 /tmp/opencode/vga/o.pgm"
        )

    img = leer_pgm(PGM)
    mascara = img > 45

    lineas = [l.rstrip("\n") for l in ARTE.read_text(encoding="utf-8").splitlines()
              if l and not l.startswith("#")]
    nl, nc = len(lineas), max(len(l) for l in lineas)

    # La línea 0 del arte es la **primera banda con tinta**, no la banda 0: entre
    # el borde superior de la imagen y el primer texto hay ~160 px de negro. Sin
    # esta corrección el check mide contra filas vacías y da 0 sin que se entienda
    # por qué.
    k0 = 0
    for k in range(mascara.shape[0] // PITCH):
        y0 = FASE + k * PITCH
        if y0 + PITCH > mascara.shape[0]:
            break
        if mascara[y0:y0 + PITCH].sum() > 0:
            k0 = k
            break

    original = np.zeros((nl, nc), dtype=bool)
    for i in range(nl):
        y0 = FASE + (k0 + i) * PITCH
        if y0 + PITCH > mascara.shape[0]:
            break
        banda = mascara[y0:y0 + PITCH]
        for c in range(nc):
            a = int(round(c * AVANCE))
            e = min(int(round((c + 1) * AVANCE)), banda.shape[1])
            if e > a:
                original[i, c] = banda[:, a:e].sum() > 0

    arte = np.zeros((nl, nc), dtype=bool)
    for k, l in enumerate(lineas):
        for c, ch in enumerate(l[:nc]):
            arte[k, c] = ch != " "

    inter = int((original & arte).sum())
    union = int((original | arte).sum())
    tot_o = int(original.sum())
    tot_a = int(arte.sum())
    iou = inter / max(1, union)
    cobertura = inter / max(1, tot_o)
    exceso = int((arte & ~original).sum()) / max(1, tot_a)

    print(f"arte      : {nl} lineas x {nc} columnas")
    print(f"original  : {tot_o} celdas con tinta")
    print(f"arte      : {tot_a} celdas con texto")
    print(f"interseccion: {inter}")
    print()
    print(f"IoU de celdas   : {iou:.3f}   (min {IOU_MIN})")
    print(f"cobertura       : {cobertura:.1%}   (min {COBERTURA_MIN:.0%})")
    print(f"exceso          : {exceso:.1%}   (max {EXCESO_MAX:.0%})")

    w_o = [int(original[i].sum()) for i in range(nl)]
    w_a = [int(arte[i].sum()) for i in range(nl)]
    print()
    print("ancho por linea — original / arte")
    for i in range(0, nl, max(1, nl // 10)):
        print(f"  {i:>3}  {w_o[i]:>3} / {w_a[i]:>3}")

    fallos = []
    if iou < IOU_MIN:
        fallos.append(f"IoU {iou:.3f} < {IOU_MIN}")
    if cobertura < COBERTURA_MIN:
        fallos.append(f"cobertura {cobertura:.1%} < {COBERTURA_MIN:.0%}")
    if exceso > EXCESO_MAX:
        fallos.append(f"exceso {exceso:.1%} > {EXCESO_MAX:.0%}")
    if fallos:
        print()
        print("FALLO: " + "; ".join(fallos))
        return 1
    print()
    print("OK: el arte es la misma calavera que la del JPG.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
