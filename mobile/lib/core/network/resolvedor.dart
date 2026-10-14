/// Decidir **a qué** bridge se le habla.
///
/// ## Por qué esto no es una función de una línea
/// Hay tres candidatos y ninguno gana siempre: el que se anuncia por mDNS, el
/// que viene compilado (Tailscale) y `localhost`. Elegir el primero de la lista
/// sin comprobar nada es la forma de tener un fallo que depende de la red: en la
/// casa funciona y fuera no, sin que ningún log diga por qué.
///
/// La regla es: **todos se prueban y se queda el que responde `/health`**, en ese
/// orden. El orden no es arbitrario, y está en [candidatos].
///
/// ## La salvedad que separa [intentos] de [resolver]
/// La lista de candidatos se usa para **mirar** —en Diagnóstico— y para
/// **elegir** —en cada petición—, y desde que la app guarda semillas TOTP ya no
/// pueden ser lo mismo: mirar un anuncio de mDNS es diagnóstico, y **obedecer**
/// a un anuncio de mDNS es dejar que cualquiera en la LAN reciba el token de la
/// API. Por eso [resolver] no mira la red local cuando hay host compilado, y
/// [intentos] sigue enseñándola entera. Ver [resolver].
library;

import 'dart:async';

import 'package:dio/dio.dart';

import '../config/app_config.dart';
import 'descubrimiento.dart';

/// Cómo se buscan los bridges de la red.
///
/// ## Por qué es un `typedef` y no una interfaz
/// Porque lo que se cambia en un test es **la respuesta de la red**, no la
/// lógica de buscarla. Con un `typedef` el test pasa una lista y el `Resolvedor`
/// sigue haciendo lo mismo que en producción —ordenar candidatos, deduplicar,
/// sondear en orden, quedarse con el primero sano—, que es justo lo que hay que
/// probar. Con una interfaz habría que reimplementar el descubrimiento entero y
/// el test pasaría sin haber ejercitado el orden.
typedef BuscadorBridge = Future<List<BridgeEncontrado>> Function();

/// Qué responde un candidato cuando se le pregunta si está vivo.
///
/// ## Por qué devuelve el JSON y no un `bool`
/// Porque el detalle importa para el diagnóstico: «no contesta» y «contesta
/// pero degradado» son fallos distintos, y verlos necesita los campos. Devolver
/// solo un `bool` obliga a la pantalla a inventar el motivo.
typedef SondeadorBridge = Future<Map<String, dynamic>> Function(String base);

/// Un intento de conexión y lo que dio de sí.
class Intento {
  const Intento({
    required this.base,
    required this.ok,
    this.origen = '',
    this.detalle = '',
  });

  final String base;
  final bool ok;

  /// De dónde salió el candidato: `mDNS`, `compilado`, `loopback`.
  ///
  /// Sin esto, un fallo dice «no encuentro el bridge» y no dice cuál se probó,
  /// que es la información que hace falta para arreglarlo.
  final String origen;
  final String detalle;
}

/// Eligió un base de URL entre los candidatos.
class Resolvedor {
  /// ## Por qué el descubridor es público y no privado
  /// Un parámetro con nombre que empieza por guion bajo no se puede pasar desde
  /// otro library, y el test lo necesita. Es más honesto que un
  /// `this._descubridor` que obliga a construirlo en un factory aparte.
  Resolvedor({
    required this.config,
    Descubridor? descubridor,
    BuscadorBridge? buscar,
    SondeadorBridge? sondear,
  })  : _buscar = buscar ??
            (descubridor?.buscar ?? _sinCandidatos),
        _sondear = sondear ?? _sondearPorHttp;

  final AppConfig config;

  /// Cómo se buscan los bridges de la red. Por defecto, mDNS.
  final BuscadorBridge _buscar;

  /// Cómo se comprueba que un candidato vive. Por defecto, `GET /health`.
  final SondeadorBridge _sondear;

  /// Cuando no hay descubridor —los tests, o una app que no quiere mDNS— no hay
  /// candidatos de red local, y eso no es un error: se prueba lo demás.
  static Future<List<BridgeEncontrado>> _sinCandidatos() async => const [];

