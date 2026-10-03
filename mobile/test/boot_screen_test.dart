// El arranque de Aegis: lo que dice, y sobre todo lo que no dice.
//
// ## Por qué hay un test del arranque
// El arranque anterior imprimía `handshake … ok`, `auth … ok` y `entrada:
// concedida` sin haber comprobado nada. Era A-016 puesto delante de la persona
// que usa la app: un sistema que reporta verde sin mirar. Estos tests miran las
// dos ramas —con puente y sin él— porque un arranque que solo dice la verdad
// cuando todo va bien no es un arranque honesto.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aegis_console/app.dart';
import 'package:aegis_console/presentation/providers/agent_providers.dart';

import 'fake_repository.dart';

void main() {
  /// Pump del arranque recogiendo **todos los textos que se han visto**.
  ///
  /// No basta con mirar al final: el arranque es transitorio, y comprobar solo
  /// el último frame es comprobar la app, no el arranque. Recoger en cada paso
  /// lo que había en pantalla es lo que permite afirmar que una frase se dijo,
  /// y también que **no** se dijo.
  Future<List<String>> arrancar(
    WidgetTester tester,
    FakeAgentRepository repo,
  ) async {
    final vistos = <String>[];
    await tester.pumpWidget(
      ProviderScope(
        overrides: [agentRepositoryProvider.overrideWithValue(repo)],
        child: const AegisApp(),
      ),
    );
    // Pasos de 100 ms: más finos que los 320 ms por línea, así que ninguna línea
    // aparece y desaparece entre dos pumps sin que nadie la vea.
    for (var i = 0; i < 60; i++) {
      await tester.pump(const Duration(milliseconds: 100));
      for (final w in tester.widgetList<Text>(find.byType(Text))) {
        vistos.add(w.data ?? '');
      }
    }
    return vistos;
  }

  testWidgets('con puente: dice lo que sabe y nada más', (tester) async {
    final vistos = await arrancar(tester, FakeAgentRepository());
    final todo = vistos.join(' | ');

    expect(todo, contains('Desperté. Estoy listo.'), reason: todo);
    expect(todo, contains('puente: contesta'), reason: todo);
    expect(todo, contains('hermes: arrancado'), reason: todo);
    expect(todo, contains('ollama: arrancado'), reason: todo);

    // Lo que el arranque viejo prometía sin comprobar. Ninguno puede aparecer.
    expect(todo, isNot(contains('handshake')));
    expect(todo, isNot(contains('auth')));
    expect(todo, isNot(contains('entrada: concedida')));

    // Y termina dejando ver la app.
    expect(find.text('AEGIS'), findsOneWidget);
    expect(find.text('Ahora'), findsWidgets);

    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('sin puente: lo dice, y no dice que está listo', (tester) async {
    final vistos = await arrancar(tester, FakeAgentRepository(fallaHealth: true));
    final todo = vistos.join(' | ');

    expect(todo, contains('no llego al portátil'), reason: todo);
    expect(todo, isNot(contains('Desperté. Estoy listo.')));
    // Y el shell se convierte en el que explica por qué.
    expect(find.text('No llego al puente'), findsWidgets);

    await tester.pumpWidget(const SizedBox());
  });
}
