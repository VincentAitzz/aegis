/// Glifo de marca Aegis: escudo abierto con un núcleo vivo.
///
/// ## Por qué no es un anillo con nodos
/// La versión anterior era una triada dentro de un anillo: era el emblema de otra
/// marca, dibujado con otra métrica. Esta es una pieza propia y hace una cosa que
/// la anterior no hacía: **el núcleo late**. Aegis no está encendido o apagado,
/// está despierto, y el glifo lo dice antes de que abras nada.
///
/// ## Dibujo
/// Un anillo abierto por abajo, como un escudo o una casquete, y dentro un punto
/// con su halo. El hueco de abajo es lo que lo distingue de un anillo: parece
/// algo que protege, no un objetivo.
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../core/theme/aegis_palette.dart';

/// Cuánto brilla el núcleo. 0 apagado, 1 al máximo.
class AegisMark extends StatefulWidget {
  const AegisMark({
    super.key,
    this.size = 28,
    this.color,
    this.vivo = true,
  });

  final double size;
  final Color? color;
  final bool vivo;

  @override
  State<AegisMark> createState() => _AegisMarkState();
}

class _AegisMarkState extends State<AegisMark> with SingleTickerProviderStateMixin {
  late final AnimationController _c;

  @override
  void initState() {
    super.initState();
    _c = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2200),
    );
    if (widget.vivo) _c.repeat(reverse: true);
  }

  @override
  void didUpdateWidget(covariant AegisMark old) {
    super.didUpdateWidget(old);
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
    final color = widget.color ?? AegisPalette.brand;
    return SizedBox.square(
      dimension: widget.size,
      child: AnimatedBuilder(
        animation: _c,
        builder: (_, _) => CustomPaint(
          painter: _MarkPainter(color: color, pulso: widget.vivo ? _c.value : 1.0),
        ),
      ),
    );
  }
}

class _MarkPainter extends CustomPainter {
  const _MarkPainter({required this.color, required this.pulso});

  final Color color;

  /// 0..1. El núcleo se agranda y se encoge con este valor: es el latido.
  final double pulso;

  @override
  void paint(Canvas canvas, Size size) {
    final c = Offset(size.width / 2, size.height / 2);
    final r = size.width / 2;

    // El escudo: un anillo con un hueco abajo. El hueco no es decorativo; es lo
    // que hace que se lea como casquete y no como diana.
    final trazo = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = r * 0.13
      ..strokeCap = StrokeCap.round
      ..color = color;
    const hueco = 0.62; // radianes de apertura a cada lado del eje vertical
    canvas.drawArc(
      Rect.fromCircle(center: c, radius: r * 0.72),
      math.pi / 2 + hueco,
      2 * math.pi - 2 * hueco,
      false,
      trazo,
    );

    // El núcleo: un disco con halo, que late.
    final radio = r * (0.19 + 0.035 * pulso);
    canvas.drawCircle(
      c,
      radio * 2.4,
      Paint()..color = color.withValues(alpha: 0.10 + 0.12 * pulso),
    );
    canvas.drawCircle(c, radio, Paint()..color = color);
  }

  @override
  bool shouldRepaint(covariant _MarkPainter old) =>
      old.color != color || old.pulso != pulso;
}

/// El nombre, con el glifo delante. Para barras de título y encabezados.
class AegisWordmark extends StatelessWidget {
  const AegisWordmark({
    super.key,
    this.size = 20,
    this.color,
    this.vivo = true,
    this.etiqueta = 'AEGIS',
  });

  final double size;
  final Color? color;
  final bool vivo;
  final String etiqueta;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        AegisMark(size: size, color: color, vivo: vivo),
        SizedBox(width: size * 0.4),
        Text(
          etiqueta,
          style: TextStyle(
            fontFamily: AegisPalette.display,
            fontSize: size * 0.9,
            fontWeight: FontWeight.w700,
            letterSpacing: size * 0.24,
            height: 1.1,
            color: color ?? AegisPalette.fg,
          ),
        ),
      ],
    );
  }
}
