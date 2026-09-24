/// Superposición global tipo DedSec: scanlines + barrido de datos.
library;

import 'package:flutter/material.dart';

import '../theme/dedsec_colors.dart';

class HudOverlay extends StatefulWidget {
  const HudOverlay({super.key, this.opacity = 0.4, this.density = 3.0});

  final double opacity;
  final double density;

  @override
  State<HudOverlay> createState() => _HudOverlayState();
}

class _HudOverlayState extends State<HudOverlay>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 5200),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: RepaintBoundary(
        child: AnimatedBuilder(
          animation: _controller,
          builder: (_, _) => CustomPaint(
            size: Size.infinite,
            painter: _HudOverlayPainter(
              progress: _controller.value,
              opacity: widget.opacity * 0.25,
              density: widget.density,
            ),
          ),
        ),
      ),
    );
  }
}

class _HudOverlayPainter extends CustomPainter {
  const _HudOverlayPainter({
    required this.opacity,
    required this.density,
    required this.progress,
  });

  final double opacity;
  final double density;
  final double progress;

  @override
  void paint(Canvas canvas, Size size) {
    final lines = Paint()
      ..color = const Color(0xFF000000).withValues(alpha: opacity)
      ..strokeWidth = 1;
    for (var y = 0.0; y < size.height; y += density) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), lines);
    }

    final sweep = Paint()..color = DedsecColors.brand.withValues(alpha: 0.05);
    final bandH = size.height * 0.06;
    final y = progress * size.height;
    canvas.drawRect(Rect.fromLTWH(0, y, size.width, bandH), sweep);
  }

  @override
  bool shouldRepaint(covariant _HudOverlayPainter old) =>
      old.progress != progress ||
      old.opacity != opacity ||
      old.density != density;
}