// El arranque cuando el puente **tarda**: lo que pasa de verdad por la malla.
//
// ## Por qué hay un test del arranque lento
// El arranque tenía dos condiciones que eran la misma comparación sobre una lista
// que **cambia** cuando contesta el puente. Con la red local contestaba antes del
// primer salto y todobien; por la malla, no. La secuencia que lo colgaba:
//
//   t=0     salud = cargando   -> 1 línea    ·  arranca la cadena
//   t=640   2 > 1             ->  entregado  ·  la cadena para
//   t=900   llega la respuesta -> 3 líneas   ->  2 > 3 = falso
//
// y el arranque **retrocedía** a la pantalla de carga con la cadena ya muerta. En
// el teléfono real eso era «AEGIS · puente: contesta · hermes: arrancado» y un
// cursor, para siempre. El emulador nunca lo vio, que es exactamente por lo que
// hace falta el test: **el fallo solo existe donde la red es lenta.**
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aegis_console/app.dart';
import 'package:aegis_console/core/widgets/boot_screen.dart';
import 'package:aegis_console/data/models/agent_models.dart';
import 'package:aegis_console/presentation/providers/agent_providers.dart';

import 'fake_repository.dart';

/// El mismo repositorio, pero `health()` tarda como tarda de verdad.
class _Lento extends FakeAgentRepository {
  _Lento(this.demora);
  final Duration demora;

  @override
  Future<BridgeHealth> health() async {
    await Future<void>.delayed(demora);
    return super.health();
  }
}

void main() {
  // Los tres momentos que importan: antes del primer salto (640 ms), justo
  // después (900 ms) y mucho después.
  for (final demora in const [
    Duration(milliseconds: 200),
    Duration(milliseconds: 900),
    Duration(milliseconds: 2500),
  ]) {
    testWidgets('con el puente lento (${demora.inMilliseconds} ms) el arranque '
        'termina', (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [agentRepositoryProvider.overrideWithValue(_Lento(demora))],
          child: const AegisApp(),
        ),
      );
      for (var i = 0; i < 80; i++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      expect(find.text('Ahora'), findsWidgets,
          reason: 'la app tiene que llegar al shell, no quedarse en el arranque');
    });
  }

  testWidgets('una lista que crece NO devuelve el arranque al principio',
      (tester) async {
    // La forma mínima del mismo fallo: el arranque entrega, y luego llegan más
    // líneas. Si entrega «de verdad», no puede volver atrás.
    var lineas = ['preguntando al puente…'];
    late StateSetter cambiar;

    await tester.pumpWidget(
      MaterialApp(
        home: StatefulBuilder(
          builder: (context, setState) {
            cambiar = setState;
            return BootScreen(
              saludo: 'Desperté.',
              lineas: lineas,
              child: const Scaffold(body: Text('SHELL')),
            );
          },
        ),
      ),
    );

    for (var i = 0; i < 4; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    // Más tarde de lo que el arranque ya había entregado, y con más líneas.
    cambiar(() => lineas = ['puente', 'hermes', 'ollama', 'modelos']);
    for (var i = 0; i < 40; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }

    expect(find.text('SHELL'), findsOneWidget,
        reason: 'el arranque tiene que terminar aunque la lista crezca después');
  });
}
