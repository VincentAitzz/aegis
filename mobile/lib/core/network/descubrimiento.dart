/// Encontrar el bridge en la red local, sin que nadie escriba su IP.
///
/// ## Por qué esto existe
/// El host de la API iba compilado con `--dart-define=API_HOST=100.101.102.100`. La
/// primera vez que la IP de la casa cambie —y cambia, cada cierto tiempo— la app
/// deja de encontrar a Aegis y no hay nada que el usuario pueda hacer. Eso se
/// esconde detrás de «funcionaba en mi casa», que es la clase de problema más
/// cara que hay: no se reproduce y no aparece en ningún log.
///
/// ## Por qué mDNS y no una IP fija
/// `multicast_dns` pregunta por `_aegis._tcp.local` y recibe los registros PTR,
/// SRV y A. El nombre del servicio lo pone el bridge al anunciarse
/// (`bridge/app/descubrimiento.py`); la instancia se llama `aegis-bridge` y el
/// `SRV` trae el puerto. Un cambio de IP en el router no cambia nada de esto.
///
/// ## Por qué Tailscale sigue ahí, y de plan B
/// Porque mDNS no sale de la red: solo funciona si el móvil y el bridge están en
/// el mismo segmento local **y** el router deja pasar el multicast. Un móvil en
/// datos, o detrás de una VPN, no lo ve. El Tailscale compilado es la red
/// privada que funciona cuando la local no; mDNS es la que no depende de que
/// nadie recuerde una IP.
///
/// ## Lo que esto NO hace
/// No escanea puertos ni prueba rangos de IP. El barcode es un anuncio explícito
/// de un servicio que dice quién es, y sondear la red de la casa para adivinar
/// qué hay es otra cosa.
library;

import 'dart:async';

import 'package:multicast_dns/multicast_dns.dart';

/// Un bridge encontrado, con lo mínimo para hablar con él.
class BridgeEncontrado {
  const BridgeEncontrado({required this.host, required this.puerto, this.nombre});

  /// IP del host, del registro `A`.
  final String host;
  final int puerto;

  /// Nombre de la instancia, para distinguirlo de otro bridge.
  final String? nombre;

  String get base => 'http://$host:$puerto';

  @override
  String toString() => nombre == null ? base : '$base ($nombre)';

  @override
  bool operator ==(Object other) =>
      other is BridgeEncontrado && other.host == host && other.puerto == puerto;

  @override
  int get hashCode => Object.hash(host, puerto);
}

/// Busca bridges por mDNS.
///
/// ## Por qué una clase y no una función suelta
/// Porque `MDnsClient` tiene un socket que hay que cerrar, y un `lookup` que se
/// puede quedar esperando. Sin un sitio donde vivir ese estado, cada pantalla
/// que busca abre un socket nuevo y lo pierde: los tests que cuelgan y los
/// sockets acumulados en el dispositivo son el mismo bug.
class Descubridor {
  Descubridor({MDnsClient? cliente}) : _cliente = cliente ?? MDnsClient();

  final MDnsClient _cliente;
  bool _arrancado = false;

  /// El tipo de servicio que anuncia el bridge.
  ///
  /// Tiene que ser **exactamente** el mismo en los dos lados. Si uno cambia y el
  /// otro no, el síntoma es «el bridge está encendido y el móvil no lo
  /// encuentra», que no se diagnostica sin leer los dos ficheros.
  static const String tipoServicio = '_aegis._tcp.local';

  /// Busca bridges durante [espera] y devuelve **todos** los que respondieron.
  ///
  /// ## Por qué todos y no el primero
  /// Puede haber un bridge en la red de la casa y otro en una máquina virtual,
  /// y quedarse con el primero que conteste es acertar por casualidad. Quien
  /// llama comprueba cuál responde `/health` y descarta el resto.
  ///
  /// ## Por qué `List` y no `Stream`
  /// Porque se busca en un momento concreto —cuando lo pide quien busca— y
  /// devolver un `Stream` obligaría al widget a gestionar un `StreamSubscription`,
  /// que es donde se cuelgan las apps. Aquí el alcance está acotado por [espera] y
  /// se cierra al terminar.
  Future<List<BridgeEncontrado>> buscar({
    Duration espera = const Duration(seconds: 3),
  }) async {
    if (!_arrancado) {
      await _cliente.start();
      _arrancado = true;
    }

    final punteros = await _reintentar<PtrResourceRecord>(
      ResourceRecordQuery.serverPointer(tipoServicio),
      espera,
    );
    if (punteros.isEmpty) return const [];

    final encontrados = <BridgeEncontrado>{};
    for (final ptr in punteros) {
      final instancia = await _uno(ptr.domainName, espera);
      if (instancia != null) encontrados.add(instancia);
    }
    return encontrados.toList();
  }

  /// Resuelve una instancia: puerto del `SRV`, IP del `A`.
  ///
  /// Los dos se piden **a la vez** y se usa lo que haya llegado. Se hacen juntos
  /// porque van en la misma respuesta mDNS y pedirlos por turnos dobla la
  /// espera —que es la parte que la persona nota— para nada.
  ///
  /// Si solo llega el `A` se usa el puerto por defecto; si solo llega el `SRV` no
  /// se puede inventar la IP y se devuelve `null`, que es mejor que devolver un
  /// host vacío que luego falla en el HTTP con un mensaje que no señala la causa.
  Future<BridgeEncontrado?> _uno(String nombre, Duration espera) async {
    final srvFuture = _reintentar<SrvResourceRecord>(
      ResourceRecordQuery.service(nombre),
      espera,
    );
    final aFuture = _reintentar<IPAddressResourceRecord>(
      ResourceRecordQuery.addressIPv4(nombre),
      espera,
    );

    final srv = await srvFuture;
    final a = await aFuture;
    if (a.isEmpty) return null;

    return BridgeEncontrado(
      host: a.first.address.address,
      puerto: srv.isEmpty ? 8000 : srv.first.port,
      nombre: nombre.endsWith('.') ? nombre.substring(0, nombre.length - 1) : nombre,
    );
  }

  /// Un `lookup` que no deja que un registro ausente tumbe la búsqueda entera.
  ///
  /// ## Por qué reintenta
  /// mDNS esudp: un único paquete se pierde. Un `A` que no llegó en el primer
  /// intento devuelve una lista vacía, y sin reintentar eso se lee como «no hay
  /// ningún bridge», que es un mensaje **falso** sobre un fallo de red. Se
  /// reintenta una vez con un margen corto: si de verdad no hay nada, se pierde
  /// un momento y se dice la verdad.
  Future<List<T>> _reintentar<T extends ResourceRecord>(
    ResourceRecordQuery consulta,
    Duration espera,
  ) async {
    for (var intento = 0; intento < 2; intento++) {
      try {
        final r = await _cliente.lookup<T>(consulta, timeout: espera).toList();
        if (r.isNotEmpty) return r;
      } on Object {
        // Un `lookup` puede lanzar si el cliente no está arrancado o si el
        // paquete viene mal formado. Es el mismo caso que «no llegó»: se
        // reintenta y, si tampoco, se devuelve vacío.
      }
      if (intento == 0) await Future<void>.delayed(const Duration(milliseconds: 250));
    }
    return const [];
  }

  /// Cierra el socket. Sin esto el proceso se queda con el descriptor abierto.
  void cerrar() {
    if (!_arrancado) return;
    _cliente.stop();
    _arrancado = false;
  }
}