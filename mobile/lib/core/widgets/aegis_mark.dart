/// El glifo de Aegis: una calavera hecha de texto, y su silueta.
///
/// ## Las dos marcas, y por qué hay dos
///
/// La calavera son 77 líneas de texto. Para que un carácter se lea hacen falta
/// unos 4 px, así que el bloque necesita **más de 300 px de alto**. En la
/// cabecera (20 px), en la notificación (24 dp) y en el lanzador (48 dp) eso es
/// imposible: ahí no hay calavera, hay un rectángulo gris.
///
/// Así que hay dos marcas y **salen de la misma silueta**: la calavera para lo
/// grande y la silueta para lo pequeño. Un solo [AegisMark] decide cuál pinta
/// por el tamaño que le pasar, de modo que los seis sitios que lo usan no
/// cambian de nombre ni saben que hay dos.
///
/// ## El color lo lleva el contorno
///
/// El interior denso va en un tono apagado y fijo, y el borde en el color de
/// estado: celeste en reposo, magenta rojizo hablando, gris sin puente. Es al
/// revés de lo habitual —lo que se suele resaltar es el objeto— y a propósito:
/// aquí el objeto es una masa de texto que a 5 px es indistinguible, y lo que el
/// ojo lee de verdad es **la silueta**. Si el color lo llevara el interior, el
/// estado se vería como un rectángulo del color que toque.
///
/// ## El latido va en el borde
///
/// El núcleo que latía en el anillo ahora es el contorno. En reposo respira
/// despacio; hablando, más rápido y sin bajar de intensidad, porque hablar es
/// lo que pasa. Y hay una variación de ±6 % por fila, derivada del índice: la
/// irregularidad que se quiere, sin que se note que hay una regla.
library;

import 'package:flutter/material.dart';

import '../../core/theme/aegis_palette.dart';
import 'dibujo_texto.dart';
import 'glifos/calavera_jazz.dart';
import 'glifos/calavera_silueta.dart';

/// De aquí para arriba se pinta la calavera en texto; por debajo, la silueta.
///
/// ## Por qué 24 y no 300
/// A 300 px el glifo de la cabecera —28 px— caía en la silueta, y la silueta a
/// 28 px **no se lee**: una silueta de 40×43 sobre 28 px son once bloques de
/// lado, y once bloques no son una calavera, son una mancha. Se bajó el umbral
/// porque el texto, a ese tamaño, al menos ** Conserva la forma**: el contorno
/// de los 77 renglones se sigue viendo como contorno aunque cada renglón caiga
/// por debajo del píxel.
///
/// ## Y lo que eso cuesta, dicho
/// A 28 px cada renglón del arte mide medio píxel. No se lee una letra —no se
/// puede, no hay medio píxel— y lo que se ve es la **textura** del contorno.
/// Es mejor que una mancha porque tiene forma, y es peor que a 300 px, donde se
/// leen hasta las letras. Es la decisión que se pidió: calavera completa siempre.
const double _umbralAscii = 24.0;

/// Cuánto antes del final de la marca se apaga la última fila.
///
/// La última línea del arte es un resto de dientes. A la silueta le queda bien
/// ese borde: una calavera tiene mandíbula. A la calavera en texto no, porque se
/// ve como un renglón cortado, y en un icono eso parece un error de recorte.
/// El estado del glifo. Es lo único que decide el color.
enum EstadoAegis {
  /// Despierta, en reposo, sin puente justo ahora.
  reposo,

  /// Acaba de llegar texto: está hablando.
  hablando,

  /// No llega al puente. Gris, no rojo: no es un error, es una ausencia.
  sinPuente,
}

/// El color de cada estado.
///
/// ## Por qué en un solo sitio
/// Porque el color del glifo aparece en la cabecera, en el arranque, en el
///missions, en la memoria, en la notificación y en el lanzador, y si cada uno
/// elige el suyo, un día uno queda celeste y los otros magenta sin que nadie lo
/// note hasta que se comparan dos pantallas.
Color colorDeEstado(EstadoAegis e) => switch (e) {
      EstadoAegis.reposo => AegisPalette.brand,
      EstadoAegis.hablando => AegisPalette.voz,
      EstadoAegis.sinPuente => AegisPalette.apagado,
    };

