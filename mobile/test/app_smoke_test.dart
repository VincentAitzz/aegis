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
import 'package:aegis_console/presentation/pages/primera_vez.dart';
import 'package:aegis_console/presentation/providers/agent_providers.dart';
import 'fake_repository.dart';
import 'preguntados_de_fabrica.dart';

void main() {
  /// [primera] simula una instalación limpia: sin el set, que es lo que recibe
  /// la app la primera vez.
  Future<void> montar(WidgetTester tester,
      {FakeAgentRepository? repo, bool primera = false}) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          agentRepositoryProvider.overrideWithValue(repo ?? FakeAgentRepository()),
        ],
        child: AegisApp(
            yaPreguntados: primera ? const {} : yaPreguntados()),
      ),
    );
    for (var i = 0; i < 12; i++) {
      await tester.pump(const Duration(milliseconds: 320));
    }
    await tester.pump(const Duration(milliseconds: 600));
  }

  testWidgets('instalación limpia: primero explica los permisos', (tester) async {
    // Este test es la razón de que `yaPreguntados` sea un `Set` y no un
    // provider. Con un provider a medio cargar, la rama de carga entraba igual
    // que el éxito y el pase **no aparecía**: se montaba la app entera, el
    // estado se quedaba en `AsyncLoading`, y no había ningún fallo visible
    // porque «no sé todavía» se escribía igual que «no toca». Montado con el set
    // vacío, el pase se ve.
    await montar(tester, primera: true);

    expect(find.byType(PrimeraVezPage), findsOneWidget);
    // Y no solo está: dice por qué, que es lo que evita que se denague a ciegas.
    expect(find.text('Un par de cosas\nantes de empezar.'), findsOneWidget);

    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('contestar saca del pase: la app entra de verdad', (tester) async {
    // El fallo que este test cubre: el set venía como campo del constructor y
    // no cambiaba, así que al marcar «preguntado» la app se quedaba en el
    // pase **con el permiso ya concedido**. Se vio en el emulador
    // (`granted=true` y el formulario delante), y ningún test lo cazaba porque
    // los de la página usan un `salir` de mentira y nunca tocan el cableado.
    //
    // Aquí se monta la app entera, y se deja constancia de que la pantalla
    // se va sola: si el árbol se repinta con el mismo set, el formulario
    // sigue ahí y el test falla.
    await montar(tester, primera: true);
    expect(find.byType(PrimeraVezPage), findsOneWidget);

    await tester.tap(find.text('Empezar'));
    // Dos pasos: el `await` del diálogo del sistema y el repintado.
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 200));
    }

    expect(find.byType(PrimeraVezPage), findsNothing,
        reason: 'la app se quedó en el pase después de contestar');
    expect(find.text('Ahora'), findsWidgets);

    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('segunda vez: ni rastro del pase', (tester) async {
    await montar(tester);
    expect(find.byType(PrimeraVezPage), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

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
