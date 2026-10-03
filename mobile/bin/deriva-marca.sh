#!/usr/bin/env bash
# De una imagen de marca, todo lo que el sistema necesita.
#
# ## Por qué un script y no «cópialo a mano»
# Porque una identidad son **varios ficheros que tienen que ser el mismo dibujo**:
# el ícono del lanzador, el foreground del ícono adaptativo, el icono pequeño de
# la notificación y el PNG grande para documentación. Copiados a mano, un día uno
# se cambia y los otros tres se quedan con el dibujo viejo; y no se nota hasta
# que alguien compara el icono del móvil con el de la notificación.
#
# Aquí sale **todo** de un fichero, o no sale nada.
#
# ## SVG o PNG
# SVG si lo tienes, porque un logo es geometría y la geometría se puede
# reescalar sin que nada aparezca. PNG de 1024 si no: también vale, y el script
# no distingue. Lo que no vale es un PNG pequeño, porque subirlo a 1024 deja los
# bordes como una escalera.
#
# ## Qué produce, y por qué cada salida es distinta
#
#   derivados/aegis_mark.png             1024 a color. Documentación y uso suelto.
#   derivados/aegis_mark_foreground.png  La **zona segura** del ícono adaptativo.
#   mipmap-*/ic_launcher.png             Lanzador legacy, cuadrado, por densidad.
#   drawable-*/ic_launcher_foreground.png  Ícono adaptativo, por densidad.
#   drawable-*/aegis_mono.png            La **silueta** de las notificaciones.
#
# Las dos últimas deservecen una razón, porque son las que parece que podrían
# ser el mismo fichero y no lo son:
#
# - **El foreground va a color** porque es un ícono de tu marca, y se ve en la
#   pantalla de inicio como lo que es.
# - **La silueta no lleva color** porque Android **tiñe** el icono de las
#   notificaciones del color del canal y aplana la transparencia para la barra de
#   estado. Un dibujo a color ahí sale un borrón del color que más abunda. La
#   silueta deja la forma intacta y que el sistema ponga el color, que es lo que
#   corresponde: en la barra de estado el color es de Aegis.
#
# ## El margen del 18 %
# Android recorta el ícono adaptativo por cada lado y además lo enmascara con
# formas distintas según el fabricante: círculo, cuadrado, «squircle». Un dibujo
# que toca el borde se ve entero en tu móvil y cortado en el de al lado. Por eso
# el foreground va al 64 % del lienzo, que es lo que respeta cualquier máscara.
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
#: La fuente de la marca es el **arte ASCII**, no un SVG.
#:
#: Antes era un SVG y este script rasterizaba geometría. Con la calavera eso se
#: invirtió: el texto es la fuente —una calavera hecha de texto no se edita como
#: geometría, se edita como texto— y todo lo demás sale de aquí.
ARTE="${ARTE:-$RAIZ/assets/brand/glifos/calavera_jazz.txt}"
# El mismo arte sin la cabecera de comentarios. El que lleva comentarios es para
# las personas; este es el que consume el pipeline. Se puede apuntar con
# $ARTE_PELADO, pero el valor por defecto es el pelado, no el documentado: lo
# contrario es tener que acordarse de un `sed`.
ARTE_PELADO="${ARTE_PELADO:-$RAIZ/assets/brand/glifos/calavera_jazz.arte.txt}"
# La **forma**, en bloques. La genera el mismo script Python desde la máscara del
# JPG. Es una entrada distinta del arte y por un motivo que está en la función
# `silueta`: del texto no sale una forma.
SILUETA="${SILUETA:-$RAIZ/assets/brand/glifos/calavera_silueta.txt}"

#: Hueso. El mismo de `AegisPalette.hueso`, y por el mismo motivo que la fuente:
#: el arte vive en un fichero que Flutter no lee, así que el valor se repite y
#: está aquí con nombre.
HUESO="#E8E4DA"

DERIVADOS="$RAIZ/assets/brand/derivados"
RES="$RAIZ/android/app/src/main/res"
VGA="$RAIZ/assets/fonts/Px437_IBM_VGA8.ttf"

if [[ ! -f "$SILUETA" ]]; then
  echo "Falta la silueta de la marca: $SILUETA" >&2
  echo "Generála con:  python3 bin/extrae-calavera.py" >&2
  exit 1
