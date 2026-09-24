/// Pantalla de arranque estilo DedSec (secuencia de inicialización).
library;

import 'package:flutter/material.dart';

import '../theme/dedsec_colors.dart';
import 'aegis_logo.dart';
import 'blink_cursor.dart';

class BootScreen extends StatefulWidget {
  const BootScreen({super.key, required this.child});

  final Widget child;

  @override
  State<BootScreen> createState() => _BootScreenState();
}

class _BootScreenState extends State<BootScreen> {
  bool _ready = false;

  @override
  void initState() {
    super.initState();
    Future<void>.delayed(const Duration(milliseconds: 1400), () {
      if (mounted) setState(() => _ready = true);
    });
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 450),
      child: _ready ? widget.child : const _BootUi(key: ValueKey('boot')),
    );
  }
}

class _BootUi extends StatelessWidget {
  const _BootUi({super.key});

  @override
  Widget build(BuildContext context) {
    final line = TextStyle(
      fontFamily: DedsecColors.mono,
      fontSize: 12,
      color: DedsecColors.fgDim,
      height: 1.7,
    );
    return ColoredBox(
      color: DedsecColors.bg0,
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisSize: MainAxisSize.min,
              children: const [
                AegisLogo(size: 26),
                SizedBox(width: 12),
                Text(
                  'A E G I S',
                  style: TextStyle(
                    fontFamily: DedsecColors.display,
                    fontSize: 24,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 6,
                    color: DedsecColors.fg,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 20),
            Text('> mesh init', style: line),
            Text('> handshake … ok', style: line),
            Text('> auth … ok', style: line),
            Text('> entrada: concedida', style: line),
            const SizedBox(height: 12),
            const Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  '> ',
                  style: TextStyle(fontFamily: DedsecColors.mono, fontSize: 12, color: DedsecColors.fgDim),
                ),
                BlinkCursor(size: 12),
              ],
            ),
          ],
        ),
      ),
    );
  }
}