// Un solo canal: la pantalla de Ahora no pregunta por qué motor, y decide sola
// si el run lleva la puerta de verificación.
//
// ## El fallo que esto cubre
//
// **El selector de motor.** Había un `SegmentedButton` con HERMES y AUTOPILOT, y
// la decisión de cuál pulsar era lo primero que se cruzaba al encargar algo. Los
// dos llegaban a las mismas 18 tools de `mcp_ops.py`: Hermes por MCP, el
// autopilot llamándolas en proceso. O sea que el interruptor no elegía una
// capacidad, elegía en qué proceso vivía el bucle —y el bucle es lo que decide
// qué guardarraíl se aplica. Dos motores son dos sitios donde un guardarraíl
// puede vivir, y el que se ejecución acababa en Hermes era el que no los tenía.
// La pantalla perdió el interruptor y ya no hay nada que elegir.
//
// **La puerta de verificación.** El móvil mandaba `verificar: false` fijo, así
// que desde el teléfono **ninguna escritura pasaba por el verificador**, ni en un
// proyecto que la persona había marcado como escribible. La ruta de `curl` sí lo
// hacía: el mismo encargo se verificaba o no según desde dónde saliera. Ahora la
// puerta sale de si el proyecto está marcado, que es el dato que ya estaba en
// `/autonomy`.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aegis_console/data/models/asistente_models.dart';
import 'package:aegis_console/presentation/pages/ahora_page.dart';
import 'package:aegis_console/presentation/providers/agent_providers.dart';

import 'fake_repository.dart';

void main() {
  Future<FakeAgentRepository> montar(
    WidgetTester tester,
    FakeAgentRepository repo,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [agentRepositoryProvider.overrideWithValue(repo)],
        child: const MaterialApp(home: Scaffold(body: AhoraPage())),
      ),
    );
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 320));
    }
    return repo;
  }

  Future<void> encargar(WidgetTester tester, String texto) async {
    await tester.enterText(find.byType(TextField).first, texto);
    await tester.pump();
    await tester.tap(find.text('Encargar'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
  }

  /// El campo de buscar de la hoja.
  ///
  /// Por hint y no por posición: con la hoja abierta hay dos `TextField` en el
  /// árbol —el buscador y el del encargo, que está debajo— y `.first` cogía el
  /// equivocado, así que el test escribía el encargo y no filtraba nada.
  Finder buscador() => find.byWidgetPredicate(
      (w) => w is TextField && w.decoration?.hintText == 'Buscar proyecto…');

  /// Un proyecto **dentro de la hoja**.
  ///
  /// Sin acotar, `find.text('aegis')` encuentra dos: la fila de la pantalla que
  /// hay detrás —que dice el proyecto activo— y la de la hoja. Un finder que no
  /// distingue dónde está no está probando el filtro.
  Finder enHoja(String alias) =>
      find.descendant(of: find.byType(ListTile), matching: find.text(alias));

  Future<void> abrirHoja(WidgetTester tester) async {
    // Por la clave y no por el icono: la pantalla tiene dos `expand_more` y sin
    // esto el finder es ambiguo (y el error sale aqui, no en un test de verdad).
    await tester.tap(find.byKey(const Key('aegis.proyecto')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
  }

  Future<void> elegirProyecto(WidgetTester tester, String alias) async {
    await abrirHoja(tester);
    await tester.tap(enHoja(alias));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
  }

  group('no queda elección de motor', () {
    testWidgets('no hay interruptor HERMES/AUTOPILOT', (tester) async {
      await montar(tester, FakeAgentRepository());
      // Ni en mayúsculas (como estaba el botón) ni en ninguno de los dos
      // términos. Un `findsNothing` es la forma de afirmar que una opción ya no
      // existe; si vuelve a aparecer, este test falla.
      expect(find.text('HERMES'), findsNothing);
      expect(find.text('AUTOPILOT'), findsNothing);
      expect(find.textContaining('Hermes'), findsNothing);
    });

    testWidgets('encargar lanza el autopilot sin preguntar nada más', (
      tester,
    ) async {
      final repo = await montar(tester, FakeAgentRepository());
      await encargar(tester, 'lista los proyectos');
      // Un solo camino: el campo, el proyecto y ya. Si hubiera dos motores, aquí
      // habría que comprobar cuál salió.
      expect(repo.promptsLanzados, ['lista los proyectos']);
    });
  });

  group('la puerta de verificación sale del permiso, no de un interruptor', () {
    testWidgets('sin proyecto no hay puerta que cerrar', (tester) async {
      final repo = await montar(tester, FakeAgentRepository());
      await encargar(tester, 'dime qué hay en el disco');
      expect(repo.proyectosLanzados, isEmpty);
      expect(repo.verificacionesLanzadas, [false]);
    });

    testWidgets('proyecto marcado: el run sale con puerta', (tester) async {
      final repo = await montar(tester, FakeAgentRepository()
        ..autonomiaFake = const Autonomia(
          modo: 'permiso',
          escritura: {'aegis': 'escritura'},
        ));
      await elegirProyecto(tester, 'aegis');

      await encargar(tester, 'arregla el verificador');

      expect(repo.proyectosLanzados, ['aegis']);
      // Esto es lo que estaba roto: el móvil mandaba `false` siempre.
      expect(repo.verificacionesLanzadas, [true]);
    });

    testWidgets('proyecto sin marcar: sin puerta, y se dice por qué', (
      tester,
    ) async {
      final repo = await montar(tester, FakeAgentRepository());
      // `compra-unida` sale en la hoja con su color de ficha: sin ficha, Aegis no
      // puede escribir. Elegirlo no pone la puerta porque no puede escribir.
      await elegirProyecto(tester, 'compra-unida');
      await encargar(tester, 'lee su esquema');
      expect(repo.proyectosLanzados, ['compra-unida']);
      expect(repo.verificacionesLanzadas, [false]);
    });
  });

  group('la hoja de proyectos filtra de verdad', () {
    testWidgets('«solo escribibles» deja fuera lo no marcado', (tester) async {
      await montar(tester, FakeAgentRepository()
        ..autonomiaFake = const Autonomia(escritura: {'aegis': 'escritura'}));
      await abrirHoja(tester);

      expect(enHoja('aegis'), findsOneWidget);
      expect(enHoja('compra-unida'), findsOneWidget);
      expect(enHoja('data-sending'), findsOneWidget);

      await tester.tap(find.text('solo escribibles'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 320));

      expect(enHoja('aegis'), findsOneWidget);
      // Los otros dos están, pero no marcados: el filtro es de permiso de
      // escritura, no de "los que tienen ficha".
      expect(enHoja('compra-unida'), findsNothing);
      expect(enHoja('data-sending'), findsNothing);
    });

    testWidgets('el buscador reduce la lista', (tester) async {
      await montar(tester, FakeAgentRepository());
      await abrirHoja(tester);
      await tester.enterText(buscador(), 'compra');
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 320));

      expect(enHoja('compra-unida'), findsOneWidget);
      expect(enHoja('aegis'), findsNothing);
      expect(enHoja('data-sending'), findsNothing);
    });

    testWidgets('cerrar la hoja no cambia de proyecto', (tester) async {
      final repo = await montar(tester, FakeAgentRepository());
      await abrirHoja(tester);
      // Cerrar con la llave de atrás devuelve `null`, que **no** es lo mismo que
      // `''`: un cierre accidental no puede cambiar a dónde va a trabajar el
      // siguiente encargo.
      await tester.tapAt(const Offset(20, 100));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      await encargar(tester, 'lee algo');
      expect(repo.proyectosLanzados, isEmpty);
    });
  });

}
