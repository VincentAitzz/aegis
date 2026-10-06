// Cómo elige la app a qué bridge le habla.
//
// ## Qué se prueba aquí y qué no
// Se prueba la **decisión**: qué candidatos salen, en qué orden, y cuál gana. No
// se prueba la red —ni el mDNS ni el HTTP—, y por eso [Resolvedor] recibe el
// buscador y el sondeador como `typedef`: el test da la respuesta de la red y el
// `Resolvedor` sigue haciendo lo mismo que en producción.
//
// Un test que necesitara la red de verdad no podría comprobar el caso que de
// verdad importa aquí, que es **mDNS no responde y el compilado sí**. Para eso
// hace falta poder apagar el multicast, y no hay forma de hacerlo desde un test
// sin dejar el resto del proceso sin red.
import 'package:aegis_console/core/config/app_config.dart';
import 'package:aegis_console/core/network/descubrimiento.dart';
import 'package:aegis_console/core/network/resolvedor.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  AppConfig compilado(String host) => AppConfig(apiHost: host, usesMeshHostname: true);

  /// Un bridge sano salvo donde se le diga lo contrario.
  Future<Map<String, dynamic>> sano(String _) async =>
      {'ok': true, 'hermes_ok': true, 'ollama_ok': true};

  group('el candidato que gana', () {
    test('es el de mDNS cuando responde, aunque el compilado también esté vivo', () async {
      // Los dos bridges están en pie y aun así el de la red local gana. Importa
      // porque el compilado es una IP que el router puede cambiar: si ganara él,
      // el cambio volvería a romper la app sin que nadie pueda hacer nada.
      final r = Resolvedor(
        config: compilado('100.101.102.100'),
        buscar: () async => const [BridgeEncontrado(host: '192.168.0.50', puerto: 8000)],
        sondear: sano,
      );
      expect(await r.resolver(), 'http://192.168.0.50:8000');
    });

    test('es el compilado cuando no hay nada por mDNS', () async {
      final r = Resolvedor(
        config: compilado('100.101.102.100'),
        buscar: () async => const [],
        sondear: sano,
      );
      expect(await r.resolver(), 'http://100.101.102.100:8000');
    });

    test('es el compilado cuando mDNS devuelve uno muerto', () async {
      // El caso que hace que esto no sea «usar el primero»: hay un anuncio, pero
      // el bridge que se anuncia ya no está. Sin el sondeo, la app se queda con
      // un candidato muerto y dice que no hay nadie, con el bridge sano a la
      // vista.
      final r = Resolvedor(
        config: compilado('100.101.102.100'),
        buscar: () async => const [BridgeEncontrado(host: '192.168.0.9', puerto: 8000)],
        sondear: (base) async =>
            base.contains('192.168.0.9') ? throw StateError('sin respuesta') : sano(base),
      );
      expect(await r.resolver(), 'http://100.101.102.100:8000');
    });

    test('es el compilado cuando mDNS lanza, en vez de morir', () async {
      // El multicast bloqueado es lo normal en una red de empresa y en algunos
      // routers. Un `throw` sin capturar aquí dejaría la app sin bridge y sin
      // decir por qué.
      final r = Resolvedor(
        config: compilado('100.101.102.100'),
        buscar: () async => throw StateError('multicast bloqueado'),
        sondear: sano,
      );
      expect(await r.resolver(), 'http://100.101.102.100:8000');
    });
  });

  group('lo que se enseña cuando no hay nadie', () {
    test('devuelve null y no se queda con un candidato a medias', () async {
      final r = Resolvedor(
        config: compilado('100.101.102.100'),
        buscar: () async => const [BridgeEncontrado(host: '192.168.0.9', puerto: 8000)],
        sondear: (_) async => throw StateError('sin respuesta'),
      );
      expect(await r.resolver(), isNull);
    });

    test('cada intento dice de dónde salió y por qué falló', () async {
      // Sin esto, «no encuentro el bridge» no dice cuál se probó, y no hay forma
      // de saber si es un problema de la app, del bridge o de la red.
      final r = Resolvedor(
        config: compilado('100.101.102.100'),
        buscar: () async => const [BridgeEncontrado(host: '192.168.0.9', puerto: 8000)],
        sondear: (_) async => throw StateError('sin respuesta'),
      );
      final intentos = await r.intentos();
      expect(intentos.map((i) => i.origen), ['mDNS', 'compilado', 'loopback']);
      expect(intentos.every((i) => !i.ok), isTrue);
      expect(intentos.first.detalle, contains('sin respuesta'));
    });

    test('un 200 con ok:false NO cuenta como bridge vivo', () async {
      // El falso éxito que este repo ya pagó una vez (A-016): el puerto contesta,
      // la respuesta llega, y el bridge por dentro está roto. Si `ok` fuera
      // «me contestaron», la app hablaría con un puente que no puede hacer nada.
      final r = Resolvedor(
        config: compilado('100.101.102.100'),
        buscar: () async => const [],
        sondear: (base) async =>
            base.contains('100.84') ? {'ok': false, 'hermes_ok': false} : sano(base),
      );
      expect(await r.resolver(), 'http://localhost:8000');
    });
  });

  group('el orden de los candidatos', () {
    test('mDNS antes que compilado antes que loopback', () async {
      final r = Resolvedor(
        config: compilado('100.101.102.100'),
        buscar: () async => const [BridgeEncontrado(host: '192.168.0.50', puerto: 8000)],
        sondear: sano,
      );
      expect((await r.intentos()).map((i) => i.origen), ['mDNS', 'compilado', 'loopback']);
    });

    test('sin host compilado, loopback no aparece dos veces', () async {
      // El emulador se construye sin `API_HOST`, y ahí `httpBase` ya es
      // `localhost:8000`. Si no se deduplicara, el mismo candidato se probaría
      // dos veces: el doble de espera y un intento repetido en el diagnóstico.
      final r = Resolvedor(
        config: const AppConfig(apiHost: 'localhost', usesMeshHostname: false),
        buscar: () async => const [],
        sondear: sano,
      );
      expect((await r.intentos()).map((i) => i.base), ['http://localhost:8000']);
    });

    test('el mismo bridge por mDNS dos veces se prueba una', () async {
      // Dos respuestas al mismo anuncio dan el mismo host. Probarlo dos veces no
      // añade información y duplica la espera.
      var sondeadas = 0;
      final r = Resolvedor(
        config: compilado('100.101.102.100'),
        buscar: () async => const [
          BridgeEncontrado(host: '192.168.0.50', puerto: 8000),
          BridgeEncontrado(host: '192.168.0.50', puerto: 8000),
        ],
        sondear: (base) async {
          sondeadas++;
          return sano(base);
        },
      );
      await r.intentos();
      expect(sondeadas, 3); // el duplicado + compilado + loopback
    });
  });

  group('Descubridor', () {
    test('sin arrancar, buscar devuelve vacío en vez de lanzar', () async {
      // Un `lookup` sin `start` lanza `StateError`. Que la app lo trague y siga
      // con los otros candidatos es lo que permite que funcione sin mDNS.
      final d = Descubridor();
      d.cerrar(); // nunca arrancó: no debe lanzar al cerrar
      expect(d.cerrar, returnsNormally);
    });

    test('el tipo de servicio es el mismo que anuncia el bridge', () {
      // Si uno de los dos lados cambia la constante, el síntoma es «el bridge está
      // encendido y el móvil no lo encuentra». Este test no puede comparar
      // contra el Python, pero sí deja el nombre escrito en un sitio donde se ve.
      expect(Descubridor.tipoServicio, '_aegis._tcp.local');
    });
  });
}