fi
if [[ ! -f "$ARTE_PELADO" ]]; then
  echo "Falta el arte pelado de la marca: $ARTE_PELADO" >&2
  echo "Generálo con:  python3 bin/extrae-calavera.py" >&2
  exit 1
fi
if [[ ! -f "$ARTE" ]]; then
  cat >&2 <<EOF
Falta el arte de la marca: $ARTE

Se genera del JPG con:

  ../bridge/.venv/bin/python bin/extrae-calavera.py
  ../bridge/.venv/bin/python bin/verifica-calavera.py   # que sigue siendo la misma

Y el texto resultante es la fuente: se edita a mano si quieres, y luego se
comprueba con el verificador para que no deje de ser la calavera.
EOF
  exit 1
fi

command -v magick >/dev/null || command -v convert >/dev/null || {
  echo "deriva-marca necesita ImageMagick (magick o convert)." >&2
  exit 1
}
CONV="$(command -v magick || command -v convert)"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/arte" "$DERIVADOS"

# -- Del arte ASCII a la silueta del sistema ---------------------------------
#
# ## Por qué al final y no al principio
# Porque el arte es la fuente y la silueta sale de él. Al revés —silueta primero,
# arte después— las dos se desincronizan el día que se cambia el dibujo, y aquí
# el síntoma sería silencioso: el lanzador con la calavera de antes y el glifo
# con la de ahora, que solo se ven si alguien los compara.
#
# ## Qué se hace
# 1. El arte se rasteriza con la **misma VGA** que la app, al tamaño que le
#    toca. Si la silueta se hiciera con otra fuente, el lanzador y el glifo
#    tendrían formas distintas.
# 2. Se reduce a una rejilla gruesa preguntando «hay tinta en esta celda?», que
#    es la **silueta**: la forma, sin el ruido del texto. A 24 dp un dibujo de
#    77 renglones es un rectángulo gris; la silueta es lo que se lee.
#
#    ## Por qué el umbral va al 88 % y no al 25 %
#    Porque el arte es **texto negro sobre blanco**, y al reducirlo cada celda
#    promedia: una celda del interior denso queda al 40 % de tinta, o sea al 60 %
#    de brillo. Con un umbral del 25 %, todo eso queda «por encima» y sale
#    **todo blanco**: una silueta vacía, que es lo que pasó la primera vez.
#
#    Lo que se busca es el otro extremo: que cualquier celda **con un poco de
#    tinta** pase a negro. El 88 % es donde la calavera se separa bien: da un 46 %
#    de cobertura, que es lo que ocupa una calavera, y no un 82 % —que sería un
#    bloque— ni un 29 % —que sería un esqueleto de puntos.
# 3. De ahí salen el lanzador y `aegis_mono.png`, que es la que Android tiñe.
# Las 12 primeras líneas del fichero son el comentario que explica de dónde sale
# esto. Se saltan porque no son dibujo.
tmp2="$tmp/arte"
# El arte **pelado**: `calavera_jazz.arte.txt`, que es el mismo dibujo sin las
# quince líneas de comentario de `calavera_jazz.txt`. Antes se hacía `sed '1,12d'`
# para quitar la cabecera, y la cabecera tiene **dieciséis** líneas: se colaban
# cuatro renglones de prosa en español, de ancho completo, encima de la calavera.
# Con ellos, la silueta no era el dibujo sino un rectángulo con una nota al pie.
cp "$ARTE_PELADO" "$tmp2/lineas.txt"

# El arte. **Transparente y en hueso**, y esto importa más de lo que parece:
#
# - **Transparente**, porque de aquí sale todo. Con fondo blanco, el blanco se
#   cuela en el foreground adaptativo y el ícono sale con uncuadrado blanco
#   detrás — que es exactamente lo que se veía.
# - **En hueso**, que es lo que se pidió. El celeste vive en la app, en el
#   contorno del glifo vivo, que cambia con el estado; un fichero estático no
#   tiene estado, y painted de celeste es solo un color más.
"$CONV" -background none -fill "$HUESO" -font "$VGA" \
  -pointsize 20 label:@"$tmp2/lineas.txt" -trim +repage "$tmp2/arte.png"

