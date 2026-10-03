# Material de marca

Dos carpetas con dos reglas distintas. La diferencia es si la app lo carga o no.

## `inbox/` — lo que te gusta

Aquí dejas lo que te parezca: capturas, imágenes que viste, logotipos, texturas,
paletas de otros sitios que te llamen la atención. **No se declara en `pubspec.yaml`
y la app no lo ve nunca.** Puedes llenar esta carpeta de lo que quieras sin que
cambie una sola línea de código ni un solo byte del APK.

No es un sitio de trabajo: es un almacén. Cuando algo de aquí te parezca lo
suficientemente bueno como para que la app lo use, ese algo pasa a `derivados/`
y pasa a ser código.

## `derivados/` — lo que la app usa

Solo lo que la app carga de verdad, y por eso **está declarado en `pubspec.yaml`**.
Cada fichero de aquí tiene un motivo: o es el ícono del lanzador, o es el
foreground del ícono adaptativo, o es una textura de fondo. Lo que no vaya a la
app, no va aquí.

Un APK pesa lo que pesa `derivados/`. Por eso lo que entra aquí entra con una
razón.

## Cómo se decide qué se implementa

El camino es siempre el mismo, y en el mismo orden:

1. La imagen entra en `inbox/`.
2. Se decide **qué** de ella se implementa: un color, una forma, un tipo de letra.
   Casi nunca la imagen entera: una foto no es un token de diseño.
3. Si es un color, va a `lib/core/theme/aegis_palette.dart`. Si es una forma, a
   `lib/core/widgets/aegis_mark.dart`. Los tokens son código, y se quedan en el
   código.
4. Solo si tiene que ser un fichero binario (el ícono del lanzador) se deriva y
   se pone en `derivados/`.

## La fuente es el **texto**

La marca ya no es un SVG: es `glifos/calavera_jazz.txt`, una calavera de 77
renglones. El SVG y los PNG pasaron a ser **derivados**, porque una calavera hecha
de texto no se edita como geometría, se edita como texto.

```
glifos/calavera_jazz.txt          ← la fuente
        │
        ├── lib/core/widgets/glifos/calavera_jazz.dart   generado, para pintar
        │     el primer frame sin esperar un asset
        ├── assets/brand/derivados/                      la grande y la zona segura
        └── res/mipmap-*, res/drawable-*                 lanzador y notificación
```

Y hay un check, porque «parece la misma» no es una medida:

```
python3 bin/extrae-calavera.py     # del JPG al texto, y el texto a Dart
python3 bin/verifica-calavera.py   # IoU 0,807 · 91,4 % del JPG cubierto
```

## Sobre el JPG y por qué esto no es una transcripción

`aegis_mark_source.jpg` es la calavera original, a **9,7 × 8,2 px por carácter**.
A esa resolución un `O` y un `0` ocupan los mismos píxeles. Se comprobó: al
agrupar las celdas por forma salen 2480 grupos distintos para 3033 celdas, o sea
que casi ninguna se parece a otra. **Ningún método recupera ese texto**, ni
automático ni a ojo.

Lo que sí se conserva, porque sale de **medir** la imagen y no de mirar:

- cuántas líneas hay, dónde empieza y acaba cada una, y su anchura;
- qué tan llena está cada celda, que es lo que dibuja la silueta;
- la frente, las sien, las cuencas, los dientes y el borde rasgado.

Y lo que se ha rellenado con el **vocabulario real** del dibujo —`PIANOCONCERTO`,
`THEMERCHANTOFVENICE`, `STRINGQUARTET`, `OP.1(1959)`, `AJOMR`— colocado para que
la masa de texto caiga donde caía. La diferencia es de contenido, no de forma, y
el verificador la mide: 91,4 % de las celdas del original están cubiertas.

## `bin/deriva-marca.sh`: un texto, todas las salidas

Una identidad son **cinco** ficheros que tienen que ser el mismo dibujo: el PNG
grande, el foreground adaptativo, el lanzador, el ícono de las notificaciones y
—si lo que se quiere es que la llave se vea— el que se comparte. Copiados a
mano, un día uno se cambia y los otros cuatro se quedan con el dibujo viejo, y no
se nota hasta que alguien compara el icono del móvil con el de la notificación.

Por eso hay un script:

```bash
bash mobile/bin/deriva-marca.sh assets/brand/inbox/<lo-que-sea>.svg
```

Sale de **un** fichero, o no sale nada:

| salida | para qué | qué es |
|---|---|---|
| `derivados/aegis_mark.png` | documentación | el arte, a color |
| `derivados/aegis_mark_foreground.png` | zona segura | el arte con aire |
| `res/mipmap-*/ic_launcher.png` | lanzador | **silueta** en celeste |
| `res/drawable-*/ic_launcher_foreground.png` | ícono adaptativo | el arte con aire |
| `res/drawable-*/aegis_mono.png` | **notificaciones** | **silueta** en blanco con alfa |

Las dos siluetas salen de la misma pregunta —«¿hay tinta en esta celda?»— sobre
el arte, y por eso no pueden separarse del original: si mañana cambia el
dibujo, cambian las dos. Y la del aviso **tiene que ser silueta** por dos
motivos: Android tiñe el icono de las notificaciones del color del canal, y a
24 dp una calavera de 77 renglones es un rectángulo gris.

### La VGA

El arte usa **Px437 IBM VGA 8x16** (`assets/fonts/`), no una monoespaciada
moderna: a 9 px por carácter, el interlineado y el peso del trazo son lo que
hace que se lea como VGA. Solo para el arte ASCII — la UI sigue con
`ShareTechMono`, que a 11 px se lee mucho mejor.

### El glifo de Dart

El script no sabe pintar. `lib/core/widgets/aegis_mark.dart` pinta el glifo en
vivo y decide por el tamaño si le cabe la calavera entera o la silueta: por
debajo de 300 px son 77 renglones que no se leen, así que `AegisMark` **no
pregunta**, decide solo. Y el color no lo elige cada sitio: lo saca de
`EstadoAegis` en un único sitio, porque el glifo aparece en seis pantallas y si
cada una|tradujera la actividad a su manera, un día una queda celeste con el
agente hablando y nadie lo nota hasta que se comparan dos pantallas.

Si cambias la geometría, cambian las dos cosas: el arte de aquí y el
`CustomPainter` de Dart. Un icono solo se juzga después de que el sistema le
aplique su máscara, nunca sobre el PNG (A-024).

## Los ficheros de la raíz

`aegis_mark_source.jpg` es **la calavera original**: 736×1040, verde sobre negro.
No se carga nunca y no se va a borrar, porque `bin/extrae-calavera.py` la mide y
`bin/verifica-calavera.py` compara contra ella. Sin esa imagen, la afirmación
«esto sigue siendo la calavera» no se puede comprobar.

`aegis_mark.png` era el cráneo ASCII de la marca que se retiró, y ya no lo usa
nadie. Se puede borrar; no molesta mientras siga ahí, pero un icono viejo en el
repo es una forma de que alguien lo vuelva a usar sin querer.

## Nota sobre `git`

Las imágenes de `inbox/` pueden ser pesadas y no valen nada hasta que se
implementan. Están fuera del índice a propósito; si alguna te importa de verdad,
súbela al repo a mano. Es preferible un almacén local a un repo que carga peso
que nadie ha decidido todavía.