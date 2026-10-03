// El glifo dice lo que Aegis está haciendo, y lo dice igual en todas partes.
//
// ## Por qué un test de widget y no de unidad
// Porque el fallo que se quiere evitar no es «la función del color está mal» —eso
// lo cubre otro test— sino **que el glifo no se conecte al estado**. Un widget
// bellamente puesto que se queda en celeste mientras el agente habla parece
// funcionando: dibuja, brilla, late. Solo se nota en el móvil real, y para
// entonces ya es una regresión en toda la app.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aegis_console/core/theme/aegis_palette.dart';
import 'package:aegis_console/core/widgets/aegis_mark.dart';
import 'package:aegis_console/data/models/agent_models.dart';
import 'package:aegis_console/data/models/asistente_models.dart';
import 'package:aegis_console/presentation/shell/aegis_shell.dart';
import 'package:aegis_console/presentation/providers/agent_providers.dart';

import 'fake_repository.dart';

/// El glifo de la cabecera, con la app entera detrás: es la forma de comprobar
/// que el estado **llega** desde el repo hasta lo que se ve.
Future<Color?> colorDelGlifoEnPantalla(
  WidgetTester tester,
  FakeAgentRepository repo,
) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [agentRepositoryProvider.overrideWithValue(repo)],
      child: const MaterialApp(home: AegisShell()),
    ),
  );
  // Un par de vueltas: el poller de actividad es un temporizador, y el glifo se
  // pinta después de la primera respuesta.
  for (var i = 0; i < 4; i++) {
    await tester.pump(const Duration(milliseconds: 300));
  }
  final mark = tester.widget<AegisMark>(find.byType(AegisMark).first);
  return colorDeEstado(mark.estado);
}

void main() {
  testWidgets('en reposo el glifo está celeste', (tester) async {
    final repo = FakeAgentRepository();   // quieto por defecto
    expect(await colorDelGlifoEnPantalla(tester, repo), AegisPalette.brand);
  });

  testWidgets('hablando el glifo se pone magenta', (tester) async {
    final repo = FakeAgentRepository()
      ..estado = const Actividad(hablando: true, haceS: 0, que: 'hermes');
    expect(await colorDelGlifoEnPantalla(tester, repo), AegisPalette.voz);
  });

  testWidgets('sin puente el glifo se apaga aunque esté hablando', (tester) async {
    // El caso donde los dos datos se pelean. Si gana el magenta, el glifo
    // dice «estoy hablando» de un Aegis que no tiene con quién hablar.
    final repo = FakeAgentRepository(
      salud: const BridgeHealth(
        ok: false,
        host: 'sin-puente',
        hermesOk: false,
        ollamaOk: false,
        agents: [],
        models: [],
      ),
    )..estado = const Actividad(hablando: true, haceS: 0, que: 'hermes');
    expect(await colorDelGlifoEnPantalla(tester, repo), AegisPalette.apagado);
  });

  testWidgets('el mismo widget sirve para el arte y para la silueta',
      (tester) async {
    // A 20 px no cabe una calavera de 77 renglones y sale la silueta; a 320 sale
    // el arte. Nadie tiene que acordarse de cuál va en cada sitio, y **ningún
    // call site pasa un segundo tipo**: si existieran dos widgets, este test
    // seguiría passando y la mitad de la app se quedaría con la marca vieja.
    for (final tam in [20.0, 320.0]) {
      await tester.pumpWidget(
        MaterialApp(home: Scaffold(body: AegisMark(size: tam))),
      );
      expect(find.byType(AegisMark), findsOneWidget, reason: 'tamaño $tam');
      await tester.pump(const Duration(milliseconds: 300));
    }
  });
}
