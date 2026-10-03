/// Panel estilo HUD con esquinas en L y cabecera [ TÍTULO ].
library;

import 'package:flutter/material.dart';

import '../theme/aegis_palette.dart';

class HudPanel extends StatelessWidget {
  const HudPanel({
    super.key,
    required this.title,
    this.child,
    this.accent = AegisPalette.brand,
    this.trailing,
    this.padding = const EdgeInsets.all(14),
  });

  final String title;
  final Widget? child;
  final Widget? trailing;
  final Color accent;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: AegisPalette.bg1,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AegisPalette.line),
      ),
      child: Stack(
        children: [
          Positioned.fill(
            child: IgnorePointer(
              child: CustomPaint(
                painter: _CornersPainter(accent),
              ),
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(14, 10, 14, 8),
                child: Row(
                  children: [
                    Text(
                      '[$title]',
                      style: TextStyle(
                        fontFamily: AegisPalette.mono,
                        fontSize: 11,
                        letterSpacing: 2,
                        color: accent,
                      ),
                    ),
                    const Spacer(),
                    ?trailing,
                  ],
                ),
              ),
              Divider(
                color: AegisPalette.brand.withValues(alpha: .25),
                height: 1,
              ),
              if (child != null) Padding(padding: padding, child: child),
            ],
          ),
        ],
      ),
    );
  }
}

class _CornersPainter extends CustomPainter {
  const _CornersPainter(this.color);

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color.withValues(alpha: .7)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5;
    const len = 9.0;
    final pairs = <List<List<Offset>>>[
      [[const Offset(0, 0), const Offset(len, 0)], [const Offset(0, 0), const Offset(0, len)]],
      [[Offset(size.width, 0), Offset(size.width - len, 0)], [Offset(size.width, 0), Offset(size.width, len)]],
      [[Offset(0, size.height), Offset(len, size.height)], [Offset(0, size.height), Offset(0, size.height - len)]],
      [[Offset(size.width, size.height), Offset(size.width - len, size.height)], [Offset(size.width, size.height), Offset(size.width, size.height - len)]],
    ];
    for (final pair in pairs) {
      for (final seg in pair) {
        canvas.drawLine(seg[0], seg[1], paint);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _CornersPainter old) => old.color != color;
}