# Las densidades, con el factor **duplicado y entero** porque la aritmética de
# bash no admite `1.5`. Se divide entre dos al usarlo.
#
# La tabla sin esa mitad salía 1,5 veces grande en todas las densidades menos
# mdpi: un icono de 288 px donde tocaban 192. Android lo escala, y un icono
# escalado se ve borroso —que es uno de los «se ve mal» que había.
for spec in "mdpi 2" "hdpi 3" "xhdpi 4" "xxhdpi 6" "xxxhdpi 8"; do
  read -r d f2 <<<"$spec"
  mkdir -p "$RES/mipmap-$d" "$RES/drawable-$d"

# La máscara de la silueta, desde el fichero de bloques.
  #
  # ## Por qué NO sale del arte de texto
  # Porque del texto no sale. `rellenar` llena la calavera de verdad para que se
  # lea, y `-trim` le quita el aire, así que la caja del arte **es** la calavera:
  # dentro de ella casi cualquier bloque tiene trazo. UMBralar el alfa del arte
  # a una rejilla gruesa da entonces una máscara blanca y un icono que es un
  # cuadrado. Se probó, y también se probó preguntando por renglones en vez de por
  # píxeles, que es peor: el perfil de anchuras del arte es 42, 45, 47… 65… 24,
  # una cuña, no un cráneo.
  #
  # ## De dónde sale entonces
  # De la máscara del JPG, que es lo que mide `bin/verifica-calavera.py`. Ahí el
  # cráneo está sobre fondo y la silueta se lee. Y con la **proporción de
  # píxeles** de la imagen, no con la del texto: la VGA es 8x16, el bloque de
  # texto sale dos veces más alto que de ancho y una calavera se deformaría. La
  # forma es de la imagen; el texto es la textura; cada uno con su proporción.
  silueta() {
    # $1 = lado en px de salida, $2 = fichero donde dejar la máscara.
    local lado="$1" salida="$2" filas
    # Se filtran las filas de la rejilla **antes** de medir nada.
    #
    # ## Por qué en dos pasos
    # Midiendo sobre el fichero entero, `awk 'NR>1 && NF'` encuentra la primera
    # línea con campos: eso es una línea de comentario, de un carácter de ancho.
    # El PBM salía `P1 1 43` —una columna y 43 filas— y al estirarlo a 192x192
    # daba un cuadrado hueso. Un `P1` de una sola columna es indistinguible de un
    # icono entero del color, que es justo lo que se veía.
    filas=$(grep -c '^[01]\{2,\}$' "$SILUETA")
    {
      printf 'P1 %s %s\n' "$(grep -m1 '^[01]\{2,\}$' "$SILUETA" | tr -d ' \n' | wc -c)" "$filas"
      grep '^[01]\{2,\}$' "$SILUETA" | tr -d ' ' | awk \
        '{ for (i = 1; i <= length($0); i++) printf "%s ", substr($0, i, 1); print "" }'
    } > "$salida.pbm"
    # Dos invocaciones y no una.
    #
    # ## Por qué
    # `magick -size NxN xc:negro mascara -compose Lighten -composite -extent NxN`
    # satura la imagen a un solo color, y con `-flatten` pasa igual. Medido: el
    # mismo encadenado da 2 colores sin `-extent`, 2 sin `-flatten`, y **1** con
    # cualquiera de los dos. Dentro de la misma invocación, `-extent` y
    # `-flatten` se llevan por delante el resultado del composito. Separado en
    # dos comandos, cada uno hace lo suyo y el icono sale con la forma.
    # `-negate` porque **la PBM tiene la polaridad al revés**: en Netpbm un `1`
    # es negro y un `0` es blanco. Sin esta inversión la máscara sale con el
    # cráneo de fondo, y el icono es un cuadrado de hueso con un cranium hueco.
    "$CONV" "$salida.pbm" -negate -filter point -resize "${lado}x${lado}" "$salida"
    "$CONV" "$salida" -background black -gravity center -extent "${lado}x${lado}" "$salida"
  }

  # El lanzador: silueta en hueso sobre negro, opaco.
  #
  # ## Por qué `Lighten` y no `CopyOpacity`
  # `CopyOpacity` exige saber de qué lado va la imagen con alfa y cuál se copia;
  # en ImageMagick 7 el orden importa y es facil equivocarse —las dos versiones
  # que se probaron dieron un cuadrado entero o un cuadrado negro—. Con un
  # `-compose Lighten` sobre un lienzo negro no hay ambigüedad: el máximo entre
  # negro y la máscara es la máscara. Para el icono de notificación hace falta
  # además **alfa**, y eso se consigue con `-transparent black`, que se lleva el
  # fondo y deja solo la forma.
  #
  # ## Y `-opaque white`, no `-colorize`
  # `-colorize` mezcla la imagen con el relleno, y al 100 % con un relleno opaco
  # eso quiere decir «todos los píxeles son del relleno». El icono salía entero
  # del color del hueso: un cuadrado. `-opaque white` es lo que se quiere —cambiar
  # el blanco por hueso— y no toca el negro, porque no es blanco.
  lado=$(( 48 * f2 / 2 ))
  silueta "$lado" "$tmp2/sil-$d.png"
  "$CONV" -size ${lado}x${lado} xc:black "$tmp2/sil-$d.png" \
    -compose Lighten -composite -fill "$HUESO" -opaque white \
    -define png:compression-level=9 "$RES/mipmap-$d/ic_launcher.png"

  # El foreground adaptativo, con el 66 % central que respeta cualquier máscara.
  # El arte se **encaja** (sin `!`), así que conserva su proporción y no se
  # deforma: a 0,89 queda estrecho dentro del cuadrado, con el aire alrededor.
  fg=$(( 108 * f2 / 2 ))
  util=$(( fg * 64 / 100 ))
  "$CONV" "$tmp2/arte.png" -resize ${util}x${util} \
    -background none -gravity center -extent ${fg}x${fg} \
    -define png:compression-level=9 "$RES/drawable-$d/ic_launcher_foreground.png"

  # La de las notificaciones: **blanca y con alfa**, porque Android la tiñe del
  # color del canal y aplana la transparencia. Con fondo en vez de alfa, el
  # sistema pinta un cuadrado del color del aviso.
  mono=$(( 24 * f2 / 2 ))
  silueta "$mono" "$tmp2/silm-$d.png"
  "$CONV" -size ${mono}x${mono} xc:black "$tmp2/silm-$d.png" \
    -compose Lighten -composite -transparent black \
    -define png:compression-level=9 "$RES/drawable-$d/aegis_mono.png"
