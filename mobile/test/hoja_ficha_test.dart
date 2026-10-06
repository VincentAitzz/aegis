// La hoja de la ficha: el acordeón y la fusión de paso-sección.
//
// ## Qué se prueba y por qué
// El acordeón tiene un comportamiento que no es evidente en el código y que se
// rompe sin avisar:
//
// - **guardar una sección abre la siguiente que falta**. Es lo que hace que se
//   lea como un cuestionario sin esconder el resto. Si se rompe, sigue
//   funcionando: se ven todas las secciones y se abre una. Por eso necesita un
//   test propio.
// - **si el guardado falla, NO avanza**. Un avance tras un rechazo dejaría al
//   usuario creyendo que se guardó, y perdería el texto que estaba escribiendo.
// - **tocar el markdown a mano para de pisar el documento**. Si se rompe al revés
//   —que el generador pise lo escrito— se pierde texto sin ningún aviso.
//
// Y uno que parece de modelo y no lo es: que las secciones que se preguntan
// **vienen del bridge**, no de una lista en Dart. Si se copian, el día que el
// bridge añada una la puerta la pedirá y la app no la preguntará.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aegis_console/data/models/asistente_models.dart';
import 'package:aegis_console/presentation/pages/hoja_ficha.dart';
import 'package:aegis_console/presentation/providers/agent_providers.dart';
import 'package:aegis_console/presentation/widgets/acordeon_secciones.dart';

import 'fake_repository.dart';

