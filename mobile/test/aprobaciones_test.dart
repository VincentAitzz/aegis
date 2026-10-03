// Aprobar tiene que poder cerrarse desde el propio cliente.
//
// ## El fallo que esto cubre
// La cola emitía un token de un solo uso, `/aprobaciones` lo devolvía, y
// `resolverAprobacion` estaba declarado `Future<void>`: el token se quedaba en
// la respuesta sin que nadie lo leyera. La pantalla de Ahora enseñaba "Sí,
// adelante", lo apagaba, y el run se quedaba muerto pidiendo un permiso que ya
// se había concedido.
//
// ## Qué se afirma aquí
// Que aprobar deja la petición en la lista **con su token**, que el botón de
// relanzar existe y que al pulsarlo el token viaja una vez. No se afirma nada
// del modelo ni de la red: el repo está falseado.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aegis_console/data/models/asistente_models.dart';
import 'package:aegis_console/presentation/pages/ahora_page.dart';
import 'package:aegis_console/presentation/providers/agent_providers.dart';

import 'fake_repository.dart';

void main() {
  /// Monta solo la pantalla de Ahora, que es donde vive la bandeja.
  Future<FakeAgentRepository> montar(WidgetTester tester, FakeAgentRepository repo) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [agentRepositoryProvider.overrideWithValue(repo)],
        child: const MaterialApp(home: Scaffold(body: AhoraPage())),
      ),
    );
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 320));
    }
    // Autopilot es el único motor que ejecuta tools: es el que devuelve el run
    // al que hay que relanzarle un permiso.
    await tester.tap(find.text('AUTOPILOT'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 320));
    return repo;
  }

  FakeAgentRepository repoConPeticion() => FakeAgentRepository()
    ..aprobacionesFake = const [
        Aprobacion(
          id: 'ok-1',
          tool: 'project_create',
          motivo: 'Voy a **dar de alta** el proyecto acme.',
          paso: 1,
          runId: 'autopilot-1',
          proyecto: 'acme',
        ),
      ];

  testWidgets('una petición sin token ofrece sí y no', (tester) async {
    final repo = await montar(tester, repoConPeticion());
    expect(find.text('ME HE PARADO'), findsOneWidget);
    expect(find.text('Sí, adelante'), findsOneWidget);
    expect(find.text('Relanzar'), findsNothing);
    expect(repo.tokensGastados, isEmpty);
  });

  testWidgets('aprobar deja el permiso relanzable, con su token', (tester) async {
    final repo = await montar(tester, repoConPeticion());

    await tester.tap(find.text('Sí, adelante'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    // La tarjeta cambia de estado: ya no está preguntando, está esperando que
    // alguien relancee.
    expect(find.text('TE DIJE QUE SÍ'), findsOneWidget);
    expect(find.text('Relanzar'), findsOneWidget);
    expect(find.text('Sí, adelante'), findsNothing);
    expect(repo.aprobacionesFake.single.token, isNotEmpty);
    // Aprobar NO ejecuta nada por su cuenta: el permiso es una promesa, no un
    // hecho. Esto es lo que impide que "aprobar" se lea como "hecho".
    expect(repo.tokensGastados, isEmpty);
  });

  testWidgets('rechazar con motivo guarda el motivo', (tester) async {
    final repo = await montar(tester, repoConPeticion());
    await tester.tap(find.text('No'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    // Hay dos TextField en pantalla (el del encargo y el del diálogo), y en
    // este test el que importa es el del diálogo.
    await tester.enterText(find.byType(TextField).last, 'ahora no');
    await tester.tap(find.text('Decir que no'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(repo.denegacionesFake, contains('ahora no'));
    expect(repo.aprobacionesFake, isEmpty);
  });

  testWidgets('sin encargo escrito, relanzar lo dice en vez de fallar', (tester) async {
    final repo = await montar(tester, repoConPeticion());
    await tester.tap(find.text('Sí, adelante'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    await tester.tap(find.text('Relanzar'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    // El motivo sale en el cuerpo de la pantalla, debajo de la tarjeta: hay que
    // bajarla para que exista siquiera, porque la `ListView` construye lo que
    // se ve. Un error que solo se lee si haces scroll, en un móvil, es un error
    // que no se lee.
    await tester.drag(find.byType(ListView), const Offset(0, -260));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.textContaining('Para relanzar hace falta el encargo'), findsOneWidget);
    expect(repo.tokensGastados, isEmpty,
        reason: 'sin prompt no hay run que relanzar, y el token no se gasta');
  });

  testWidgets('reenviar el encargo gasta el token, y solo una vez', (tester) async {
    final repo = await montar(tester, repoConPeticion());
    await tester.tap(find.text('Sí, adelante'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    // El selector de fases es lo que hace esto cómodo: el relanzado tiene que
    // salir de la misma pantalla donde se escribió el encargo.
    expect(find.text('IDEA'), findsOneWidget);
    expect(find.text('ARQUITECTURA'), findsOneWidget);

    await tester.enterText(find.byType(TextField).first, 'da de alta el proyecto acme');
    await tester.pump();
    await tester.tap(find.text('Relanzar'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));

    expect(repo.tokensGastados, hasLength(1));
    expect(repo.promptsLanzados, hasLength(1));
    expect(repo.promptsLanzados.single, 'da de alta el proyecto acme');
  });


  testWidgets('ejecutar lo aprobado no relanza nada', (tester) async {
    final repo = await montar(tester, repoConPeticion());
    await tester.tap(find.text('Sí, adelante'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    await tester.tap(find.text('Ejecutar'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    // Esto es lo que lo distingue de Relanzar: no hay run nuevo, no hay token y
    // no hay modelo. Se ejecutó la llamada que estaba aprobada.
    expect(repo.ejecutadasFake, ['ok-1']);
    expect(repo.tokensGastados, isEmpty);
    expect(repo.promptsLanzados, isEmpty);
    // Y el resultado se ve, en vez de un "hecho" sin texto que lo confirme.
    expect(find.textContaining('Alta de prueba'), findsOneWidget);
  });

  testWidgets('lo aprobado explica cuál de los dos botones es cuál', (tester) async {
    await montar(tester, repoConPeticion());
    await tester.tap(find.text('Sí, adelante'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.textContaining('Ejecutar hace justo lo que aprobaste'), findsOneWidget);
  });

  testWidgets('la fase elegida viaja con el encargo', (tester) async {
    final repo = await montar(tester, FakeAgentRepository());
    await tester.enterText(find.byType(TextField).first, 'aterriza la idea');
    await tester.pump();
    await tester.tap(find.text('ARQUITECTURA'));
    await tester.pump();
    // Al elegirla se explica para qué sirve: una fase cambia lo que Aegis se
    // permite hacer, y eso no se elige sin leer.
    expect(find.textContaining('coste de cambio'), findsOneWidget);
    await tester.tap(find.text('Encargar'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(repo.fasesLanzadas, contains('arquitectura'));
    // `pump` y no `pumpAndSettle`: la pantalla sigue preguntando el estado del
    // run cada 3 s, así que nunca se calma y `pumpAndSettle` se pasa el tiempo.
    await tester.pump(const Duration(milliseconds: 400));
  });
}