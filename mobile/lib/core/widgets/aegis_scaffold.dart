/// Scaffold de Aegis: fondo, barra de título y la superposición de pantalla.
///
/// ## Por qué existe todavía
/// El shell (`AegisShell`) no lo usa: el shell es la pantalla de secciones y
/// compone la suya, porque necesita la barra de secciones debajo. Este queda
/// para las pantallas **que se empujan encima** —diagnóstico, detalle de misión—
/// donde sí hace falta una barra de título de Material con botón de atrás.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../theme/aegis_palette.dart';
import 'hud_overlay.dart';

class AegisScaffold extends StatelessWidget {
  const AegisScaffold({
    super.key,
    this.appBar,
    required this.body,
    this.bottomNavigationBar,
    this.superposicion = true,
  });

  final PreferredSizeWidget? appBar;
  final Widget body;
  final Widget? bottomNavigationBar;

  /// La superposición va sobre todo lo que se ve. En el diagnóstico se apaga:
  /// ahí se lee texto técnico pequeño y la textura solo resta.
  final bool superposicion;

  @override
  Widget build(BuildContext context) {
    return AnnotatedRegion<SystemUiOverlayStyle>(
      // Sin esto, el texto del sistema sale en negro sobre el fondo oscuro y
      // la barra de estado se vuelve invisible.
      value: const SystemUiOverlayStyle(
        statusBarColor: Colors.transparent,
        statusBarIconBrightness: Brightness.light,
        statusBarBrightness: Brightness.dark,
      ),
      child: Stack(
        children: [
          Scaffold(
            backgroundColor: AegisPalette.bg0,
            appBar: appBar,
            body: body,
            bottomNavigationBar: bottomNavigationBar,
          ),
          if (superposicion) const IgnorePointer(child: HudOverlay()),
        ],
      ),
    );
  }
}
