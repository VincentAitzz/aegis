// ¿Termina alguna vez una llamada del repositorio **de verdad**?
//
// ## Qué se prueba aquí
// Que `AgentRepositoryImpl` con su interceptor devuelve una respuesta. No la URL
// que compone —de eso se ocupa `base_dio_test.dart`— sino que la petición
// **llega a salir**.
//
// ## Por qué este test existe
// El interceptor resolvía la base y nunca llamaba a `handler.next(options)`. En
// Dio 5 `onRequest` no continúa solo, así que cada una de las 35 llamadas se
// quedaba esperando una respuesta que no iba a llegar: sin excepción, sin
// socket, sin nada en el log de red. En el emulador, la app entera se quedaba en
// «buscando proyectos…».
//
// Lo que lo escondió fue que **todos** los tests del repositorio usaban un doble
// que no pasa por Dio. El fallo estaba en la única capa que nadie ejecutaba. Un
// doble puede ser más cómodo que la red y ser, a la vez, el sitio donde se
// esconden los fallos de la capa real.
import 'dart:convert';
import 'dart:typed_data';

import 'package:aegis_console/core/config/app_config.dart';
import 'package:aegis_console/core/network/resolvedor.dart';
import 'package:aegis_console/data/repositories/agent_repository_impl.dart';
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

/// Un adaptador que contesta lo que se le pida, sin tocar la red.
///
/// ## Por qué un adaptador y no un servidor de verdad
/// Lo que se prueba es la **cadena de Dio**: que el interceptor suelte la
/// petición. Un `HttpServer` de verdad añadiría un puerto, un bind y un
/// `tearDown`, y seguiría sin comprobar lo que importa: si `handler.next()` se
/// llamó alguna vez.
class _AdaptadorFalso implements HttpClientAdapter {
  _AdaptadorFalso({this.estado = 200, this.respuesta = const {}, this.deCabecera = const {}});

  final int estado;
  final Map<String, dynamic> respuesta;
  final Map<String, String> deCabecera;

  final List<Uri> pedidas = [];
  final List<Map<String, List<String>>> cabeceras = [];

  @override
  void close({bool force = false}) {}

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    pedidas.add(options.uri);
    cabeceras.add(options.headers.map((k, v) => MapEntry(k, [v])));
    return ResponseBody.fromString(
      jsonEncode(respuesta),
      estado,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
        ...deCabecera.map((k, v) => MapEntry(k, [v])),
      },
    );
  }
}

void main() {
  late _AdaptadorFalso adaptador;

  final AppConfig config =
      const AppConfig(apiHost: '10.0.2.2', usesMeshHostname: false);

  AgentRepositoryImpl repoCon({_AdaptadorFalso? con}) {
    adaptador = con ?? _AdaptadorFalso();
    return AgentRepositoryImpl(
      config: config,
      // El sondeo dice que el bridge vive, sin red: lo que se prueba es la
      // petición del repositorio, no el descubrimiento (que tiene sus tests).
      resolvedor: Resolvedor(
        config: config,
        buscar: () async => const [],
        sondear: (_) async => const {'status': 'ok'},
      ),
      adaptador: adaptador,
    );
  }

  test('una llamada del repositorio termina y llega al servidor', () async {
    // El fallo era una `Future` que no completaba nunca. Sin este timeout, un
    // cuelgue futuro se convierte otra vez en un test que se queda esperando
    // hasta que lo corte el runner, y el síntoma vuelve a ser «no sé qué pasa».
    final repo = repoCon();

    final respuesta = await repo.projects().timeout(
      const Duration(seconds: 10),
      onTimeout: () =>
          fail('projects() no terminó: la petición se quedó en el interceptor'),
    );

    expect(respuesta, isEmpty);
    expect(adaptador.pedidas.single.path, '/proyectos');
  }, timeout: const Timeout(Duration(seconds: 30)));

  test('y manda el token y el origen, no solo la URL', () async {
    // Lo que sale bien es que la cabecera viaja: sin token el bridge responde
    // 401, y eso en el móvil es «la app no hace nada» sin explicación.
    final repo = repoCon();
    await repo.projects().timeout(const Duration(seconds: 10));
    expect(adaptador.cabeceras.last['X-Aegis-Token'], isNotNull);
    expect(adaptador.cabeceras.last.containsKey('X-Aegis-Origen'), isTrue);
  }, timeout: const Timeout(Duration(seconds: 30)));

  test('un 409 enseña el motivo que viene en la cabecera', () async {
    // El caso que se vio en el emulador: el APK era más viejo que el código, el
    // bridge contestaba 409, y el móvil decía «el bridge no tiene un APK que
    // servir todavía». Lo que pasaba era que había un APK y lo que faltaba era
    // recompilarlo — dos mundos distintos, y el mensaje mandaba al sitio
    // equivocado.
    //
    // El motivo llega en cabecera porque esta llamada es un `HEAD`, y un `HEAD`
    // no tiene cuerpo: leerlo del `detail`, que es lo natural, lo pierde siempre.
    final repo = repoCon(con: _AdaptadorFalso(
      estado: 409,
      respuesta: const {'detail': 'el APK no representa el código de ahora'},
      deCabecera: const {'x-aegis-motivo': 'recompila: el codigo cambio'},
    ));

    final v = await repo
        .versionApk(instalado: 3, hayPermiso: true)
        .timeout(const Duration(seconds: 10));

    expect(v.motivo, contains('recompila'));
    expect(v.versionCode, 0);
  }, timeout: const Timeout(Duration(seconds: 30)));

  test('un 200 normal enseña la versión de la cabecera', () async {
    final repo = repoCon(con: _AdaptadorFalso(
      deCabecera: const {
        'x-aegis-version': '6',
        'x-aegis-version-name': '1.0.5',
      },
    ));

    final v = await repo
        .versionApk(instalado: 3, hayPermiso: true)
        .timeout(const Duration(seconds: 10));

    expect(v.versionCode, 6);
    expect(v.disponible, isTrue);
    expect(v.motivo, isEmpty);
  }, timeout: const Timeout(Duration(seconds: 30)));

  test('un 401 no se disfraza de «no hay APK»', () async {
    // El fallo real: el APK base estaba compilado sin token, el HEAD volvía 401
    // y la app pintaba «el bridge no tiene un APK que servir todavía». Eso manda
    // a mirar la puerta del bridge, que estaba bien, y no al token, que estaba
    // roto. Un motivo que no lleva a su sitio cuesta más que ningún motivo.
    final repo = repoCon(con: _AdaptadorFalso(
      estado: 401,
      respuesta: const {'detail': 'token inválido'},
    ));

    final v = await repo
        .versionApk(instalado: 8, hayPermiso: true)
        .timeout(const Duration(seconds: 10));

    expect(v.versionCode, 0);
    expect(v.motivo, contains('token'));
    expect(v.motivo, isNot(contains('no tiene un APK')));
  }, timeout: const Timeout(Duration(seconds: 30)));

  test('y una versión igual no se anuncia como nueva', () async {
    // Si se anunciara, el móvil ofrecería una «actualización» que no cambia
    // nada y gastaría 50 MB y una confirmación de Android en ello.
    final repo = repoCon(con: _AdaptadorFalso(
      deCabecera: const {'x-aegis-version': '3'},
    ));
    final v = await repo
        .versionApk(instalado: 3, hayPermiso: true)
        .timeout(const Duration(seconds: 10));
    expect(v.disponible, isFalse);
  }, timeout: const Timeout(Duration(seconds: 30)));
}