  /// Los candidatos, en el orden en que se prueban.
  ///
  /// ## Por qué este orden y no otro
  /// **mDNS primero**: es la red local, sin cifrado ni saltos, y es la que
  /// sobrevive a que el router cambie la IP del bridge. Es la que debería ganar
  /// en casa, que es donde está la persona casi siempre.
  ///
  /// **Compilado después**: Tailscale es la red privada que funciona cuando el
  /// móvil está en datos o la local no le deja el multicast. Es lenta comparada
  /// con la local, no más fiable.
  ///
  /// **`localhost` al final**: sirve para el emulador con `adb reverse` y para los
  /// tests. Nunca debe ganar a un bridge real, porque si el emulador encaja con
  /// el bucle local, cualquier fallo del bridge **parece** un fallo de la app.
  /// Un buscador con plazo, y que **siempre** termina.
  ///
  /// ## El `.then` con tipo explícito no es cosmético: es el arreglo
  /// `Future.timeout` decide el tipo de `onTimeout` por el tipo **de ejecución**
  /// del future, no por el declarado. Un buscador que solo lanza —`() async =>
  /// throw …`— se compila como `Future` de `Never`, así que `timeout` espera un
  /// `onTimeout` de `Future<Never>` y el `await` recibe el **fallo de tipos** como
  /// si fuera una excepción en tiempo de ejecución. El `on Object` lo traga, la
  /// resolución sigue sin mDNS, y no aparece nada en ningún log: compila, el test
  /// pasa, y la red desaparece.
  ///
  /// Declarar el tipo de la variable no lo arregla —este arrange lo probó—, y
  /// porque el tipo de ejecución sigue siendo `Never`. Lo que lo arregla es
  /// **construir un future nuevo** con el tipo que se quiere: de ahí el `.then`
  /// con tipo explícito.
  Future<List<BridgeEncontrado>> _conPlazo(
    BuscadorBridge buscar,
    Duration plazo,
  ) =>
      buscar()
          .then<List<BridgeEncontrado>>((r) => r)
          .timeout(plazo, onTimeout: () => const <BridgeEncontrado>[]);

  Future<List<Intento>> intentos() async {
    final vistos = <String, String>{};

    for (final c in await _candidatos()) {
      vistos.putIfAbsent(c.base, () => c.origen);
    }

    final out = <Intento>[];
    for (final c in vistos.entries) {
      final i = await _probar(c.key, c.value);
      out.add(i);
    }
    return out;
  }

  /// La base contra la que hablar, o `null` si nadie responde.
  ///
  /// ## Por qué devuelve `String` y no el `Intento`
  /// Porque quien llama —el cliente HTTP— solo necesita la URL. Devolver el
  /// intento entero hace que cada consumidor tenga que acordarse de mirar el
  /// campo, y uno se olvidará.
  ///
  /// ## Por qué con host compilado **no** se consulta mDNS
  /// Porque el que gana la resolución se convierte en el que recibe el
  /// `X-Aegis-Token` **en todas las peticiones**, y el orden era
  /// «el primero que conteste `/health`». Eso no es descubrir un bridge: es
  /// **aceptar que cualquiera en la LAN pueda convertirse en el bridge**. Basta
  /// con anunciar `_aegis._tcp.local` y contestar `{"status":"ok"}` — que es
  /// exactamente lo que el sondeo comprueba, y no comprueba nada más. La
  /// app no distinguía «el bridge» de «un host que dice ser el bridge».
  ///
  /// ## Por qué no se pierde nada, corrigiendo el motivo antiguo
  /// El orden anterior justificaba el mDNS primero con que «el compilado es una
  /// IP que el router puede cambiar». Eso es cierto para la IP de casa y
  /// **falso para Tailscale**: un `100.x` lo asigna el plano de control de la
  /// malla y no se mueve porque el router cambie, porque te mude de casa o
  /// porque el ISP te dé otra IP. La premise del trade-off era incorrecta, así
  /// que el trade-off no se estaba pagando por nada.
  ///
  /// Lo que sí cambia: si el host compilado no responde, aquí se devuelve
  /// `null` —**falla cerrado**— en vez de repartirse por la lista. Quien lo
  /// recibe (`AgentRepositoryImpl._base`) cae al host compilado y ve el error de
  /// verdad, en vez de hablar con quien haya ganado el multicast.
  ///
  /// [intentos] sigue viendo la lista entera, así que Diagnóstico **sí** enseña
  /// lo que se anuncia por mDNS: se puede seguir mirando por qué la app no
  /// llega, aunque ya no obedezca al anuncio.
  Future<String?> resolver() async {
    if (config.usesMeshHostname) {
      final i = await _probar(config.httpBase, 'compilado');
      return i.ok ? i.base : null;
    }
    for (final i in await intentos()) {
      if (i.ok) return i.base;
    }
    return null;
  }

  Future<List<({String base, String origen})>> _candidatos() async {
    final lista = <({String base, String origen})>[];

    // mDNS primero. Un fallo aquí **no** es un fallo: puede que el multicast
    // esté bloqueado, que no haya nadie, o que el móvil esté en datos. Por eso
    // va con `catchError` y sigue.
    //
    // El `timeout` es la segunda red de seguridad, y no sobra aunque
    // `Descubridor` ya tenga el suyo: aquí la consecuencia de un cuelgue es
    // distinta. Un `await` colgado aquí retiene **toda** la resolución, y con
    // ella todas las peticiones de la app —se vio en el emulador—. Un `catch`
    // sobre una `Future` que nunca termina no se ejecuta nunca, así que el plazo
    // tiene que estar en el `await`, no alrededor.
    try {
      final encontrados = await _conPlazo(_buscar, Descubridor.topeBusqueda);
      for (final b in encontrados) {
        lista.add((base: b.base, origen: 'mDNS'));
      }
    } on Object {
      // Sin mDNS no se muere: se prueba lo demás.
    }

    // El host compilado. `usesMeshHostname` evita añadir `localhost:8000` dos
    // veces cuando el define no está.
    if (config.usesMeshHostname) {
      lista.add((base: config.httpBase, origen: 'compilado'));
    }
    lista.add((base: 'http://localhost:8000', origen: 'loopback'));

    return lista;
  }

