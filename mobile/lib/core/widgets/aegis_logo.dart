/// Glifo de marca Aegis: triada sigma dedsec-inspirada (anillo + 3 nodos).
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../core/theme/dedsec_colors.dart';

class AegisLogo extends StatelessWidget {
  const AegisLogo({super.key, this.size = 28, this.color});

  final double size;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    return SizedBox.square(
      dimension: size,
      child: CustomPaint(
        painter: _AegisMarkPainter(color ?? DedsecColors.fg),
      ),
    );
  }
}

class _AegisMarkPainter extends CustomPainter {
  const _AegisMarkPainter(this.color);

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final cx = size.width / 2;
    final cy = size.height / 2;
    final r = size.width / 2;

    final ring = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = r * 0.08
      ..color = color;
    canvas.drawCircle(Offset(cx, cy), r * 0.86, ring);

    final tick = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = r * 0.05
      ..color = color.withValues(alpha: .8);
    for (var i = 0; i < 8; i++) {
      final a = i * math.pi / 4;
      final inner = Offset(cx + math.cos(a) * r * 0.86, cy + math.sin(a) * r * 0.86);
      final outer = Offset(cx + math.cos(a) * r, cy + math.sin(a) * r);
      canvas.drawLine(outer, inner, tick);
    }

    final node = Paint()..color = color;
    final spoke = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = r * 0.06
      ..color = color.withValues(alpha: .9);
    for (var i = 0; i < 3; i++) {
      final a = -math.pi / 2 + i * 2 * math.pi / 3;
      final p = Offset(cx + math.cos(a) * r * 0.55, cy + math.sin(a) * r * 0.55);
      canvas.drawLine(p, Offset(cx, cy), spoke);
      canvas.drawCircle(p, r * 0.13, node);
    }
    canvas.drawCircle(Offset(cx, cy), r * 0.09, node);
  }

  @override
  bool shouldRepaint(covariant _AegisMarkPainter old) => old.color != color;
}