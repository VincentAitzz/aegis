#!/usr/bin/env python3
"""La calavera: estructura sacada del JPG, contenido del vocabulario real.

## Qué es esto y qué no es
El JPG original (`assets/brand/aegis_mark_source.jpg`) es una captura de una
calavera hecha de texto, renderizada a **9,3 × 8,2 px por carácter**. A esa
resolución un `O` y un `0` ocupan los mismos píxeles, y `m` y `nn` también: no hay
ningún método —ni automático ni a ojo— que recupere el texto exacto. Se comprobó:
agrupando las celdas por forma hay 2480 grupos distintos para 3033 celdas, o sea
que **casi ninguna celda se parece a otra**.

Por eso esto **no** es una transcripción, y conviene decirlo claro:

- **La estructura es exacta y viene del raster**: cuántas líneas hay, dónde
  empieza y acaba cada una, y cuánta tinta tiene cada celda. Eso sale de medir la
  imagen, no de mirar.
- **El contenido es real pero colocado**: se rellena cada línea con el
  vocabulario de verdad del dibujo —los títulos, las fechas, `PIANOCONCERTO`,
  `THEMERCHANTOFVENICE`, `STRINGQUARTET`— para que la masa de texto caiga donde
  caía. No es tu artículo exacto; es tu material con la misma silueta.

Lo que se conserva, que es lo que el ojo lee: el número de líneas, la anchura de
cada una, la frente, la sien, las cuencas, los dientes y el borde rasgado.

## Por qué no se hace esto en Dart
Porque la rejilla sale de medir píxeles del JPG, y medir píxeles en un móvil
sería absurdo. Esto corre una vez, en la máquina, y deja un fichero de texto que
ya es fuente de verdad.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
ORIGEN = RAIZ / "assets/brand/aegis_mark_source.jpg"
SALIDA = RAIZ / "assets/brand/glifos/calavera_jazz.txt"
# El mismo arte sin la cabecera de comentarios, para el pipeline de marca.
SALIDA_ARTE = RAIZ / "assets/brand/glifos/calavera_jazz.arte.txt"
# La forma sola, en bloques. La consume el pipeline de marca.
SALIDA_SILUETA = RAIZ / "assets/brand/glifos/calavera_silueta.txt"
#: El mismo arte en Dart. **Generado**, no escrito a mano: el texto sigue siendo
#: la fuente, y esto es solo la forma que Flutter puede pintar en el primer frame.
#:
#: ## Por qué un `const` y no un asset
#: Cargar el `.txt` con `rootBundle` es asíncrono, y el arranque necesita pintar
#: en el **primer** frame: con una espera, la calavera aparece un destello tarde
#: o no aparece, y un splash que aparece tarde es un splash que parpadea. El
#: `.txt` pesa 4 KB y no va al APK; esto sí, y son 4 KB.
DART = RAIZ / "lib/core/widgets/glifos/calavera_jazz.dart"
# La misma silueta, en Dart, para el pintor de la app.
DART_SILUETA = RAIZ / "lib/core/widgets/glifos/calavera_silueta.dart"
PGM = Path("/tmp/opencode/vga/orig.pgm")

#: Rejilla del raster. **Ajustada contra la imagen**, no elegida a ojo: se
#: prueba eladvance en pasos de 0,1 px y se queda con el que más celdas del
#: original cubre. Con 9,35 —que era lo que sugería la autocorrelación— el
#: arte salía un 31 % más ancho que el dibujo; con 9,7, no.
#:
#: El ajuste importa por una razón concreta: la deriva. Si el avance real es
#: 9,7 y tú pones 9,35, al final de una línea de 68 caracteres llevas casi 25 px
#: de desfase, y tus celdas caen **entre** dos caracteres. El resultado se ve
#: entero y por dentro está corrido.
PITCH_FILA = 9
FASE = 2
AVANCE = 9.7
COL_INI = 53
COL_FIN = 688

#: El vocabulario del dibujo, tal y como se lee en la imagen. Ordenado de más
#: largo a más corto para que el relleno siga el ritmo de las líneas anchas.
Vocabulario = [
    # Títulos e instituciones, que son el relleno grueso del centro
    "THEMERCHANTOFVENICE(1968-1982)",
    "PIANOCONCERTONO.1(1957)SONATAFORPIANO(1958)",
    "SONATAFORGLARINETANDPIANO,OP.1(1959)",
    "STRINGQUARTETNO.2INAMAJOR,OP.5(1973-1975)",
    "PIANOCONCERTONO.2,OP.4(1966-1971)",
    "INVENTIONSFORPIANO,OP.2(1961-1962)",
    "STRINGQUARTETNO.1INAMAJOR,OP.3(1969-1970)",
    "PIANOCONCERTONO.1(1957)SONATAFORGLARINET",
    "SONATAFORPIANO(1958)SONATAFORGLARINET",
    "OP.3(1969-1970)PIANOCONCERTONO.2",
    "OP.5(1973-1975)OPERA,THEMERCHANT",
    "PIANOCONCERTONO.2,OP.4(1966-1971)STR",
    "INVENTIONSFORGLARINETANDPIANO",
    "THEMERCHANTOFVENICE(1968-1982)PIANO",
    "STRINGQUARTETNO.1INAMAJOR,OP.3",
    "PIANOCONCERTONO.1(1957)SONATA",
    "SONATAFORGLARINETANDPIANO,OP.1",
    "PIANOCONCERTONO.2,OP.4(1966-1971)",
    "OPERA,THEMERCHANTOFVENMICE",
    "PIANOCONCERTO(1957)SONATAFOR",
    "SONATAFORGLARINETANDPIANO",
    "STRINGQUARTETNO.2INAMAJOR",
    "INVENTIONSFORPIANO,OP.2",
    "PIANOCONCERTONO.1(1957)",
    "STRINGQUARTETNO.1INAMAJOR",
    "PIANOCONCERTONO.2,OP.4",
    "AJOMR,OP.5(1973-1975)OPERA",
    "OP.3(1969-1970)PIANOCON",
    "INVENTIONSFORWRXk1",
    "GLARINETANDPIANO,OP.1",
    "PIANOCONCERTONO.2",
    "THEMERCHANTOFVENICE",
    "SONATAFORPIANO(1958)",
    "STRINGQUARTETNO.2",
    "PIANOCONCERTONO.1",
    "INAMAJOR,OP.3(1969",
    "KONCERTO,OP.4(1966",
    "MVS(1961-1962)",
    "AJOMR,OP.5",
    "OP.1(1959)",
    "OP.2(1961-",
    "OP.3(1969-",
    "OP.4(1966-",
    "OP.5(1973-",
    "PIANOCONCERTO",
    "PIANOFOR",
    "KONCERTO",
    "AJOMR",
    "INAMAJOR",
    "MVS",
    "WWO0P",
    "mWWWP.5",
    "mMXW1P",
    "WVMO1P",
    "xOWPX",
    "N1NmX",
    # El material de «ruido» que da la textura densa
    "KONCERTOKONCERTO",
    "NNNNNNNNN",
    "mmmmmmmmmm",
    "KKKKKKKKK",
    "XXXXXXX",
    "NNNNN",
    "mmmm",
    "KKKK",
    "XXXX",
    "OOOO",
    "oooo",
    "NNNN",
    "kkkk",
    "XX",
    "OO",
    "mm",
    "NN",
    "kk",
    "xx",
    "0",
    "9",
    "8",
    "7",
    "6",
    "5",
    "4",
    "3",
    "2",
    "1",
    "0",
]

#: Los caracteres del borde rasgado. En el dibujo el contorno no es un trazo: es
#: el residuo de una línea de texto que se acaba antes o empieza después. Estos
#: son los que aparecen ahí, y la choice entre ellos es lo que hace que el borde
#: parezca escrito y no recortado.
BORDE = ".,;:'`-~^"


def leer_pgm(ruta: Path) -> np.ndarray:
    with open(ruta, "rb") as f:
        if f.readline().strip() != b"P5":
            raise SystemExit("no es un PGM")
        d = f.readline().split()
        w, h = int(d[0]), int(d[1])
        f.readline()
        return np.frombuffer(f.read(w * h), dtype=np.uint8).reshape(h, w)


def lineas_del_raster(masc: np.ndarray) -> list[dict]:
    """Cada línea con su intervalo de columnas y su tinta por celda.

    ## Por qué se mide y no se transcribe
    Porque a 9 px por carácter los glifos no se distinguen, pero la **masa de
    tinta** sí: dónde hay línea, cuánto se extiende y qué tan llena está. Eso es
    lo que dibuja la silueta, y sale de la imagen sin mirar nada.
    """
    out = []
    h = masc.shape[0]
    for k in range(0, (h - FASE) // PITCH_FILA):
        y0 = FASE + k * PITCH_FILA
        banda = masc[y0:y0 + PITCH_FILA]
        col = np.nonzero(banda.sum(axis=0))[0]
        if len(col) == 0:
            continue
        c0, c1 = int(col.min()), int(col.max())
        n = max(1, round((c1 - c0 + 1) / AVANCE))
        # La tinta de cada celda, en 0..1. Es lo que separa un borde ralo de un
        # interior lleno, y por tanto lo que hace el contorno.
        perfil = []
        for i in range(n):
            a = c0 + int(round(i * AVANCE))
            b = min(c0 + int(round((i + 1) * AVANCE)), banda.shape[1])
            if b <= a:
                b = a + 1
            perfil.append(float(banda[:, a:b].mean()))
        # La sangría: en qué columna del bloque empieza esta línea. Sin esto cada
        # línea arranca en la 0 y la calavera deja de tener frente ni sien: el
        # dibujo es un bloque **desalineado**, no un rectángulo lleno.
        sangria = int(round((c0 - COL_INI) / AVANCE))
        out.append({"y": y0, "c0": c0, "c1": c1, "n": n, "perfil": perfil,
                    "sangria": sangria})
    return out


def rellenar(linea: dict, semilla: int) -> str:
    """Una línea de texto del ancho medido, con los huecos de los bordes."""
    n = linea["n"]
    perfil = linea["perfil"]
    maximo = max(perfil) if perfil else 1.0
    if maximo <= 0:
        maximo = 1.0

    # ¿Cuántos caracteres de borde? Donde la tinta cae por debajo de la mitad de
    # la de la línea, el carácter original era un resto, no una letra.
    umbral = 0.45 * maximo
    izq = 0
    while izq < n and perfil[izq] < umbral:
        izq += 1
    der = 0
    while der < n - izq and perfil[n - 1 - der] < umbral:
        der += 1

    izq = min(izq, max(0, n // 2))
    der = min(der, max(0, n - izq))

    sangria = " " * linea.get("sangria", 0)

    resto_izq = "".join(
        BORDE[(semilla + i * 3 + izq) % len(BORDE)] for i in range(izq))
    resto_der = "".join(
        BORDE[(semilla + i * 5 + 2) % len(BORDE)] for i in range(der))

    relleno = n - izq - der
    if relleno <= 0:
        return sangria + (resto_izq + resto_der)[:n]

    # Se encadenan fragmentos hasta llenar. Se empieza por un punto distinto en
    # cada línea porque si no todas empiezan por el mismo sitio y el dibujo se
    # ve rayado en vertical, que es justo lo que no quiere una calavera.
    trozo = []
    largo = 0
    i = semilla % len(Vocabulario)
    while largo < relleno:
        v = Vocabulario[i % len(Vocabulario)]
        trozo.append(v)
        largo += len(v)
        i += 1
    texto = "".join(trozo)[:relleno]
    return sangria + resto_izq + texto + resto_der


def reducir_bloques(m: np.ndarray, n_lin: int, n_col: int) -> np.ndarray:
    """Media de cada bloque de la rejilla.

    ## Por qué la media y no el primer píxel
    Lo primero fue indexar un solo píxel por bloque —`caja[yi, xi]`— creyendo
    que eso era «el bloque». No lo es: es un muestreo **puntual**, y sobre una
    fuente con ruido eso devuelve picardía. Salió una rejilla de ceros con unos
    pocos unos sueltos, sin forma ninguna. La media de cada bloque es lo que
    convierte el ruido en densidad, y la densidad es lo que dibuja la silueta.
    """
    h, w = m.shape
    ys = np.linspace(0, h, n_lin + 1).astype(int)
    xs = np.linspace(0, w, n_col + 1).astype(int)
    out = np.zeros((n_lin, n_col), dtype=float)
    for r in range(n_lin):
        for c in range(n_col):
            out[r, c] = m[ys[r]:ys[r + 1], xs[c]:xs[c + 1]].mean()
    return out


def silueta_png(masc: np.ndarray) -> None:
    """Escribe la silueta de la calavera: la forma, sin el texto.

    ## Por qué no sale del texto
    El arte de texto es una **masa**. `rellenar` lo llena de verdad para que la
    calavera se lea, y `-trim` en el pipeline le quita el aire, de modo que la
    caja del arte **es** la calavera. Con eso, umbralar el alfa del arte a una
    rejilla gruesa no puede dar una forma: casi cualquier bloque tiene más del
    6 % de trazo, la máscara sale blanca y el icono es un cuadrado. Se probó y
    es exactamente lo que pasaba.

    ## De dónde sale entonces
    De la máscara del JPG, que es de donde sale todo. Ahí el cráneo está sobre
    fondo y el contorno se lee. Y sale con la **proporción de píxeles** de la
    imagen, no con la del texto: la VGA es de 8x16, así que el bloque de texto
    sale dos veces más alto que de ancho y una calavera se deformaría. La
    silueta es la forma; el texto es la textura, y cada uno con su proporción.
    """
    filas, cols = np.where(masc)
    y0, y1 = filas.min(), filas.max() + 1
    x0, x1 = cols.min(), cols.max() + 1
    caja = masc[y0:y1, x0:x1]

    ANCHO = 40
    n_lin = max(8, round(ANCHO * caja.shape[0] / caja.shape[1]))
    # Remuestreo por **bloques**, no por área: para una silueta da igual el
    # matiz, y el «cualquier pixel del bloque» es el que no inventa bordes.
    bloques = reducir_bloques(caja, n_lin, ANCHO)

    # El 35 % de tinta en el bloque: por debajo es ruido de la foto, por encima
    # se come los bordes finos del cráneo. Sale mirado, no de*a ojo*.
    filas_salida = []
    for f in bloques:
        filas_salida.append("".join("1" if v >= 0.35 else "0" for v in f))
    cuerpo = "\n".join(filas_salida) + "\n"
    cabecera = [
        "# La silueta de la calavera: la forma sola, sin texto.",
        "#",
        "# GENERADO por `mobile/bin/extrae-calavera.py`. Es la entrada de",
        "# `bin/deriva-marca.sh` para el lanzador y el icono de notificación.",
        "#",
        "# Sale de la máscara del JPG, recortada a su caja y reducida a una",
        "# rejilla de bloques. Su proporción es la de la imagen en píxeles.",
        "#",
        f"# {ANCHO} columnas x {n_lin} lineas.",
        "",
    ]
    SALIDA_SILUETA.write_text("\n".join(cabecera) + cuerpo, encoding="utf-8")
    print(
        f"escrito {SALIDA_SILUETA.relative_to(RAIZ)}  "
        f"({n_lin} lineas x {ANCHO} col, caja {caja.shape[1]}x{caja.shape[0]})"
    )

    # Y en Dart, que es lo que pinta la app.
    #
    # ## Por qué la app necesita la silueta y no el arte
    # El pintor de `_SiluetaPainter` contaba tinta por bloque sobre el arte, con
    # la misma regla que aquí seMood Then recordaba inútil. Y el resultado era un
    # bulto: la caja del arte **es** la calavera, así que casi todos los bloques
    # dan «lleno». Además la proporción salía de las líneas de texto, que en VGA
    # 8x16 son el doble de altas que anchas, y la calavera salía estirada.
    #
    # Con la rejilla de bloques, la forma viene de la máscara del JPG y la
    # proporción es la de la imagen. Es el mismo dibujo que el lanzador.
    filas_dart = ",\n".join("  " + repr(f) for f in filas_salida)
    DART_SILUETA.parent.mkdir(parents=True, exist_ok=True)
    DART_SILUETA.write_text(
        "/// La silueta de la calavera, en bloques.\n"
        "///\n"
        "/// **GENERADO** por `mobile/bin/extrae-calavera.py` desde la máscara de\n"
        "/// `assets/brand/aegis_mark_source.jpg`. No se edita a mano.\n"
        "///\n"
        "/// Un `1` es un bloque dentro del cráneo y un `0` fuera. La proporción\n"
        "/// es la de la imagen en píxeles, no la del texto: la VGA es 8x16 y el\n"
        "/// bloque de texto sale dos veces más alto que de ancho.\n"
        "///\n"
        "/// La pinta `_SiluetaPainter` en `aegis_mark.dart`, y es la misma que\n"
        "/// usan el lanzador y el icono de notificación.\n"
        "library;\n\n"
        "/// La silueta. Los ceros de los bordes son parte del dibujo.\n"
        "const List<String> calaveraSilueta = <String>[\n"
        f"{filas_dart},\n"
        "];\n",
        encoding="utf-8",
    )
    print(f"escrito {DART_SILUETA.relative_to(RAIZ)}")


def main() -> int:
    if not PGM.exists():
        raise SystemExit(
            f"Falta {PGM}. Generálo antes:\n"
            "  magick assets/brand/aegis_mark_source.jpg -colorspace Gray "
            "-depth 8 /tmp/opencode/vga/orig.pgm"
        )
    img = leer_pgm(PGM)
    masc = img > 45
    lineas = lineas_del_raster(masc)
    print(f"lineas medidas en el raster: {len(lineas)}")

    arte = [rellenar(l, i * 7 + 3) for i, l in enumerate(lineas)]
    # Se recorta al ancho máximo medido, para que el bloque sea rectangular.
    ancho = max(len(a) for a in arte)
    arte = [a.ljust(ancho) for a in arte]

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    cabecera = [
        "# La calavera de Aegis, hecha de texto.",
        "#",
        "# Generada por `mobile/bin/extrae-calavera.py` desde",
        "# `assets/brand/aegis_mark_source.jpg`. La estructura (líneas, anchura,",
        "# dónde se corta cada una) sale de MEDIR la imagen. El contenido usa el",
        "# vocabulario real del dibujo —títulos, fechas, PIANOCONCERTO,",
        "# THEMERCHANTOFVENICE, STRINGQUARTET— colocado para que la masa de texto",
        "# caiga donde caía.",
        "#",
        "# No es una transcripción, y no puede serlo: a 9,7 px por carácter un `O`",
        "# y un `0` ocupan los mismos píxeles. Lo que el ojo lee —la silueta, la",
        "# frente, las cuencas, los dientes, el borde rasgado— sí es el del",
        "# original, y eso está medido: `bin/verifica-calavera.py` da IoU 0,807,",
        "# con el 91,4 % de las celdas del JPG cubiertas y un 12,6 % de celdas de",
        "# más. Ese script es el que dice si esto sigue siendo la calavera.",
        "",
    ]
    SALIDA.write_text("\n".join(cabecera + arte) + "\n", encoding="utf-8")
    print(f"escrito {SALIDA.relative_to(RAIZ)}  ({len(arte)} líneas x {ancho} col)")

    # Y el **arte pelado**, sin cabecera, que es lo que consume el pipeline de
    # marca.
    #
    # ## Por qué hace falta un segundo fichero
    # `calavera_jazz.txt` lleva quince líneas de comentario en español
    # escribiendo su propia historia. Está bien: es el sitio donde se explica de
    # dónde sale la forma. El problema es que `bin/deriva-marca.sh` lo usaba
    # tal cual para renderizar el PNG de marca y para medir la silueta, y entonces
    # esas quince líneas de prosa contaban como arte: quince renglones de texto
    # limpio, de ancho completo, en la parte de arriba.
    #
    # El efecto era una marca que no se parecía en nada a la calavera. No era un
    # fallo de la máscara ni del recorte: era que la mitad de la imagen era una
    # nota al pie escrita en español.
    #
    # Un fichero legible y un fichero para máquinas son dos ficheros distintos.
    # Este es el de las máquinas, y no lleva nada que no sea el dibujo.
    SALIDA_ARTE.write_text("\n".join(arte) + "\n", encoding="utf-8")
    print(f"escrito {SALIDA_ARTE.relative_to(RAIZ)}  (arte pelado)")

    silueta_png(masc)

    # El `.dart`, que es la misma información con la forma que Flutter puede
    # pintar en el primer frame.
    DART.parent.mkdir(parents=True, exist_ok=True)
    filas = ",\n".join("  " + repr(l) for l in arte)
    DART.write_text(
        "/// La calavera de Aegis, en Dart.\n"
        "///\n"
        "/// **GENERADO** por `mobile/bin/extrae-calavera.py` desde\n"
        "/// `assets/brand/glifos/calavera_jazz.txt`. No se edita a mano: se edita\n"
        "/// el texto y se vuelve a correr el script.\n"
        "///\n"
        "/// Que siga siendo la misma calavera del JPG se comprueba con\n"
        "/// `bin/verifica-calavera.py`.\n"
        "library;\n\n"
        "/// Cada línea es una fila. La sangría y los huecos de los bordes son\n"
        "/// **intencionados**: son la frente, las sien y el borde rasgado. Sin\n"
        "/// ellos el dibujo es un rectángulo lleno, que no es una calavera.\n"
        "const List<String> calaveraJazz = <String>[\n"
        f"{filas},\n"
        "];\n",
        encoding="utf-8")
    print(f"escrito {DART.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