  /// Prueba un candidato con `/health`, que es lo que el bridge ya expone y lo
  /// que Diagnóstico ya enseña.
  ///
  /// ## Por qué `/health` y no un `HEAD /`
  /// Porque `/health` **solo devuelve 200 si el bridge entero está bien**, con su
  /// estado. Un `HEAD /` a un puerto abierto da 200 con cualquier cosa que escuche
  /// ahí, y da un «encontrado» sobre un bridge que está de pie pero muerto por
  /// dentro —la peor forma de falso éxito, y ya se pagó una en este repo (A-016).
  Future<Intento> _probar(String base, String origen) async {
    try {
      final j = await _sondear(base);
      return Intento(
        base: base,
        ok: _vivo(j),
        origen: origen,
        // El detalle se enseña cuando falla: sin él, «no encuentra el bridge» y
        // «el bridge contesta pero está degradado» son la misma línea para quien
        // lee.
        detalle: 'status=${j['status']} · ok=${j['ok']} · hermes=${j['hermes_ok']} · ollama=${j['ollama_ok']}',
      );
    } on Object catch (e) {
      return Intento(base: base, ok: false, origen: origen, detalle: _motivo(e));
    }
  }

  /// Si esta respuesta dice que hay un bridge detrás.
  ///
  /// ## Por qué se aceptan `ok` y `status`, y por qué esto ya pasó
  /// `/health` devuelve **`status: "ok"`**, no `ok: true`. El `ok` que sí existe
  /// es el de Ollama, anidado. Aquí sePedía `ok` en la raíz, así que **el bridge
  /// vivo se leía como muerto**: el sondeo contestaba 200 y con cuerpo, y el
  /// resolutor lo tiraba.
  ///
  /// Dos piezas que parecían rotas y eran un contrato inventado. Y lo caro: no
  /// salía ningún error, porque un 200 con cuerpo raro no es un error para nadie.
  /// La app se quedaba «buscando proyectos…» para siempre sin una sola línea en
  /// el log —y el bridge, tan vivo, registrando cada sondeo en el suyo.
  ///
  /// Se aceptan los dos porque son las dos formas que ha tenido este endpoint, y
  /// porque un cliente nuevo tiene que funcionar contra el bridge que hay, no
  /// contra el que uno se imagina.
  static bool _vivo(Map<String, dynamic> j) =>
      j['ok'] == true || j['status'] == 'ok';

  /// Cuánto se espera a un candidato antes de declararlo muerto.
  ///
  /// Corto a propósito: probar tres candidatos a 10 s cada uno son 30 s de
  /// pantalla en blanco antes de decir que no hay nadie. 4 s basta para un bridge
  /// de la red de la casa, donde se llega en milisegundos.
  static const Duration esperaPorCandidato = Duration(seconds: 4);

  /// El sondeo real: `GET /health`, que es lo que el bridge ya expone y lo que
  /// Diagnóstico ya enseña.
  ///
  /// ## Por qué `/health` y no un `HEAD /`
  /// Porque `/health` **solo devuelve 200 si el bridge entero está bien**, con su
  /// estado. Un `HEAD /` a un puerto abierto da 200 con cualquier cosa que escuche
  /// ahí, y produce un «encontrado» sobre un bridge que está de pie pero muerto
  /// por dentro —la peor forma de falso éxito, y ya se pagó una en este repo
  /// (A-016).
  static Future<Map<String, dynamic>> _sondearPorHttp(String base) async {
    final dio = Dio(BaseOptions(
      baseUrl: base,
      connectTimeout: esperaPorCandidato,
      receiveTimeout: esperaPorCandidato,
      // Sin cabeceras de auth: aquí solo se quiere saber **quién** contesta.
      // La llamada real la hace el cliente con su token.
      headers: const {'Accept': 'application/json'},
    ));
    final r = await dio.get<Map<String, dynamic>>('/health');
    return r.data ?? const <String, dynamic>{};
  }

  /// Traduce el fallo a una frase que diga algo.
  ///
  /// Los tres tipos de sin-respuesta se juntan a propósito: para quien lee, un
  /// `connectionError` y un `connectionTimeout` son la misma cosa —no hay nadie
  /// ahí— y separarlos inventa una distinción que no está en el problema.
  static String _motivo(Object e) {
    if (e is DioException) {
      return switch (e.type) {
        DioExceptionType.connectionError ||
        DioExceptionType.connectionTimeout ||
        DioExceptionType.receiveTimeout =>
          'sin respuesta',
        _ => e.message ?? e.type.name,
      };
    }
    return '$e';
  }
}