/// La pantalla de la primera vez: explica, y pregunta si te dejan.
///
/// ## Por qué existe, y por qué no es un diálogo suelto
/// Porque el aviso de este repo —«un "¿permitir notificaciones?" en el primer
/// frame se contesta "no" casi siempre»— no va de la pantalla, va del
/// **contexto**. Un diálogo del sistema sin contexto se deniega; uno con la
/// explicación delante se contesta bien. Por eso cada permiso enseña su
/// párrafo **antes** de que salga el diálogo.
///
/// ## Por qué es saltable
/// Porque hay quien no quiere avisos, y una app a la que no se puede entrar sin
/// ellos deja de servir para lo único que importa aquí: **ver tus códigos**.
/// Un autenticador al que no puedes entrar porque no diste el permiso de
/// notificaciones es peor que un bloc de notas.
///
/// ## Por qué solo la primera vez, y por qué la lista es de ids
/// Android **deja de enseñar el diálogo** tras dos denegaciones: volver a
/// preguntar no abre nada, y un botón que no abre nada parece la app colgada.
/// Se guarda **qué identificadores** se han preguntado, no un «ya arrancó»: con
/// un booleano, un permiso nuevo no se preguntaría nunca. Con la lista, uno
/// nuevo se pregunta en su primera vez aunque la app se hubiera abierto mil
/// veces, y uno viejo no se repite.
library;

import 'package:flutter/material.dart';

import '../../core/permisos.dart';
import '../../core/theme/aegis_palette.dart';

class PrimeraVezPage extends StatefulWidget {
  const PrimeraVezPage({
    super.key,
    required this.faltan,
    required this.preguntar,
    required this.saltar,
    this.alResponder,
  });

  /// Los que todavía no se han preguntado, en orden.
  final List<PermisoApp> faltan;

  /// Anota uno como preguntado. Se llama al **preguntar**, no al conceder.
  final void Function(PermisoApp) preguntar;

  /// Entra a la app sin contestar nada, y no vuelve a preguntar.
  final VoidCallback saltar;

  /// Se llama **después** de que el sistema conteste, no antes.
  ///
  /// Va aparte de [preguntar] porque las dos cosas pasan en momentos distintos
  /// y confundirlas cuesta un fallo invisible: `preguntar` es «he lanzado la
  /// pregunta» —y se anota ya, para que nadie la repita—, mientras que esta es
  /// «ya hay veredicto», que es cuando tiene sentido volver a preguntar al
  /// sistema lo que ahora sabe.
  final VoidCallback? alResponder;

  @override
  State<PrimeraVezPage> createState() => _PrimeraVezPageState();
}

class _PrimeraVezPageState extends State<PrimeraVezPage> {
  int _i = 0;

  PermisoApp get _actual => widget.faltan[_i];
  bool get _ultimo => _i >= widget.faltan.length - 1;

  Future<void> _pedir() async {
    final p = _actual;
    // Se anota **antes** de esperar. El diálogo del sistema es asíncrono y su
    // respuesta llega después: si se anotara al volver, un permiso que alguien
    // no contesta se volvería a preguntar en el siguiente arranque, y Android
    // ya no enseñaría nada — parecería un botón roto.
    widget.preguntar(p);
    // El `await` no suelta hasta que hay respuesta: el canal del sistema
    // resuelve en `onRequestPermissionsResult`, no al lanzar el diálogo.
    await p.pedir();
    widget.alResponder?.call();
    if (!mounted) return;
    if (_ultimo) {
      widget.saltar();
      return;
    }
    setState(() => _i++);
  }

  void _saltarTodo() {
    for (final p in widget.faltan) {
      widget.preguntar(p);
    }
    widget.saltar();
  }

  @override
  Widget build(BuildContext context) {
    final p = _actual;

    return Scaffold(
      backgroundColor: AegisPalette.bg0,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(26, 28, 26, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'AEGIS',
                style: TextStyle(
                  fontFamily: AegisPalette.display,
                  fontSize: 13,
                  letterSpacing: 4,
                  color: AegisPalette.brand,
                ),
              ),
              const SizedBox(height: 22),
              Text(
                'Un par de cosas\nantes de empezar.',
                style: const TextStyle(
                  fontFamily: AegisPalette.display,
                  fontSize: 30,
                  height: 1.2,
                  color: AegisPalette.fg,
                ),
              ),
              const SizedBox(height: 26),
              // Los puntos de progreso. No son adorno: dicen que hay un
              // principio y un final, y sin eso un formulario de una sola
              // pantalla parece que se ha quedado a medias.
              Row(
                children: [
                  for (var i = 0; i < widget.faltan.length; i++)
                    Expanded(
                      child: Container(
                        height: 3,
                        margin: EdgeInsets.only(right: i == widget.faltan.length - 1 ? 0 : 6),
                        decoration: BoxDecoration(
                          color: i <= _i ? AegisPalette.brand : AegisPalette.line,
                          borderRadius: BorderRadius.circular(2),
                        ),
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 30),
              Text(
                p.paraQue,
                style: const TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 14,
                  height: 1.6,
                  color: AegisPalette.fg,
                ),
              ),
              const SizedBox(height: 18),
              // Qué se pierde sin concederlo, dicho de forma concreta: «puede
              // pasar algo malo» no informa; «no te vas a enterar» sí.
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 11),
                decoration: BoxDecoration(
                  color: AegisPalette.bg1,
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: AegisPalette.line),
                ),
                child: Text(
                  'Sin esto, Aegis funciona igual. No te avisa de nada.',
                  style: const TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 11.5,
                    height: 1.5,
                    color: AegisPalette.fgDim,
                  ),
                ),
              ),
              const Spacer(),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: _saltarTodo,
                      child: const Text('Ahora no'),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    flex: 2,
                    child: FilledButton(
                      onPressed: _pedir,
                      child: Text(_ultimo ? 'Empezar' : 'Sí, avísame'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              const Center(
                child: Text(
                  'Puedes cambiarlo después en Ajustes.',
                  style: TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 10,
                    color: AegisPalette.fgFaint,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}