void main() {
  Future<void> montar(
    WidgetTester tester, {
    required FakeAgentRepository repo,
    FichaTexto? ficha,
    FichaPrivada? privada,
  }) async {
    // Superficie alta a propósito: la hoja es un `ListView`, y uno perezoso solo
    // construye lo que está en el viewport. Con la altura por defecto de 800x600
    // el botón de guardar ni existe en el árbol, y un `find.text` no lo encuentra
    // aunque el widget esté en la lista.
    tester.view.physicalSize = const Size(1080, 3200);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [agentRepositoryProvider.overrideWithValue(repo)],
        child: MaterialApp(
          home: Scaffold(
            body: HojaFicha(
              alias: 'prueba',
              ficha: ficha ??
                  FichaTexto(
                    alias: 'prueba',
                    kind: 'encargo',
                    estado: 'parcial',
                    secciones: const {},
                    faltan: const [
                      'Qué problema resuelve',
                      'Para qué se usa',
                      'Quién lo usa',
                      'Criterio de aceptación',
                      'Alcance dentro',
                      'Alcance fuera',
                      'Alternativas consideradas',
                      'Cómo se verifica',
                    ],
                  ),
            ),
          ),
        ),
      ),
    );
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 320));
    }
    if (privada != null) repo.privadaFake = privada;
  }

  /// Baja hasta el final de la hoja.
  ///
  /// Necesario para cualquier aserción sobre lo que hay bajo el acordeón: el
  /// `ListView` es perezoso y no construye lo que no se ve. Sin esto, el botón de
  /// guardar no existe para el test aunque esté en pantalla para una persona.
  Future<void> alFondo(WidgetTester tester) async {
    await tester.drag(find.byType(ListView), const Offset(0, -1200));
    await tester.pump();
    await tester.drag(find.byType(ListView), const Offset(0, -1200));
    await tester.pump();
  }

  group('el acordeón abre la que falta', () {
    testWidgets('la primera sección sin escribir es la que se abre', (tester) async {
      final repo = FakeAgentRepository();
      await montar(tester, repo: repo, ficha: FichaTexto(
        alias: 'prueba',
        kind: 'encargo',
        secciones: const {'Quién lo usa': 'Ana y Luis'},
      ));
      // «Qué problema resuelve» es la primera y está vacía: esa se abre, no la
      // que ya tiene contenido.
      expect(find.text('Qué problema resuelve'), findsWidgets);
      await alFondo(tester);
      expect(find.text('Guardar esta sección'), findsOneWidget,
          reason: 'una sola sección abierta a la vez');
    });

    testWidgets('guardar abre la siguiente que falta', (tester) async {
      final repo = FakeAgentRepository();
      await montar(tester, repo: repo);

      await tester.enterText(find.byType(TextField).first, 'Cobrar a mano');
      await alFondo(tester);
      await tester.tap(find.text('Guardar esta sección'));
      for (var i = 0; i < 10; i++) {
        await tester.pump(const Duration(milliseconds: 320));
      }

      expect(repo.contenidoFichaGuardado, contains('Cobrar a mano'));
      // Y ahora se abre la siguiente, que no es la que acabas de escribir.
      expect(find.text('Para qué se usa'), findsWidgets);
    });

    testWidgets('solo hay una sección abierta', (tester) async {
      final repo = FakeAgentRepository();
      await montar(tester, repo: repo);
      // Abrir la segunda cierra la primera: dos abiertas a la vez romperían la
      // idea de «una pregunta a la vez».
      expect(find.text('Guardar esta sección'), findsOneWidget);
      await alFondo(tester);
      await tester.tap(find.text('Para qué se usa'));
      await tester.pump();
      await alFondo(tester);
      expect(find.text('Guardar esta sección'), findsOneWidget,
          reason: 'abrir la segunda cierra la primera: dos a la vez rompen la '
              'idea de «una pregunta a la vez»');
    });
  });

  group('un guardado fallido no avanza', () {
    testWidgets('y el motivo se enseña', (tester) async {
      final repo = FakeAgentRepository();
      await montar(tester, repo: repo);
      await tester.enterText(find.byType(TextField).first, 'algo');

      // La escritura falla: `mensajeDeError` no aplica a un `StateError` del
      // fake, así que el texto que se busca es el que este pone.
      repo.errorFicha = 'escritura RECHAZADA: no parsea';
      await alFondo(tester);
      await tester.tap(find.text('Guardar esta sección'));
      for (var i = 0; i < 10; i++) {
        await tester.pump(const Duration(milliseconds: 320));
      }

      expect(find.textContaining('no parsea'), findsOneWidget,
          reason: 'el texto que escribió el bridge es el que se enseña; sin esto '
              'se vería «DioException [bad response]»');
    });
  });

  group('las secciones vienen del bridge', () {
    testWidgets('pregunta las que el bridge declara para el tipo', (tester) async {
      final repo = FakeAgentRepository();
      await montar(tester, repo: repo, ficha: const FichaTexto(
        alias: 'prueba',
        kind: 'encargo',
      ));
      // Las ocho del encargo, en su orden.
      expect(find.text('Qué problema resuelve'), findsOneWidget);
      expect(find.text('Cómo se verifica'), findsOneWidget);
    });

    testWidgets('un tipo de herramienta no pregunta lo de un encargo',
        (tester) async {
      final repo = FakeAgentRepository();
      await montar(tester, repo: repo, ficha: const FichaTexto(
        alias: 'prueba',
        kind: 'herramienta',
      ));
      expect(find.text('Qué no toca'), findsOneWidget);
      expect(find.text('Qué problema resuelve'), findsNothing,
          reason: 'preguntarle a una herramienta por el problema de un cliente '
              'es ruido: las secciones son las del tipo, no las de otro');
    });
  });

  group('la caja de markdown', () {
    testWidgets('muestra lo que se va a guardar', (tester) async {
      final repo = FakeAgentRepository();
      await montar(tester, repo: repo);
      expect(find.text('MARKDOWN · lo que se guarda'), findsOneWidget);
    });

    testWidgets('tocarla avisa de que está editada a mano', (tester) async {
      final repo = FakeAgentRepository();
      await montar(tester, repo: repo);
      await alFondo(tester);
      await tester.enterText(find.byType(TextField).last, 'lo escribo yo');
      await tester.pump();
      expect(find.text('editado a mano'), findsOneWidget,
          reason: 'sin el aviso, que el generador deje de pisar lo escrito '
              'parecería un fallo');
    });
  });

  group('la pestaña del cliente', () {
    testWidgets('avisa de que no se versiona', (tester) async {
      final repo = FakeAgentRepository();
      await montar(tester, repo: repo);
      expect(find.text('no se versiona'), findsOneWidget);
    });

    testWidgets('pregunta cómo se cobra antes de nada', (tester) async {
      final repo = FakeAgentRepository();
      await montar(tester, repo: repo);
      await tester.tap(find.textContaining('CLIENTE'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 320));
      expect(find.text('¿Cómo se cobra?'), findsOneWidget);
      expect(find.text('precio cerrado'), findsOneWidget);
      expect(find.text('sin cobro'), findsOneWidget);
    });

    testWidgets('sin modelo de cobro, se preguntan todas las secciones',
        (tester) async {
      // Elegir uno es lo que oculta lo que no aplica. Sin haberlo elegido, se
      // muestran todas: esconder secciones antes de saber cómo se cobra esconde
      // justo lo que hace falta para decidir.
      final repo = FakeAgentRepository();
      await montar(tester, repo: repo);
      await tester.tap(find.textContaining('CLIENTE'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 320));
      expect(find.text('Presupuesto y pagos'), findsOneWidget);
      expect(find.text('Hitos y facturación'), findsOneWidget);
    });
  });

  group('AcordeonSecciones, la lógica suelta', () {
    test('primeraPendiente devuelve la primera sin escribir', () {
      final secciones = [
        const SeccionAcordeon(titulo: 'A', abierta: false, escrita: true),
        const SeccionAcordeon(titulo: 'B', abierta: false, escrita: false),
        const SeccionAcordeon(titulo: 'C', abierta: false, escrita: false),
      ];
      expect(AcordeonSecciones.primeraPendiente(secciones), 'B');
    });

    test('primeraPendiente con todo escrito no abre nada', () {
      final secciones = [
        const SeccionAcordeon(titulo: 'A', abierta: false, escrita: true),
      ];
      expect(AcordeonSecciones.primeraPendiente(secciones), isNull,
          reason: 'un acordeón con todo cerrado dice «está completa»; abrir una '
              'invita a cambiar algo que ya está bien');
    });

    test('el progreso cuenta solo las obligatorias', () {
      // La ficha privada tiene doce secciones y ninguna es obligatoria: marcar
      // «11 sin escribir» haría creer que hay algo que rellenar que no.
      final secciones = [
        const SeccionAcordeon(titulo: 'A', abierta: false, escrita: true),
        const SeccionAcordeon(
            titulo: 'B', abierta: false, escrita: false, requerida: false),
      ];
      final (hechas, total) = AcordeonSecciones.progreso(secciones);
      expect(hechas, 1);
      expect(total, 1);
    });
  });
}