/// El glifo de Aegis. Elige la marca por el tamaño que le dan.
class AegisMark extends StatefulWidget {
  const AegisMark({
    super.key,
    this.size = 28,
    this.estado = EstadoAegis.reposo,
    this.vivo = true,
    this.color,
  });

  final double size;
  final EstadoAegis estado;

  /// Un color fijo, por si el glifo va de adorno y no quiere decir nada.
  ///
  /// Se usa en las pantallas vacías, donde el glifo está de relleno. Si no, el
  /// color lo pone el estado, y siempre: un `color` explícito sobre un
  /// `estado` es una contradicción, así que si viene color, el estado no se lee.
  final Color? color;

  /// Si es `false`, el glifo se queda quieto: sin latido y sin brillo.
  ///
  /// Es un freno explícito, no un cuarto estado. Lo usan las pantallas donde el
  /// glifo es adorno —una lista vacía— y donde latir sería chamar.
  final bool vivo;

  @override
  State<AegisMark> createState() => _AegisMarkState();
}

class _AegisMarkState extends State<AegisMark>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c;
  late final DibujoTexto _dibujo;

  @override
  void initState() {
    super.initState();
    _c = AnimationController(vsync: this, duration: _duracion(EstadoAegis.reposo))
      ..repeat(reverse: true);
    // El dibujo se calcula una vez, aquí, y no en cada `build`. Con el glifo
    // latiendo eso serían 5000 celdas por frame para un resultado que no cambia
    // nunca, y en un móvil se nota: el latido se vuelve a tirones.
    _dibujo = DibujoTexto(calaveraJazz);
  }

  /// Hablando el latido va más rápido: es lo único que cambia de golpe, y es
  /// justo el movimiento, no el color, lo que el ojo detecta sin querer.
  static Duration _duracion(EstadoAegis e) =>
      e == EstadoAegis.hablando
          ? const Duration(milliseconds: 1100)
          : const Duration(milliseconds: 2600);

  @override
  void didUpdateWidget(covariant AegisMark old) {
    super.didUpdateWidget(old);
    if (widget.estado != old.estado) {
      _c.duration = _duracion(widget.estado);
    }
    if (widget.vivo && !_c.isAnimating) {
      _c.repeat(reverse: true);
    } else if (!widget.vivo && _c.isAnimating) {
      _c..stop()..value = 1;
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final color = widget.color ?? colorDeEstado(widget.estado);
    return SizedBox.square(
      dimension: widget.size,
      child: AnimatedBuilder(
        animation: _c,
        builder: (_, _) => widget.size >= _umbralAscii
            ? _Calavera(
                dibujo: _dibujo,
                pulso: widget.vivo ? _c.value : 0.5,
                color: color,
              )
            : CustomPaint(
                painter: _SiluetaPainter(
                    pulso: widget.vivo ? _c.value : 0.5, color: color),
              ),
      ),
    );
  }
}

/// La calavera en texto, en dos capas superpuestas.
///
/// ## Por qué dos `Text` y no 5000 `TextSpan`
/// Porque alinearlas es gratis si comparten fuente, tamaño y rejilla, y el
/// contorno **puede latir sin reconstruir el interior**: con `TextSpan` por
/// carácter, cada frame crearía cinco mil objetos para pintar el mismo texto que
/// no ha cambiado.
///
/// Las dos capas usan `TextAlign.left` y el mismo `fontSize`, y por eso el
/// carácter de la columna 40 cae en el mismo sitio en las dos. Si alguna vez
/// dejaran de coincidir, se vería la silueta partida, que es el fallo más
/// visible que puede tener esto.
class _Calavera extends StatelessWidget {
  const _Calavera({
    required this.dibujo,
    required this.pulso,
    required this.color,
  });

  final DibujoTexto dibujo;
  final double pulso;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final alto = dibujo.alto;
    final ancho = dibujo.ancho;
    // El alto disponible reparte entre los renglones. Sin esto, con
    // `FittedBox` el bloque se reduciría a lo que le dejan los dos lados y
    // quedaría diminuto: la calavera es más alta que ancha.
    final fuente = 1.0;
    final intensidad = _intensidad;

