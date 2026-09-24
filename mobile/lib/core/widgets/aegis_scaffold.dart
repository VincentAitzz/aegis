/// Scaffold global Aegis: aplica el overlay DedSec sobre cualquier página.
library;

import 'package:flutter/material.dart';

import '../theme/dedsec_colors.dart';
import 'hud_overlay.dart';

class AegisScaffold extends StatelessWidget {
  const AegisScaffold({
    super.key,
    this.appBar,
    required this.body,
    this.bottomNavigationBar,
  });

  final PreferredSizeWidget? appBar;
  final Widget body;
  final Widget? bottomNavigationBar;

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        Positioned.fill(
          child: Scaffold(
            backgroundColor: DedsecColors.bg0,
            appBar: appBar,
            body: body,
            bottomNavigationBar: bottomNavigationBar,
          ),
        ),
        const IgnorePointer(child: HudOverlay()),
      ],
    );
  }
}