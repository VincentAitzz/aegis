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
    this.estado = EstadoAegis.reposo,
  });

  /// Lo que está haciendo Aegis. Lo pinta quien sabe, que es el `AegisApp` a
  /// través de la actividad.
  final EstadoAegis estado;

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

  /// El arranque ya entregó el paso a la app, y **no vuelve atrás**.
  ///
  /// ## Por qué existe: el fallo que collationaba el arranque entero
  /// Las dos condiciones —«¿enseño todas las líneas?» y «¿he terminado?»—
  /// eran la misma comparación sobre `lineas.length`, que **cambia** cuando
  /// contesta el puente. Con la malla de por medio pasa esto:
  ///
  /// ```
  /// t=0     salud = cargando      -> 1 línea   ·  arranca la cadena
  /// t=640   _vistas=2 > 1        ->  entregado ·  la cadena para
  /// t=900   llega la respuesta    -> 3 líneas  ->  2 > 3 = falso
  /// ```
  ///
  /// Y el arranque **retrocedía** a la pantalla de carga con la cadena ya muerta:
  /// el móvil se quedaba en «AEGIS / puente: contesta / hermes: arrancado» y un
  /// cursor parpadeando, para siempre. En el emulador no pasaba porque el puente
  /// contestaba antes del primer salto.
  ///
  /// ## Por qué no basta con reiniciar la cadena
  /// Porque el arranque no es un sitio donde enseñar datos: es una transición.
  /// Su trabajo es decir lo que se sabe **hasta ese momento** y pasar. Lo que
  /// llegue después lo enseña la pantalla real, que es la que tiene los datos
  /// frescos. Retroceder para añadir una línea que nadie ha pedido es peor que
  /// pasarse medio segundo antes.
  bool _entregado = false;

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
      // Solo mientras haya líneas nuevas que enseñar. En cuanto no las hay, se
      // entrega el paso **y no se vuelve a mirar**: ese "no volver a mirar" es
      // lo que impide que una respuesta que llega tarde deshaga la entrega.
      if (_vistas < widget.lineas.length) {
        _siguiente();
      } else {
        setState(() => _entregado = true);
      }
    });
  }

  @override
  void dispose() {
    _salto?.cancel();
    _crecer.dispose();
    super.dispose();
  }

  /// Una vez entregado, entregado. Ver la nota de `_entregado`.
  bool get _terminado => _entregado || _vistas > widget.lineas.length;

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
              estado: widget.estado,
            ),
    );
  }
}

/// El ancho que ocupa el bloque de la calavera.
///
/// ## Cuadrado a propósito, aunque el dibujo no lo sea
/// La calavera es más alta que ancha (0,44), así que en un cuadrado sobra aire a
/// los lados. Da igual: el aire es lo que la hace legible, y un bloque medido a
/// la medida del dibujo se nota en cada rotura de línea.
///
/// ## Por qué el glifo y la caja miden lo mismo
/// Porque `AegisMark` es un `SizedBox.square(dimension: size)`. Si la caja del
/// arranque mide 150 de ancho y se le pide 320, **el glifo se dibuja a 320 y se
/// sale**: la primera versión lo hacía así y el arte se montaba encima del texto
/// del arranque, que es el peor sitio posible para que algo se desborde.

const double _altoCalavera = 320.0;
const double _anchoCalavera = 320.0;

class _ArranqueUi extends StatelessWidget {
  const _ArranqueUi({
    super.key,
    required this.saludo,
    required this.lineas,
    required this.pct,
    required this.estado,
  });

  final String saludo;
  final List<String> lineas;
  final Animation<double> pct;

  /// Lo que está haciendo Aegis, para que la calavera tenga el mismo color que
  /// la de la cabecera. Sin esto, el arranque y el shell podrían estar los dos
  /// en magenta con el agente callado, y no habría forma de saber cuál mintió.
  final EstadoAegis estado;

  @override
  Widget build(BuildContext context) {
    const rotulo = TextStyle(
      fontFamily: AegisPalette.display,
      fontSize: 17,
      fontWeight: FontWeight.w700,
      letterSpacing: 5,
      color: AegisPalette.hueso,
    );
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
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            // La calavera, grande. Aquí sí cabe el arte entero: son 77 renglones
            // y hacen falta más de 300 px para que un carácter se lea, y esta es
            // la única superficie de la app donde se puede.
            //
            // Crece desde pequeño: la primera señal de que hay alguien despierto
            // al otro lado, antes de que aparezca una sola palabra.
            SizedBox(
              height: _altoCalavera,
              width: _anchoCalavera,
              child: FadeTransition(
                opacity: pct,
                child: ScaleTransition(
                  scale: Tween<double>(begin: 0.86, end: 1).animate(
                    CurvedAnimation(parent: pct, curve: Curves.easeOutCubic),
                  ),
                  child: AegisMark(size: 320, estado: estado),
                ),
              ),
            ),
            const SizedBox(height: 18),
            Center(child: Text('AEGIS', style: rotulo)),
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
