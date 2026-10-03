/// Cursor de bloque parpadeante estilo terminal.
library;

import 'package:flutter/material.dart';

import '../theme/aegis_palette.dart';

class BlinkCursor extends StatefulWidget {
  const BlinkCursor({super.key, this.color = AegisPalette.brand, this.size = 13});

  final Color color;
  final double size;

  @override
  State<BlinkCursor> createState() => _BlinkCursorState();
}

class _BlinkCursorState extends State<BlinkCursor>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 520),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (_, _) => Opacity(
        opacity: 0.15 + 0.85 * _controller.value,
        child: Text(
          '▌',
          style: TextStyle(
            fontFamily: AegisPalette.mono,
            fontSize: widget.size,
            color: widget.color,
            height: 1,
          ),
        ),
      ),
    );
  }
}