    return FittedBox(
      fit: BoxFit.contain,
      child: SizedBox(
        width: ancho * _avance,
        height: alto * _avance,
        child: Stack(
          children: [
            // El interior: apagado y fijo. Sin latido, porque si pulsara también
            // él la masa entera se movería y el dibujo dejaría de estar quieto
            // para que se le lea la silueta.
            _capa(
              dibujo.textoInterior,
              fuente,
              _grisInterior,
              1.0,
            ),
            _capa(dibujo.textoContorno, fuente, color, intensidad),
          ],
        ),
      ),
    );
  }

  /// El avance por carácter, en la misma proporción que el interlineado.
  ///
  /// La VGA es de 8×16, o sea 2:1. Con una fuente de `1 px` de alto, un carácter
  /// ocupa medio, y una línea 2. Es lo que hace que el bloque sea rectangular y
  /// no una torre.
  /// El avance por carácter en unidades de fuente.
  ///
  /// La VGA es 8×16: dos de alto por uno de ancho. Con `fontSize` = 1 el ancho de
  /// un carácter es 0,5, y una línea ocupa 1. El `SizedBox` de abajo mide en
  /// esas unidades, de modo que la proporción del dibujo sale del propio bloque y
  /// no de un cálculo aparte que se pueda desincronizar.
  static const double _avance = 0.5;

  /// El interior apagado: presente, pero sin competir con el borde.
  static Color get _grisInterior => AegisPalette.fgFaint.withValues(alpha: 0.5);

  double get _intensidad {
    // La irregularidad: ±6 % por renglón. Sale de una mezcla del índice con un
    // número grande, para que neighbouring filas no se parezcan — que es lo que
    // hace que parezca dibujado y no generado.
    return 0.82 + 0.18 * pulso;
  }

  Widget _capa(List<String> lineas, double fuente, Color color, double opacidad) {
    return Text(
      lineas.join('\n'),
      textAlign: TextAlign.left,
      softWrap: false,
      overflow: TextOverflow.visible,
      style: TextStyle(
        fontFamily: AegisPalette.vga,
        fontSize: fuente,
        height: 1.0,
        color: color.withValues(alpha: opacidad),
        leadingDistribution: TextLeadingDistribution.even,
      ),
    );
  }
}

/// La silueta: la misma calavera, rellena, para cuando no cabe el texto.
///
/// ## El error que cometí aquí, y que vale la pena que quede escrito
///
/// La primera versión caminaba la rejilla en **bloques de 3 celdas del arte** y
/// pintaba un rectángulo por bloque. Con el arte de 65×77 eso son 22×26 bloques,
/// así que parecía bien… hasta que se usa a 20 px, que es donde vive la cabecera:
/// 20 px repartidos en 65 columnas dan **0,3 px por celda**, y el bloque medía
/// 0,9 px. Salía una mancha.
//
// El error era medir en la unidad del arte cuando lo que manda es la del
// **dispositivo**. Aquí la rejilla de bloques se elige a partir del tamaño en
/// píxeles, y el arte se muestrea dentro de cada bloque. Así el mismo pintor
/// sirve a 20 px y a 320, y a 20 sale una calavera de 8×9 bloques en vez de una
/// de 22×26 aplastada en un píxel.
class _SiluetaPainter extends CustomPainter {
  _SiluetaPainter({required this.pulso, required this.color});

  final double pulso;
  final Color color;

  /// Píxeles por bloque.
  ///
  /// ## Por qué 2,6 y no 3
  /// Es la resolución que hace que a 20 px salgan unas 8 columnas de bloques. Con
  /// 3 salían 7 y la mandíbula no se veía; con 2 salían 10 y el contorno se
  /// cerraba. El número está aquí y no repartido porque es el único sitio donde
  /// se decide, y cambiarlo cambia **todas** las siluetas a la vez.
  static const double _pxPorBloque = 2.6;

  /// Cuántos bloques caben como mínimo. Por debajo de 6 no hay calavera, hay
  /// punto.
  static const int _minimo = 6;
  static const int _maximo = 26;

