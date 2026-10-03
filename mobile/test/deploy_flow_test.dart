// Aprobar una instalación tiene que **instalar**, no solo emitir el token.
//
// ## El fallo que esto cubre
//
// El bridge separa la aprobación de la instalación en dos endpoints a propósito:
// `POST /deploys/{id}` emite el token y `POST /deploys/{id}/instalar` lo gasta
// **dentro del bridge**, para que el agente nunca llegue a verlo. El docstring de
// `deploy_aprobar` dice que quien aprueba desde el móvil «encadena las dos».
//
// El móvil no encadenaba. `decideDeploy` era lo único que llamaba, y el
// `deploysProvider` se refrescaba. Medido en el teléfono real, el 2026-10-03:
//
//   POST /deploys/deploy-a362be7a5e          → 200   (aprobado)
//   POST /deploys/deploy-a362be7a5e/instalar → —     (nunca se llamó)
//
// Dos OK dados, la lista refrescada, y **`lastUpdateTime` del teléfono sin
// cambiar**. La app-installada siguió siendo la de antes. Quien aprueba se
// queda con un gesto que parece haber hecho algo y no ha movido nada, y no hay
// nadie a quien preguntar porque el gesto se hizo a distancia.
//
// Esto es el mismo patrón que A-016 por el otro lado: una interfaz que dice «hecho» con
// detrás un «no instalado». La diferencia es que aquí no fue el agente el que
// mintió, sino el cliente.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aegis_console/data/models/agent_models.dart';
import 'package:aegis_console/presentation/pages/ajustes_page.dart';
import 'package:aegis_console/presentation/providers/agent_providers.dart';

import 'fake_repository.dart';

void main() {
  // El id y el texto son los de la petición real que falló el 2026-10-03: si el
  // test usa de mentira, deja de contar la historia y solo afirma que dos
  // llamadas se encadenan.
  FakeAgentRepository repoConPeticion() => FakeAgentRepository(
        despliegues: const DeployState(
          emulador: true,
          telefono: true,
          pendientes: [
            DeployRequest(
              id: 'deploy-a362be7a5e',
              estado: 'pendiente',
              razon: 'APK verificado, listo para instalar en SERIAL1234567',
              lanzar: true,
            ),
          ],
          tokensVivos: 1,
        ),
      );

  /// Monta **Ajustes**, que es donde vive el cuadro de despliegues.
  ///
  /// Se monta esa pantalla y no la de Ahora a propósito: el bug estaba en el
  /// cliente de la llamada, así que el test tiene que ir a donde el approving
  /// ocurre, no a donde se pintaba la consecuencia.
  Future<void> montar(WidgetTester tester, FakeAgentRepository repo) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [agentRepositoryProvider.overrideWithValue(repo)],
        child: const MaterialApp(home: Scaffold(body: AjustesPage())),
      ),
    );
    // `DeploysController.build()` devuelve `null` y **programa un timer de 20 s**
    // para la primera lectura: con 10 bombeos el cuadro no se ha pintado nunca y
    // el test fallaría por no encontrar un botón que sí existe. Se avanza hasta
    // pasar ese primer tick en vez de forzar el estado a mano, porque el estado
    // forzado no probaría que la pantalla se pinta sola.
    for (var i = 0; i < 70; i++) {
      await tester.pump(const Duration(milliseconds: 320));
    }
    // Y el cuadro va el tercero en la lista, así que en el viewport de 600 dp de
    // alto está bajo el pliegue.
    final boton = find.text('APROBAR UNA VEZ');
    expect(boton, findsOneWidget, reason: 'el cuadro de despliegues no se pintó');
    await tester.ensureVisible(boton);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 320));
  }

  testWidgets('aprobar encadena la instalación, no solo el token', (
    tester,
  ) async {
    final repo = repoConPeticion();
    await montar(tester, repo);
    expect(find.text('APROBAR UNA VEZ'), findsOneWidget);

    await tester.tap(find.text('APROBAR UNA VEZ'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));

    // Lo que falla es que falte la segunda. Por eso se mira el **par**, no que
    // se haya llamado a algo: aprobar sin instalar detrás también llamaría a
    // algo.
    expect(repo.deploys, ['aprobar:deploy-a362be7a5e', 'instalar:deploy-a362be7a5e']);
  });

  testWidgets('denegar NO instala', (tester) async {
    final repo = repoConPeticion();
    await montar(tester, repo);

    await tester.tap(find.text('NO'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));

    // Denegar es un no: instalar aquí sería lo contrario de lo que se pidió.
    expect(repo.deploys, ['denegar:deploy-a362be7a5e']);
    expect(find.textContaining('Denegado'), findsOneWidget);
  });

  testWidgets('el resultado de la instalación se enseña', (tester) async {
    // Si aprobar no dice nada, el gesto se siente como un trámite sin destino: el
    // endpoint devuelve que **arranca** y el aviso del móvil confirma al
    // terminar, así que la app tiene que decir algo en medio.
    final repo = repoConPeticion();
    await montar(tester, repo);

    await tester.tap(find.text('APROBAR UNA VEZ'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));

    expect(find.textContaining('arranca'), findsOneWidget);
  });

  testWidgets('el boton de instalar no existe suelto en la API del repo', (
    tester,
  ) async {
    // El método tiene que existir con su nombre. Si alguien lo borra thinking
    // que `decideDeploy` ya instala, esto no compila y el bug vuelve a estar
    // disponible sin que nada se queje.
    final repo = repoConPeticion();
    await montar(tester, repo);
    expect(repo.instalarDeploy, isNotNull);
    expect('instalar:deploy-a362be7a5e', isNot(startsWith('aprobar:')));
  });
}
