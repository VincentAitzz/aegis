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

## Los ficheros de la raíz

`aegis_mark.png` y `aegis_mark_source.jpg` son de la marca anterior, la que se
retiró. El PNG era el cráneo ASCII que salía en el arranque, y ya no sale: el
arranque usa ahora el glifo vectorial de `lib/core/widgets/aegis_mark.dart`, que
no necesita ninguna imagen.

Cuando saques de aquí lo que sirva de esos dos, se borran. No hace falta
mantener un icono que ninguna pantalla muestra, y un icono viejo en el repo es
una forma de que alguien lo vuelva a usar sin querer.

## Nota sobre `git`

Las imágenes de `inbox/` pueden ser pesadas y no valen nada hasta que se
implementan. Están fuera del índice a propósito; si alguna te importa de verdad,
súbela al repo a mano. Es preferible un almacén local a un repo que carga peso
que nadie ha decidido todavía.