done

# El `image_path` de `pubspec.yaml` y el grande de documentación, del mismo arte.
# El grande es para documentación, no para la app.
#
# ## Sin paleta
# La primera versión iba con `-colors 16` para que el PNG no pesara, y salió un
# borro gris: el arte son miles de caracteres de 5 px, y al cuantizar a 16 tonos
# las letras dejan de distinguirse y se funden con el fondo. Un logo que se ve
# mal en el fichero de marca vale menos que un logo de 250 KB.
#
# ## Lienzo vertical, no cuadrado
# La calavera es más alta que ancha (relación 0,44). En un lienzo cuadrado
# cabía en la mitad izquierda y se veía como una banda con medio fondo vacío al
# lado. El lienzo va con la proporción del dibujo.
"$CONV" -background "#07080B" -fill "#4CC9F0" -font "$VGA" \
  -pointsize 20 label:@"$tmp2/lineas.txt" -trim +repage -resize 420x820 \
  -gravity center -background "#07080B" -extent 460x820 \
  -define png:compression-level=9 -define png:compression-filter=5 \
  -strip "$DERIVADOS/aegis_mark.png"
"$CONV" -background "#07080B" -fill "#4CC9F0" -font "$VGA" \
  -pointsize 20 label:@"$tmp2/lineas.txt" -trim +repage -resize 280x600 \
  -gravity center -background none -extent 300x600 \
  -define png:compression-level=9 "$DERIVADOS/aegis_mark_foreground.png"

echo "Salidas desde el arte ASCII:"
echo "  $DERIVADOS/aegis_mark.png              1024 a color"
echo "  $DERIVADOS/aegis_mark_foreground.png   zona segura"
echo "  $RES/mipmap-*/ic_launcher.png            lanzador (silueta)"
echo "  $RES/drawable-*/ic_launcher_foreground.png  adaptativo (arte)"
echo "  $RES/drawable-*/aegis_mono.png           notificaciones (silueta)"
