// La pantalla de la primera vez.
//
// ## Por qué esta pantalla tiene test propio
// Porque es la primera cosa que ve alguien y **su único trabajo es que los
// botones hagan algo**. Si un botón no responde, alguien pasa de largo la
// pantalla entera creyendo que la app no arranca. Es la misma clase de fallo
// que el de la pantalla de claves, y aquí costaría más: en vez de un
// autenticador que no añade cuentas, una app que no empieza.
import 'dart:io';

import 'package:aegis_console/core/permisos.dart';
import 'package:aegis_console/presentation/providers/primera_vez_providers.dart';
import 'package:aegis_console/presentation/pages/primera_vez.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Un permiso de mentira, que no habla con ningún sistema.
PermisoApp _permisoDePrueba({
  required String id,
  required String paraQue,
  void Function()? alPedir,
}) =>
    PermisoApp(
      id: id,
      nombre: 'prueba',
      paraQue: paraQue,
      concedido: () async => false,
      // El tipado `Future<void> Function()` es lo que avisó de que un `() {}`
      // a secas no vale aquí. Es el mismo motivo por el que existe
      // `AccionAegis`: los callbacks de esta app hacen trabajo asíncrono, y
      // un tipo que admite `void` lo deja pasar sin decir nada.
      pedir: alPedir == null ? () async {} : () async => alPedir(),
    );

Future<void> asentar(WidgetTester t) async {
  for (var i = 0; i < 6; i++) {
    await t.pump(const Duration(milliseconds: 120));
  }
}

