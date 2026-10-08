// Qué ofrece el diálogo de actualización y qué hace con lo que le dicen.
//
// ## Qué se prueba aquí
// La conducta: qué botón aparece, si se puede instalar sin permiso, y qué se
// dice cuando algo falla. No se prueba el `MethodChannel` —eso necesita un
// emulador— sino las **decisiones**, que es donde se puede equivocar uno.
//
// Cada caso va contra un [InstaladorFalso] distinto en vez de mutar uno común:
// un doble compartido entre tests se desincroniza, y el que falla acaba siendo
// el que no toca este diálogo.
import 'package:aegis_console/core/network/instalador_nativo.dart';
import 'package:aegis_console/data/models/version_apk.dart';
import 'package:aegis_console/presentation/widgets/dialogo_actualizar.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fake_repository.dart';

void main() {
  /// Monta el diálogo con un repo y un nativo, y devuelve los dos.
  (FakeAgentRepository, InstaladorFalso) montar({
    int versionCode = 3,
    bool hayPermiso = true,
    bool fallaDescarga = false,
    bool fallaInstalar = false,
  }) {
    final repo = FakeAgentRepository()
      ..versionApkDelBridge = VersionApk(versionCode: versionCode, versionName: '1.0.$versionCode')
      ..fallaDescarga = fallaDescarga
      // Por defecto la descarga da pasos, para que la barra se vea de verdad en
      // el test que la mira. Los que no la miran no se.ietf.
      ..pasosDeProgreso = 3;
    final nativo = InstaladorFalso(versionCodeValue: 2)
      ..puedeInstalarValue = hayPermiso
      ..fallaInstalar = fallaInstalar;
    return (repo, nativo);
  }

  Future<void> abrir(WidgetTester t, FakeAgentRepository repo, InstaladorFalso nativo) async {
    await t.pumpWidget(MaterialApp(
      home: Scaffold(
        body: Builder(
          builder: (ctx) => TextButton(
            onPressed: () => showDialog<void>(
              context: ctx,
              builder: (_) => DialogoActualizar(
                repo: repo,
                nativo: nativo,
                instalado: 2,
              ),
            ),
            child: const Text('abrir'),
          ),
        ),
      ),
    ));
    await t.tap(find.text('abrir'));
    await t.pump();
    await t.pump(); // el Future del versionCode
  }

  testWidgets('con versión nueva y permiso, ofrece bajarla', (t) async {
    final (repo, nativo) = montar();
    await abrir(t, repo, nativo);
    await t.pumpAndSettle();
    expect(find.text('Bajar la nueva'), findsOneWidget);
    expect(find.text('no se puede instalar en silencio'), findsNothing);
  });

  testWidgets('sin permiso, NO ofrece instalar y sí ofrece ir al permiso', (t) async {
    // Sin el permiso, un botón de instalar lleva a un intent que Android no va a
    // mostrar. El diálogo tiene que decir qué hacer, no dejar un botón muerto.
    final (repo, nativo) = montar(hayPermiso: false);
    await abrir(t, repo, nativo);
    await t.pumpAndSettle();
    expect(find.text('Bajar la nueva'), findsNothing);
    expect(find.text('Ir al permiso en Ajustes'), findsOneWidget);
  });

  testWidgets('al pedir el permiso, se abre Ajustes', (t) async {
    final (repo, nativo) = montar(hayPermiso: false);
    await abrir(t, repo, nativo);
    await t.pumpAndSettle();
    await t.tap(find.text('Ir al permiso en Ajustes'));
    await t.pumpAndSettle();
    expect(nativo.permisoAbierto, isTrue);
    // Y no pide pulsar nada que no exista: al volver se vuelve a preguntar solo.
    expect(find.textContaining('vuelve a pulsar'), findsNothing);
  });

  testWidgets('al volver de Ajustes, pregunta otra vez y ofrece la descarga', (t) async {
    // El permiso se concede fuera de la app, así que el diálogo solo puede
    // enterarse al volver. Antes se quedaba esperando a que pulsaran algo que no
    // había, y había que cerrar y abrir a mano.
    final (repo, nativo) = montar(hayPermiso: false);
    await abrir(t, repo, nativo);
    await t.pumpAndSettle();
    expect(find.text('Ir al permiso en Ajustes'), findsOneWidget);

    nativo.puedeInstalarValue = true; // concedido en Ajustes
    t.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    t.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await t.pumpAndSettle();

    expect(find.text('Bajar la nueva'), findsOneWidget);
  });

  testWidgets('«tienes» es lo instalado, no lo que sirve el bridge', (t) async {
    // Con 2 instalada y 3 en el bridge, decir «tienes versión 3» es mentira.
    final (repo, nativo) = montar();
    await abrir(t, repo, nativo);
    await t.pumpAndSettle();
    expect(find.text('versión 2'), findsOneWidget);
    expect(find.text('3 (1.0.3)'), findsOneWidget);
  });

  testWidgets('si el nativo falla al preguntar, lo dice en vez de quedarse mudo', (t) async {
    // El fallo se vio en el emulador: sin este `catch` el diálogo se quedaba en
    // «preguntando» para siempre, sin error y sin pista de qué pasaba.
    final (repo, _) = montar();
    final nativo = InstaladorFalso(versionCodeValue: 2)..fallaVersionCode = true;
    await t.pumpWidget(MaterialApp(
      home: Scaffold(
        body: Builder(
          builder: (ctx) => TextButton(
            onPressed: () => showDialog<void>(
              context: ctx,
              builder: (_) => DialogoActualizar(repo: repo, nativo: nativo),
            ),
            child: const Text('abrir'),
          ),
        ),
      ),
    ));
    await t.tap(find.text('abrir'));
    await t.pump();
    await t.pumpAndSettle();
    expect(find.textContaining('no se pudo comprobar la actualización'), findsOneWidget);
    expect(find.text('Bajar la nueva'), findsNothing);
  });

  testWidgets('sin versión nueva, no ofrece bajarla', (t) async {
    final (repo, nativo) = montar(versionCode: 2);
    await abrir(t, repo, nativo);
    await t.pumpAndSettle();
    expect(find.text('Bajar la nueva'), findsNothing);
  });

  testWidgets('al bajar, muestra el progreso y luego habilita instalar', (t) async {
    final (repo, nativo) = montar();
    await abrir(t, repo, nativo);
    await t.pumpAndSettle();
    await t.tap(find.text('Bajar la nueva'));
    // Un `pump` y no `pumpAndSettle`: el falso termina en el acto, así que al
    // asentar la descarga ya terminó y la barra de progreso nunca llega a
    // pintarse. Lo que importa aquí es que **hubo** progreso, y para verlo hay
    // que mirarlo mientras dura.
    await t.pump();
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    await t.pumpAndSettle();
    // Y al terminar, la barra desaparece y aparece el botón de instalar: si la
    // barra se quedara, el diálogo parecería bloqueado para siempre.
    expect(find.byType(LinearProgressIndicator), findsNothing);
    expect(find.text('Instalar'), findsOneWidget);
    expect(find.textContaining('descargado'), findsOneWidget);
  });

  testWidgets('si la descarga falla, lo dice y no ofrece instalar', (t) async {
    // Ofrecer instalar sin fichero es un botón que va a fallar con un error del
    // sistema que no explica nada.
    final (repo, nativo) = montar(fallaDescarga: true);
    await abrir(t, repo, nativo);
    await t.pumpAndSettle();
    await t.tap(find.text('Bajar la nueva'));
    await t.pumpAndSettle();
    expect(find.text('Instalar'), findsNothing);
    expect(find.textContaining('no se pudo descargar'), findsOneWidget);
  });

  testWidgets('al instalar, dice que Android lo confirmará, no que ya se instaló', (t) async {
    // La diferencia entre «te toca confirmar» y «instalado» es toda la
    // honestidad de este diálogo: el desenlace lo controla el sistema, y decir
    // «instalado» sobre un diálogo que la persona aún no ha visto es mentir.
    final (repo, nativo) = montar();
    await abrir(t, repo, nativo);
    await t.pumpAndSettle();
    await t.tap(find.text('Bajar la nueva'));
    await t.pumpAndSettle();
    await t.tap(find.text('Instalar'));
    await t.pumpAndSettle();
    expect(nativo.instaladas, ['/data/apk/aegis-2.apk']);
    expect(find.textContaining('te toca confirmar'), findsOneWidget);
    expect(find.textContaining('instalada'), findsNothing);
  });

  testWidgets('si no hay instalador, lo dice como lo que es', (t) async {
    // «No se pudo instalar» y «este móvil no tiene instalador» llevan a
    // diagnosear cosas distintas: uno se arregla permisos, el otro no se arregla
    // desde la app.
    final (repo, nativo) = montar(fallaInstalar: true);
    await abrir(t, repo, nativo);
    await t.pumpAndSettle();
    await t.tap(find.text('Bajar la nueva'));
    await t.pumpAndSettle();
    await t.tap(find.text('Instalar'));
    await t.pumpAndSettle();
    expect(find.textContaining('no tiene un instalador'), findsOneWidget);
  });

  testWidgets('el puente sin APK se ve distinto de «estás al día»', (t) async {
    // Las dos pantallas empiezan igual, pero una se arregla esperando y la otra
    // no tiene nada que arreglar. Si separecieran, no habría forma de saber cuál
    // de las dos es.
    final (repo, nativo) = montar(versionCode: 0);
    await abrir(t, repo, nativo);
    await t.pumpAndSettle();
    expect(find.text('Bajar la nueva'), findsNothing);
    expect(find.textContaining('no tiene un APK'), findsOneWidget);
  });

  testWidgets('el motivo del bridge se enseña tal cual', (t) async {
    final repo = FakeAgentRepository()
      ..versionApkDelBridge = const VersionApk(versionCode: 0);
    await abrir(t, repo, InstaladorFalso(versionCodeValue: 2));
    await t.pumpAndSettle();
    expect(find.textContaining('no tiene un APK'), findsOneWidget);
  });

  testWidgets('si Ajustes no abre, lo dice en vez de tragárselo', (t) async {
    // El caso medido: un dispositivo sin pantalla de Ajustes donde conceder el
    // permiso. El botón «Ir al permiso» no hacía nada, y el motivo se perdía en
    // una excepción sin dueño. Un botón que no hace nada es peor que un botón
    // que dice que no puede.
    final (repo, nativo) = montar(versionCode: 4, hayPermiso: false);
    nativo.motivoPermiso = 'no hay ninguna pantalla de Ajustes';

    await abrir(t, repo, nativo);
    await t.tap(find.text('Ir al permiso en Ajustes'));
    await t.pumpAndSettle();

    expect(nativo.permisoAbierto, isTrue);
    expect(
      find.textContaining('no hay ninguna pantalla de Ajustes'),
      findsOneWidget,
      reason: 'el motivo tiene que verse en el diálogo, no solo existir en el nativo',
    );
  });

  testWidgets('y el motivo sobrevive a la repregunta al volver', (t) async {
    // La nota vive aparte del motivo del bridge a propósito. Ese se borra al
    // volver a preguntar; si el fallo de abrir Ajustes viviera ahí, se iría por
    // la ventana en cuanto la app repreguntara al volver de Ajustes — que es
    // justo lo que pasa.
    final (repo, nativo) = montar(versionCode: 4, hayPermiso: false);
    nativo.motivoPermiso = 'no hay ninguna pantalla de Ajustes';

    await abrir(t, repo, nativo);
    await t.tap(find.text('Ir al permiso en Ajustes'));
    await t.pumpAndSettle();

    // Vuelve la app del fondo: el diálogo repregunta al bridge.
    t.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await t.pumpAndSettle();

    expect(find.textContaining('no hay ninguna pantalla de Ajustes'), findsOneWidget);
  });
}