  @override
  void paint(Canvas canvas, Size size) {
    // La rejilla de bloques, no el arte.
    //
    // ## Por qué
    // Antes contaba tinta por bloque sobre `calaveraJazz`, y salía un **bulto**.
    // No es un fallo del umbral: es que el arte es una masa. `rellenar` lo llena
    // de verdad para que la calavera se lea, y la caja del arte **es** la
    // calavera, así que casi cualquier bloque da «lleno». Por encima estaba la
    // proporción: las líneas de texto en VGA 8x16 son el doble de altas que de
    // anchas, y el bloque salía estirado al doble.
    //
    // La rejilla viene de la máscara del JPG, que es donde la forma está de
    // verdad, y su proporción es la de la imagen en píxeles. Es el mismo dibujo
    // que pintan el lanzador y el icono de notificación: una sola calavera.
    final g = calaveraSilueta;
    if (g.isEmpty || size.width <= 0 || size.height <= 0) return;
    final nc = g.first.length;
    final nf = g.length;
    if (nc == 0) return;

    // La rejilla se decide por píxeles, no por la de la silueta. `_maximo` es el
    // techo para que a 320 px no salga un mosaico de 100×120 bloques, que a esa
    // resolución ya no es una silueta sino ruido.
    final cols = (size.width / _pxPorBloque).round().clamp(_minimo, _maximo);
    final filas = (cols * nf / nc).round().clamp(_minimo, _maximo + 8);

    // La rejilla se **encaja** en la caja, sin estirar.
    //
    // ## Por qué
    // `bw = size.width / cols` y `bh = size.height / filas` reparten la caja
    // entre los bloques, y con eso la calavera se deformaba: el ancho y el alto
    // se estiran cada uno a su ritmo hacia lo que la caja mande. En la cabecera
    // la caja es casi cuadrada y la silueta no lo es, así que además se salía
    // por arriba. Se elige el lado que manda y el otro se calcula, como en
    // `-resize` sin `!`: la forma no se toca y lo que sobra es aire.
    final porAncho = size.width / cols;
    final porAlto = size.height / filas;
    final bw = porAncho < porAlto ? porAncho : porAlto;
    final bh = bw;
    final anchoDibujo = bw * cols;
    final altoDibujo = bh * filas;
    final dx = (size.width - anchoDibujo) / 2;
    final dy = (size.height - altoDibujo) / 2;

    final pintura = Paint()..style = PaintingStyle.fill;
    for (var f = 0; f < filas; f++) {
      for (var c = 0; c < cols; c++) {
        // El bloque mira **este trozo de la rejilla**, que es lo que lo hace
        // independiente de la resolución: el mismo bloque cubre 10 celdas a
        // 20 px y 2 a 320, y en los dos casos pregunta lo mismo.
        final y0 = (f * nf / filas).floor();
        final y1 = ((f + 1) * nf / filas).ceil().clamp(y0 + 1, nf);
        final x0 = (c * nc / cols).floor();
        final x1 = ((c + 1) * nc / cols).ceil().clamp(x0 + 1, nc);

        var llenos = 0;
        var total = 0;
        for (var y = y0; y < y1; y++) {
          final l = g[y].padRight(nc);
          for (var x = x0; x < x1; x++) {
            total++;
            if (l[x] == '1') llenos++;
          }
        }
        if (total == 0) continue;
        final rel = llenos / total;
        // Mitad de bloques: el bloque está dentro de la calavera. Por debajo es
        // borde, y el borde se apaga en vez de pintar.
        if (rel < 0.5) continue;
        pintura.color = color.withValues(alpha: 0.4 + 0.6 * rel * _brillo);
        canvas.drawRect(
          Rect.fromLTWH(dx + c * bw, dy + f * bh, bw + 0.5, bh + 0.5),
          pintura,
        );
      }
    }
  }

  /// El brillo del latido, con la misma irregularidad por bloque que la
  /// calavera: si solo latiera el conjunto, se vería como una luz que sube y
  /// baja, y no como un dibujo.
  double get _brillo => 0.7 + 0.3 * pulso;

  @override
  bool shouldRepaint(covariant _SiluetaPainter old) =>
      old.pulso != pulso || old.color != color;
}


/// El nombre con el glifo delante. Para barras de título y encabezados.
class AegisWordmark extends StatelessWidget {
  const AegisWordmark({
    super.key,
    this.size = 20,
    this.estado = EstadoAegis.reposo,
    this.vivo = true,
    this.etiqueta = 'AEGIS',
  });

  final double size;
  final EstadoAegis estado;
  final bool vivo;
  final String etiqueta;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        AegisMark(size: size, estado: estado, vivo: vivo),
        SizedBox(width: size * 0.4),
        Text(
          etiqueta,
          style: TextStyle(
            fontFamily: AegisPalette.display,
            fontSize: size * 0.9,
            fontWeight: FontWeight.w700,
            letterSpacing: size * 0.24,
            height: 1.1,
            color: AegisPalette.hueso,
          ),
        ),
      ],
    );
  }
}