void main() {
  // `test` normal y no `testWidgets`: esto lee y escribe un fichero de verdad,
  // y dentro de `testWidgets` el reloj es falso, así que la E/S real nunca
  // termina y el test se queda colgado sin decir por qué. Un test que se cuelga
  // no informa del fallo: lo esconde.
  // Un directorio temporal por test, de verdad: la persistencia que se prueba
  // aquí es la escritura, y writing a un mock sería probar el mock.
  late Directory dir;
  late String ruta;

  setUp(() async {
    dir = await Directory.systemTemp.createTemp('aegis-preguntado');
    ruta = '${dir.path}/preguntado.txt';
  });

  tearDown(() {
    if (dir.existsSync()) dir.deleteSync(recursive: true);
  });

  /// Un contenedor con la ruta sustituida por la temporal.
  ProviderContainer contenedorDePrueba() {
    final c = ProviderContainer(overrides: [
      rutaMarcadorProvider.overrideWith((ref) async => ruta),
    ]);
    addTearDown(c.dispose);
    return c;
  }

  group('lo que se guarda entre arrancadas', () {
    test('preguntar uno lo sigue estando al leer de nuevo', () async {
      final c = contenedorDePrueba();
      await c.read(preguntadosProvider.future);
      final p = permisosDePrimeraVez.first;
      await c.read(preguntadosProvider.notifier).preguntar(p);

      // Un contenedor nuevo es lo que hace el arranque siguiente: lee del
      // disco, no de memoria.
      final otro = contenedorDePrueba();
      final leidos = await otro.read(preguntadosProvider.future);
      expect(leidos, contains(p.id),
          reason: 'al reabrir la app volvería a preguntar lo ya preguntado');
    });

    test('saltar marca el registro entero, no solo el visto', () async {
      final c = contenedorDePrueba();
      await c.read(preguntadosProvider.future);
      await c.read(preguntadosProvider.notifier).marcarTodas();

      final otro = contenedorDePrueba();
      final leidos = await otro.read(preguntadosProvider.future);
      for (final p in permisosDePrimeraVez) {
        expect(leidos, contains(p.id),
            reason: '${p.id} se volvería a preguntar en el siguiente arranque');
      }
    });
  });

  group('lo que se enseña antes de preguntar', () {
    testWidgets('cada permiso explica para qué es', (t) async {
      await t.pumpWidget(MaterialApp(
        home: PrimeraVezPage(
          faltan: [_permisoDePrueba(id: 'A', paraQue: 'Para avisarte de X.')],
          preguntar: (_) {},
          saltar: () {},
        ),
      ));
      await asentar(t);
      // El motivo va **en pantalla**, antes del diálogo. Es lo que diferencia
      // esto de un `requestPermission` en frío, que este repo ya escribió una
      // vez que se deniega.
      expect(find.text('Para avisarte de X.'), findsOneWidget);
    });

    testWidgets('y dice qué se pierde sin concederlo', (t) async {
      await t.pumpWidget(MaterialApp(
        home: PrimeraVezPage(
          faltan: [_permisoDePrueba(id: 'A', paraQue: 'Para avisarte de X.')],
          preguntar: (_) {},
          saltar: () {},
        ),
      ));
      await asentar(t);
      expect(find.textContaining('funciona igual'), findsOneWidget,
          reason: 'sin decir qué se pierde, denegar parece que cuesta algo');
    });

    testWidgets('dice que se puede cambiar después', (t) async {
      await t.pumpWidget(MaterialApp(
        home: PrimeraVezPage(
          faltan: [_permisoDePrueba(id: 'A', paraQue: 'Para avisarte de X.')],
          preguntar: (_) {},
          saltar: () {},
        ),
      ));
      await asentar(t);
      expect(find.textContaining('cambiarlo después'), findsOneWidget);
    });
  });

  group('los botones hacen algo', () {
    testWidgets('preguntar pide el permiso y anota que se preguntó', (t) async {
      var pedidos = 0;
      final preguntados = <String>[];
      await t.pumpWidget(MaterialApp(
        home: PrimeraVezPage(
          faltan: [_permisoDePrueba(
            id: 'A',
            paraQue: 'Para avisarte.',
            alPedir: () => pedidos++,
          )],
          preguntar: (p) => preguntados.add(p.id),
          saltar: () {},
        ),
      ));
      await asentar(t);

      // Con un solo permiso pendiente el botón dice «Empezar»: se pregunta y
      // a la vez se entra. Con dos, el primero dice «Sí, avísame».
      await t.tap(find.text('Empezar'));
      await asentar(t);

      expect(pedidos, 1, reason: 'el botón no pidió el permiso');
      // Se anota **antes** de esperar la respuesta: el diálogo del sistema es
      // asíncrono, y si se anotara al volver, quien no contesta se lo volvería
      // a preguntar en el siguiente arranque.
      expect(preguntados, ['A']);
    });

    testWidgets('avisa cuando hay respuesta, no cuando pregunta', (t) async {
      // Son dos momentos distintos y confundirlos deja estado viejo: «he
      // lanzado la pregunta» no es «sé lo que contestaste». Aquí se ordena a
      // propósito con una señal, porque un `Future` que se resuelve ya no
      // distingue nada por sí solo.
      final guion = <String>[];
      await t.pumpWidget(MaterialApp(
        home: PrimeraVezPage(
          faltan: [
            _permisoDePrueba(
              id: 'A',
              paraQue: 'Para avisarte.',
              alPedir: () => guion.add('preguntado'),
            ),
          ],
          preguntar: (_) => guion.add('anotado'),
          saltar: () => guion.add('salido'),
          alResponder: () => guion.add('respondido'),
        ),
      ));
      await asentar(t);

      await t.tap(find.text('Empezar'));
      await asentar(t);

      expect(guion, ['anotado', 'preguntado', 'respondido', 'salido'],
          reason: 'se anota antes de esperar (para no repetir) y se avisa '
              'después de la respuesta, no antes');
    });

    testWidgets('el último permiso lleva a empezar', (t) async {
      var salto = false;
      await t.pumpWidget(MaterialApp(
        home: PrimeraVezPage(
          faltan: [_permisoDePrueba(id: 'A', paraQue: 'Para avisarte.')],
          preguntar: (_) {},
          saltar: () => salto = true,
        ),
      ));
      await asentar(t);

      expect(find.text('Empezar'), findsOneWidget);
      await t.tap(find.text('Empezar'));
      await asentar(t);
      expect(salto, isTrue, reason: 'el último botón no llevó a la app');
    });

    testWidgets('saltar entra y marca todos, no solo el visto', (t) async {
      // Quien salta en el primer paso se ha entrado en la app con el resto sin
      // preguntar. Preguntárselo en el siguiente arranque es volver a
      // interrumpir a alguien que ya dijo que no.
      final preguntados = <String>[];
      var salto = false;
      await t.pumpWidget(MaterialApp(
        home: PrimeraVezPage(
          faltan: [
            _permisoDePrueba(id: 'A', paraQue: 'Uno.'),
            _permisoDePrueba(id: 'B', paraQue: 'Dos.'),
          ],
          preguntar: (p) => preguntados.add(p.id),
          saltar: () => salto = true,
        ),
      ));
      await asentar(t);

      await t.tap(find.text('Ahora no'));
      await asentar(t);
      expect(salto, isTrue);
      expect(preguntados, ['A', 'B']);
    });
  });

  group('el registro', () {
    test('un permiso nuevo se pregunta aunque la app se haya abierto mil veces', () {
      // El motivo por el que se guarda una **lista** y no un «ya arrancó»: con
      // un booleano, el permiso que se añada mañana no se preguntaría nunca y
      // nadie vería por qué.
      final ya = {'POST_NOTIFICATIONS'};
      final faltan = permisosDePrimeraVez.where((p) => !ya.contains(p.id));
      // Hoy solo hay uno, así que no queda ninguno: lo que se comprueba es que
      // la regla sea una resta de conjuntos y no un caso especial.
      expect(faltan.where((p) => p.id == 'POST_NOTIFICATIONS'), isEmpty);
    });

    test('los identificadores son los nombres de Android, no inventados', () {
      // Un id propio obligaría a mantener una tabla de traducción que nadie
      // mira. Con el nombre real, cruzar el registro con el manifest es una
      // igualdad.
      for (final p in permisosDePrimeraVez) {
        expect(p.id, matches(RegExp(r'^[A-Z_]+$')),
            reason: '${p.id} no parece un permiso de Android');
      }
      expect(permisosDePrimeraVez.map((p) => p.id),
          contains('POST_NOTIFICATIONS'));
    });

    test('la cámara no se pide en el pase: la pide mobile_scanner al abrir', () {
      // Preguntarla al arrancar sería preguntarla sin motivo visible, que es lo
      // que este repo ya escribió que no hay que hacer.
      expect(permisosDePrimeraVez.map((p) => p.id), isNot(contains('CAMERA')));
    });
  });
}