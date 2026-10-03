// La cabecera no se mete debajo de la barra del sistema, y los avisos tampoco.
//
// ## El fallo que esto cubre
//
// La cabecera del shell era un `Container` de 52 dp pelados dentro de
// `Scaffold.body`, sin `SafeArea`, y los dos avisos flotantes estaban clavados a
// `top: 52`. Dos bugs del mismo origen:
//
// 1. `Scaffold.body` no aplica el inset superior. En cualquier dispositivo con
//    barra de estado o muesca, la marca y los primeros píxeles de cada sección se
//    dibujaban **debajo** del reloj y de los iconos.
// 2. Los avisos dan por hecho que debajo de ellos empieza el contenido. No era
//    cierto en cuanto había inset: se montaban encima de la cabecera, tapando la
//    marca justo cuando peor se ven las cosas —sin puente, o esperando tu OK.
//
// El `AnnotatedRegion<SystemUiOverlayStyle>` que ya estaba arregla el **color**
// del texto del sistema, no el espacio. Se veía bien y aun así se solapaba.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aegis_console/data/models/agent_models.dart';
import 'package:aegis_console/presentation/providers/agent_providers.dart';
import 'package:aegis_console/presentation/shell/aegis_shell.dart';

import 'fake_repository.dart';

/// Lo que mide la cabecera: 52 dp de contenido más el inset de arriba.
const double _cuerpo = 52.0;

void main() {
  // Función y no getter: esto vive dentro del cuerpo de `main`, y Dart no
  // admite `get` en un cuerpo de función.
  Finder cabecera() => find.byKey(const Key('aegis.cabecera'));

  Future<void> montar(
    WidgetTester tester, {
    double top = 24,
    bool puente = true,
  }) async {
    // `view.padding` va en **píxeles físicos** y el `MediaQuery` que ve el widget
    // los divide por el ratio del dispositivo. Con el ratio por defecto de 3,
    // pedir 24 de status bar da 8 lógicos y el test mide otra cosa de la que
    // cree. Se fija a 1 para que físico y lógico sean lo mismo.
    tester.view.devicePixelRatio = 1.0;
    final pad = FakeViewPadding(top: top, bottom: 34);
    tester.view.padding = pad;
    tester.view.viewPadding = pad;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          agentRepositoryProvider.overrideWithValue(
            FakeAgentRepository(
              salud: BridgeHealth(
                ok: puente,
                host: 'test-host',
                hermesOk: true,
                ollamaOk: true,
                models: const ['qwen2.5-coder:7b'],
                agents: const ['worker'],
              ),
            ),
          ),
        ],
        child: const MaterialApp(home: AegisShell()),
      ),
    );
    for (var i = 0; i < 8; i++) {
      await tester.pump(const Duration(milliseconds: 320));
    }
  }

  testWidgets('la cabecera baja lo que baja la barra del sistema', (
    tester,
  ) async {
    await montar(tester, top: 24);
    // El `SafeArea` es el **padre** del `Container`, así que lo que se desplaza es
    // la caja, no su tamaño: siempre mide 52 y empieza 24 más abajo. Por eso el
    // reloj le caía encima —la caja arrancaba en 0— y no porque la caja fuera
    // más alta de lo debido.
    final caja = tester.getRect(cabecera());
    expect(caja.top, 24.0);
    expect(caja.height, _cuerpo);
  });

  testWidgets('sin inset, la caja se queda donde está', (tester) async {
    // El caso contrario importa tanto como el primero: si alguien "arregla" el
    // solape metiendo un padding fijo de 24 dentro del `Container`, este test
    // falla —y el del primero seguiría verde en un móvil sin muesca, que es
    // donde se nota tarde.
    await montar(tester, top: 0);
    final caja = tester.getRect(cabecera());
    expect(caja.top, 0.0);
    expect(caja.height, _cuerpo);
  });

  testWidgets('la marca no se dibuja bajo el reloj', (tester) async {
    await montar(tester, top: 24);
    // Se mide **la marca**, que es lo que el reloj tapaba, y no la caja: la caja
    // mediría el mismo con o sin el arreglo si el texto se compensara a mano.
    expect(tester.getRect(find.text('AEGIS')).top, greaterThanOrEqualTo(24.0));
  });

  testWidgets('la sección empieza donde acaba la cabecera', (tester) async {
    await montar(tester, top: 24);
    final r = tester.getRect(cabecera());
    // El campo de encargo es lo primero que hay que ver de la sección de Ahora.
    final campo = tester.getRect(find.byType(TextField).first);
    expect(
      campo.top,
      greaterThanOrEqualTo(r.bottom - 0.5),
      reason: 'el contenido se monta por encima del final de la cabecera',
    );
  });

  testWidgets('el aviso va debajo de la cabecera, no encima', (tester) async {
    // El bug era `top: 52` clavado: con inset, el aviso se montaba sobre la
    // marca. Sale justo cuando peor se ve la app, así que taparla ahí era lo
    // peor que podía hacer.
    await montar(tester, top: 24, puente: false);
    final r = tester.getRect(cabecera());
    final aviso = find.textContaining('Sin puente');
    expect(aviso, findsOneWidget);
    expect(
      tester.getRect(aviso).top,
      greaterThanOrEqualTo(r.bottom - 0.5),
      reason: 'el aviso tapa la cabecera en vez de ir debajo',
    );
  });
}
