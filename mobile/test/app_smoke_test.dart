// Humo de la app entera: arranca, muestra la marca y deja cambiar de sección.
//
// ## Por qué esto no prueba la app
// No la prueba. Prueba que **monta**: que el árbol de widgets se construye sin
// excepción, que el arranque termina y que el shell navega. Una prueba que
//bara más cosas de las que puede ver acaba no probando nada (A-016 aplicado a
// los tests): por eso el repo de red está falseado y aquí no se afirma nada del
// comportamiento del agente.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aegis_console/app.dart';
import 'package:aegis_console/presentation/providers/agent_providers.dart';

import 'fake_repository.dart';

void main() {
  Future<void> montar(WidgetTester tester, {FakeAgentRepository? repo}) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          agentRepositoryProvider.overrideWithValue(repo ?? FakeAgentRepository()),
        ],
        child: const AegisApp(),
      ),
    );
    for (var i = 0; i < 12; i++) {
      await tester.pump(const Duration(milliseconds: 320));
    }
    await tester.pump(const Duration(milliseconds: 600));
  }

  testWidgets('arranca y muestra el shell', (tester) async {
    await montar(tester);

    expect(find.text('AEGIS'), findsOneWidget);
    // El nombre de la sección activa aparece dos veces: en la barra y, dentro
    // de la propia sección, en su contenido.
    expect(find.text('Ahora'), findsWidgets);

    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('la barra deja ir a las otras secciones', (tester) async {
    await montar(tester);

    for (final seccion in ['Misiones', 'Ajustes']) {
      await tester.tap(find.text(seccion).last);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.text(seccion), findsWidgets,
          reason: 'no se quedó en $seccion');
    }

    // Y se vuelve a la primera sin perder el árbol.
    await tester.tap(find.text('Ahora').last);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('Encargar'), findsOneWidget);

    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('sin bridge, Ahora explica en vez de quedarse muda',
      (tester) async {
    await montar(tester, repo: FakeAgentRepository(fallaHealth: true));

    expect(find.text('No llego al puente'), findsWidgets);

    await tester.pumpWidget(const SizedBox());
  });
}
