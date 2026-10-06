// El alta de un proyecto desde el móvil.
//
// ## Qué se prueba
// Tres cosas, y una de ellas es la que más cuesta ver en el código:
//
// - **el alias se valida antes de gastar un viaje**. El bridge valida lo mismo,
//   pero si la app no valida, escribir «Mal Alias» cuesta un 400 y se ve como un
//   fallo del puente cuando el problema es el teclado;
// - **un 409 del verificador se dice con su motivo**, no como una excepción. Es
//   el caso donde el interruptor de escritura parece roto;
// - **el resumen enseña qué falta por escribir**, que es lo único accionable
//   después de crear un proyecto.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aegis_console/presentation/pages/hoja_alta.dart';
import 'package:aegis_console/presentation/providers/agent_providers.dart';

import 'fake_repository.dart';

void main() {
  Future<void> montar(WidgetTester tester, FakeAgentRepository repo) async {
    tester.view.physicalSize = const Size(1080, 3200);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [agentRepositoryProvider.overrideWithValue(repo)],
        child: const MaterialApp(home: Scaffold(body: HojaAlta())),
      ),
    );
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 320));
    }
  }

  group('el alias', () {
    testWidgets('con mayúsculas no deja enviar', (tester) async {
      final repo = FakeAgentRepository();
      await montar(tester, repo);

      await tester.enterText(find.byType(TextField).first, 'Mal Alias');
      await tester.pump();

      // El motivo exacto, no «algo que diga minúsculas»: la ayuda del campo
      // contiene la palabra y el test pasaría sin comprobar nada.
      expect(find.textContaining('empezando por letra o dígito'), findsOneWidget,
          reason: 'el motivo del rechazo tiene que estar escrito antes de gastar '
              'un viaje: el bridge valida lo mismo, pero aquí es un teclado');
      expect(repo.altasFake, isEmpty);
    });

    testWidgets('un alias válido pasa y se envía', (tester) async {
      final repo = FakeAgentRepository();
      await montar(tester, repo);

      await tester.enterText(find.byType(TextField).first, 'encargo-nuevo');
      await tester.pump();
      await tester.tap(find.text('Crear el proyecto'));
      for (var i = 0; i < 10; i++) {
        await tester.pump(const Duration(milliseconds: 320));
      }

      expect(repo.altasFake, hasLength(1));
      expect(repo.altasFake.first['alias'], 'encargo-nuevo');
    });

    testWidgets('vacío no se puede enviar', (tester) async {
      final repo = FakeAgentRepository();
      await montar(tester, repo);
      final boton = tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Crear el proyecto'));
      expect(boton.onPressed, isNull,
          reason: 'sin alias no hay nada que crear, y el bridge lo rechazaría');
    });
  });

  group('el resumen', () {
    testWidgets('enseña qué secciones faltan', (tester) async {
      final repo = FakeAgentRepository();
      await montar(tester, repo);
      await tester.enterText(find.byType(TextField).first, 'encargo-nuevo');
      await tester.pump();
      await tester.tap(find.text('Crear el proyecto'));
      for (var i = 0; i < 10; i++) {
        await tester.pump(const Duration(milliseconds: 320));
      }

      expect(find.text('PROYECTO CREADO'), findsOneWidget);
      expect(find.textContaining('Falta escribir en la ficha'), findsOneWidget);
      // Y los nombres exactos, que es lo que permite saber qué hacer después.
      expect(find.textContaining('Qué problema resuelve'), findsWidgets);
    });
  });

  group('un rechazo del bridge', () {
    testWidgets('el 409 del verificador sale con su motivo', (tester) async {
      final repo = FakeAgentRepository();
      repo.errorAlta = StateError(
        "'x' no tiene verificador declarado en app/projects.py, así que no hay "
        'contra qué comprobar que el trabajo quedó bien.',
      );
      await montar(tester, repo);

      await tester.enterText(find.byType(TextField).first, 'encargo-nuevo');
      await tester.pump();
      await tester.tap(find.text('Crear el proyecto'));
      for (var i = 0; i < 10; i++) {
        await tester.pump(const Duration(milliseconds: 320));
      }

      expect(find.textContaining('verificador declarado'), findsOneWidget,
          reason: 'el motivo que escribió el bridge es lo accionable; sin esto '
              'se vería «Bad state: …»');
    });

    testWidgets('tras un rechazo no dice que se creó nada', (tester) async {
      final repo = FakeAgentRepository();
      repo.errorAlta = StateError('alias ya registrado');
      await montar(tester, repo);
      await tester.enterText(find.byType(TextField).first, 'aegis');
      await tester.pump();
      await tester.tap(find.text('Crear el proyecto'));
      for (var i = 0; i < 10; i++) {
        await tester.pump(const Duration(milliseconds: 320));
      }

      expect(find.text('PROYECTO CREADO'), findsNothing,
          reason: 'enseñar «creado» tras un fallo es la forma más directa de '
              'perder la confianza en la pantalla');
    });
  });

  group('lo que se pide', () {
    testWidgets('el verificador se envía tal cual', (tester) async {
      final repo = FakeAgentRepository();
      await montar(tester, repo);
      await tester.enterText(find.byType(TextField).first, 'encargo-nuevo');
      await tester.pump();
      // El campo del verificador es el quinto: alias, nombre, alcance,
      // verificador, y la base solo aparece si se marca.
      final campos = find.byType(TextField);
      await tester.enterText(campos.at(3), 'flutter test');
      await tester.tap(find.text('Crear el proyecto'));
      for (var i = 0; i < 10; i++) {
        await tester.pump(const Duration(milliseconds: 320));
      }
      expect(repo.altasFake.first['verificar'], 'flutter test',
          reason: 'sin verificador el proyecto recién creado no puede marcado '
              'para escritura: el alta puede terminar en algo Aegis no puede tocar');
    });

    testWidgets('la base se pide solo si dices que la tiene', (tester) async {
      final repo = FakeAgentRepository();
      await montar(tester, repo);
      // Sin tocar el interruptor, no hay campo de base.
      expect(find.byType(TextField), findsNWidgets(4));
      expect(find.textContaining('proveedor: neon'), findsNothing);
    });
  });
}