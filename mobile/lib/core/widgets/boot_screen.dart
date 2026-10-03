/// Arranque de Aegis.
///
/// ## Por qué esto no dice "todo listo"
/// La versión anterior imprimía `handshake … ok`, `auth … ok` y `entrada:
/// concedida` antes de haber comprobado nada: era un texto, y se pintaba de
/// algo que no se había visto. Es A-016 puesto delante del usuario —un sistema
/// que reporta verde sin comprobar— y por eso hay que arreglarlo aunque se vea
/// bonito.
///
/// Ahora cada línea dice **una de dos cosas**: o lo que Aegis sabe de verdad
/// porque lo ha comprobado, o que aún no lo sabe. La línea de abajo se queda
/// pensando hasta que la primera pantalla le diga lo que ve de verdad, y por eso
/// no desaparece a los 1,4 s como antes.
///
/// ## Por qué esto también es una decisión de identidad
/// Un asistente que miente en su primer segundo te enseña que todo lo demás
/// puede ser inventado. La honestidad del arranque es la forma más barata de
/// ganar la confianza que hace falta para que le pidas cosas en serio.
///
/// ## Por qué no hay ASCII
/// El cráneo de la versión anterior era el emblema de otra marca. Fuera.
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../theme/aegis_palette.dart';
import 'aegis_mark.dart';
import 'blink_cursor.dart';

class BootScreen extends StatefulWidget {
  const BootScreen({
    super.key,
    required this.child,
    required this.saludo,
    this.lineas = const [],
  });

  final Widget child;

  /// Lo que Aegis dice al despertar. Viene de quien sabe el estado real: si el
  /// puente no contesta, aquí no se dice que está listo.
  final String saludo;

  /// Lo que ya se sabe de verdad, en el orden en que se sabe.
  final List<String> lineas;

  @override
  State<BootScreen> createState() => _BootScreenState();
}

class _BootScreenState extends State<BootScreen>
    with SingleTickerProviderStateMixin {
  late final AnimationController _crecer;
  Timer? _salto;
  int _vistas = 0;

  @override
  void initState() {
    super.initState();
    _crecer = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 700),
    )..forward();
    _siguiente();
  }

  /// Una línea cada 320 ms, y luego la pantalla.
  ///
  /// `mounted` antes de `setState`: el temporizador sobrevive al frame en que la
  /// ruta ya se está cerrando, y sin esto salta la excepción de "setState after
  /// dispose" en el arranque, que es justo la primera vez que se abre la app.
  void _siguiente() {
    _salto = Timer(const Duration(milliseconds: 320), () {
      if (!mounted) return;
      setState(() => _vistas++);
      if (_vistas <= widget.lineas.length) {
        _siguiente();
      }
    });
  }

  @override
  void dispose() {
    _salto?.cancel();
    _crecer.dispose();
    super.dispose();
  }

  bool get _terminado => _vistas > widget.lineas.length;

  @override
  Widget build(BuildContext context) {
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 450),
      child: _terminado
          ? widget.child
          : _ArranqueUi(
              key: const ValueKey('arranque'),
              saludo: widget.saludo,
              lineas: widget.lineas.take(_vistas).toList(),
              pct: _crecer,
            ),
    );
  }
}

class _ArranqueUi extends StatelessWidget {
  const _ArranqueUi({
    super.key,
    required this.saludo,
    required this.lineas,
    required this.pct,
  });

  final String saludo;
  final List<String> lineas;
  final Animation<double> pct;

  @override
  Widget build(BuildContext context) {
    final linea = TextStyle(
      fontFamily: AegisPalette.mono,
      fontSize: 11.5,
      color: AegisPalette.fgDim,
      height: 1.75,
    );
    return ColoredBox(
      color: AegisPalette.bg0,
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // El glifo crece desde pequeño: la primera señal de que hay alguien
            // despierto al otro lado, antes de que aparezca una sola palabra.
            FadeTransition(
              opacity: pct,
              child: ScaleTransition(
                scale: Tween<double>(begin: 0.86, end: 1).animate(
                  CurvedAnimation(parent: pct, curve: Curves.easeOutCubic),
                ),
                child: const AegisWordmark(size: 34),
              ),
            ),
            const SizedBox(height: 22),
            Text(saludo, style: linea),
            const SizedBox(height: 6),
            for (final l in lineas) Text('  $l', style: linea),
            const SizedBox(height: 10),
            const Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text('> ',
                    style: TextStyle(
                        fontFamily: AegisPalette.mono,
                        fontSize: 11.5,
                        color: AegisPalette.fgDim)),
                BlinkCursor(size: 12),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
