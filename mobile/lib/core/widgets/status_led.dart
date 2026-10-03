/// LED de estado con glow y pulso opcional.
library;

import 'package:flutter/material.dart';

class StatusLed extends StatefulWidget {
  const StatusLed({super.key, required this.color, this.size = 10, this.pulse = false});

  final Color color;
  final double size;
  final bool pulse;

  @override
  State<StatusLed> createState() => _StatusLedState();
}

class _StatusLedState extends State<StatusLed> with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
      lowerBound: 0,
      upperBound: 1,
    );
    if (widget.pulse) _controller.repeat(reverse: true);
  }

  @override
  void didUpdateWidget(covariant StatusLed old) {
    super.didUpdateWidget(old);
    if (widget.pulse && !_controller.isAnimating) {
      _controller.repeat(reverse: true);
    } else if (!widget.pulse && _controller.isAnimating) {
      _controller..stop()..value = 1;
    }
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
      builder: (_, _) {
        final v = widget.pulse ? _controller.value : 1.0;
        return SizedBox.square(
          dimension: widget.size,
          child: Stack(
            alignment: Alignment.center,
            children: [
              Container(
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  boxShadow: [
                    BoxShadow(
                      color: widget.color.withValues(alpha: .55),
                      blurRadius: widget.size * 0.9,
                    ),
                  ],
                ),
              ),
              Container(
                width: widget.size * 0.6,
                height: widget.size * 0.6,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: widget.color,
                ),
              ),
              if (widget.pulse)
                Container(
                  width: widget.size * (1 + v * 0.6),
                  height: widget.size * (1 + v * 0.6),
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    border: Border.all(
                      color: widget.color.withValues(alpha: .35 * (1 - v)),
                    ),
                  ),
                ),
            ],
          ),
        );
      },
    );
  }
}
