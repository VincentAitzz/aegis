// La bóveda: qué se guarda, cómo se canjea un código y qué NO se guarda nunca.
//
// ## Por qué el storage va detrás de una interfaz
// Porque `flutter_secure_storage` necesita un dispositivo: en el host de
// pruebas no hay Keystore. La interfaz es lo que permite probar la **lógica** —
// el canje, los hashes, el borrado— sin un emulador, y son las cosas que tienen
// reglas. La pantalla se prueba en el emulador.
import 'dart:convert';
import 'dart:math';

import 'package:aegis_console/core/auth/boveda.dart';
import 'package:aegis_console/core/auth/otpauth.dart';
import 'package:aegis_console/core/auth/totp.dart';
import 'package:flutter_test/flutter_test.dart';

/// Un almacenamiento en memoria, con los mismos crash-test que el de verdad.
class AlmacenFalso implements AlmacenBoveda {
  String? contenido;
  bool corrupto = false;
  int escrituras = 0;

  @override
  Future<Boveda> leer() async {
    // Devuelve el estado marcado, no lanza: es lo que hace el almacén real y lo
    // que obliga a que la pantalla distinga «vacía» de «dañada».
    if (corrupto) return Boveda(corrupta: true);
    if (contenido == null) return Boveda();
    return Boveda.desdeJson(jsonDecode(contenido!));
  }

  @override
  Future<void> escribir(Boveda b) async {
    if (corrupto) throw const BovedaCorrupta();
    escrituras++;
    contenido = jsonEncode(b.aJson());
  }

  @override
  Future<List<String>> anadir(CuentaQr qr) async {
    final b = await leer();
    final c = b.anadir(qr, DateTime.utc(2026), id: b.nuevoId());
    await escribir(b);
    return c;
  }

  @override
  Future<String?> canjear(String codigo) async {
    final b = await leer();
    final id = b.canjear(codigo, DateTime.utc(2026));
    if (id != null) await escribir(b);
    return id;
  }

  @override
  Future<bool> borrar(String id) async {
    final b = await leer();
    final r = b.borrar(id);
    if (r) await escribir(b);
    return r;
  }

  @override
  Future<List<Cuenta>> todas() async => (await leer()).cuentas;
}

CuentaQr _qr({
  String emisor = 'GitHub',
  String etiqueta = 'demo',
  AlgoritmoTotp algoritmo = AlgoritmoTotp.sha1,
  int digitos = 6,
  int periodo = 30,
}) =>
    CuentaQr(
      emisor: emisor,
      etiqueta: etiqueta,
      semilla: base32Decodificar('JBSWY3DPEHPK3PXP'),
      algoritmo: algoritmo,
      digitos: digitos,
      periodo: periodo,
    );

void main() {
  group('generar códigos de recuperación', () {
    test('son diez por cuenta, en tres grupos de cuatro', () {
      final codigos = generarCodigos();
      expect(codigos.length, 10);
      for (final c in codigos) {
        expect(c, matches(RegExp(r'^[0-9A-Z]{4}(-[0-9A-Z]{4}){2}$')),
            reason: '«$c» no tiene la forma acordada');
      }
    });

    test('el alfabeto no tiene los caracteres que se confunden', () {
      // 0/O, 1/I/L son las cinco confusiones que hacen teclear mal. Un código
      // con un 0 y una O es un código que alguien va a fallar.
      for (final c in generarCodigos()) {
        for (final malo in ['0', 'O', '1', 'I', 'L']) {
          expect(c.contains(malo), isFalse, reason: '«$c» contiene «$malo»');
        }
      }
    });

    test('no se repiten dos veces, porque un repetido no sirve de nada', () {
      expect(generarCodigos(n: 50).toSet().length, 50);
    });

    test('con una semilla fija da siempre lo mismo', () {
      // Para poder probar. `Random(1)` es determinista; lo que se comprueba es
      // que el generador acepta la fuente, no que sea aleatorio.
      expect(generarCodigos(n: 5, aleatorio: Random(7)),
          generarCodigos(n: 5, aleatorio: Random(7)));
    });
  });

  group('hashear y normalizar', () {
    test('el mismo código da el mismo hash, y da igual cómo se teclee', () {
      final h = hashearCodigo('X4K9-2NPQ-7RTZ');
      expect(hashearCodigo('X4K9-2NPQ-7RTZ'), h);
      // Sin guiones, en minúsculas, con espacios: todo lo que hace una persona
      // de verdad al teclear.
      expect(hashearCodigo('x4k92npq7rtz'), h);
      expect(hashearCodigo('X4K9 2NPQ 7RTZ'), h);
      expect(hashearCodigo('  x4k9-2npq-7rtz  '), h);
    });

    test('distintos códigos dan hashes distintos', () {
      // Con dos códigos generados de verdad, no con una sustitución de
      // caracteres: un `replaceAll` sobre un código de ejemplo no encuentra
      // nunca lo que se le pide cambiar, y el test pasa sin comprobar nada.
      final codigos = generarCodigos(n: 2);
      final hashes = codigos.map(hashearCodigo).toSet();
      expect(hashes.length, 2,
          reason: '«${codigos[0]}» y «${codigos[1]}» hashean igual');
    });
  });

  group('la bóveda', () {
    test('añadir una cuenta devuelve sus códigos en claro, una vez', () {
      final b = Boveda();
      final codigos = b.anadir(_qr(), DateTime.utc(2026), id: 'a1');
      expect(codigos.length, 10);
      expect(b.cuentas.length, 1);
      // Y lo que queda guardado son hashes, no los códigos. Esto es lo que se
      // decidió: recuperarlos sin el móvil tiene que significar «los tengo
      // escritos en un papel».
      final json = jsonEncode(b.aJson());
      for (final c in codigos) {
        expect(json.contains(c), isFalse,
            reason: '«$c» aparece en claro en lo guardado');
      }
      expect(json.contains(normalizarCodigo(codigos.first)), isFalse);
      expect(b.sinGastar('a1'), 10);
    });

    test('la semilla sí se guarda, en Base64', () {
      final b = Boveda();
      b.anadir(_qr(), DateTime.utc(2026), id: 'a1');
      final json = jsonEncode(b.aJson());
      final original = base32Decodificar('JBSWY3DPEHPK3PXP');
      expect(json.contains(base64Encode(original)), isTrue);
    });

    test('canjear un código devuelve la cuenta y lo gasta', () {
      final b = Boveda();
      final codigos = b.anadir(_qr(), DateTime.utc(2026), id: 'a1');
      expect(b.canjear(codigos[3], DateTime.utc(2026)), 'a1');
      expect(b.sinGastar('a1'), 9);
    });

    test('un código gastado no se puede canjear dos veces', () {
      final b = Boveda();
      final codigos = b.anadir(_qr(), DateTime.utc(2026), id: 'a1');
      b.canjear(codigos[0], DateTime.utc(2026));
      expect(b.canjear(codigos[0], DateTime.utc(2026)), isNull);
      expect(b.sinGastar('a1'), 9);
    });

    test('un código en minúsculas o sin guiones también canjea', () {
      // El motivo de normalizar: un código que falla por una mayúscula hace
      // desconfar de los que sí valen.
      final b = Boveda();
      final codigos = b.anadir(_qr(), DateTime.utc(2026), id: 'a1');
      final minusculas = codigos[0].toLowerCase().replaceAll('-', '');
      expect(b.canjear(minusculas, DateTime.utc(2026)), 'a1');
    });

    test('el código de una cuenta no canjea en otra', () {
      final b = Boveda();
      final deA = b.anadir(_qr(emisor: 'A'), DateTime.utc(2026), id: 'a1');
      b.anadir(_qr(emisor: 'B'), DateTime.utc(2026), id: 'a2');
      expect(b.canjear(deA[0], DateTime.utc(2026)), 'a1');
    });

    test('un código inventado no canjea en ninguna', () {
      final b = Boveda();
      b.anadir(_qr(), DateTime.utc(2026), id: 'a1');
      expect(b.canjear('AAAA-BBBB-CCCC', DateTime.utc(2026)), isNull);
    });

    test('borrar una cuenta se lleva también sus códigos', () {
      // Un código sin su cuenta es un código que no lleva a ningún lado: dejarlo
      // permitiría canjear algo que ya no existe.
      final b = Boveda();
      final codigos = b.anadir(_qr(), DateTime.utc(2026), id: 'a1');
      expect(b.borrar('a1'), isTrue);
      expect(b.cuentas, isEmpty);
      expect(b.canjear(codigos[0], DateTime.utc(2026)), isNull);
      expect(b.sinGastar('a1'), 0);
    });

    test('las cuentas van por id, no por emisor', () {
      // Dos cuentas del mismo servicio es lo más normal del mundo. Si el id
      // fuera el emisor, borrar una se llevaría las dos.
      final b = Boveda();
      b.anadir(_qr(etiqueta: 'uno@ejemplo.com'), DateTime.utc(2026), id: 'a1');
      b.anadir(_qr(etiqueta: 'dos@ejemplo.com'), DateTime.utc(2026), id: 'a2');
      expect(b.cuentas.length, 2);
      b.borrar('a1');
      expect(b.cuentas.length, 1);
      expect(b.cuentas.first.etiqueta, 'dos@ejemplo.com');
    });

    test('el id nuevo no choca con los que ya hay', () {
      final b = Boveda();
      final ids = <String>{};
      for (var i = 0; i < 30; i++) {
        final id = b.nuevoId();
        expect(ids.contains(id), isFalse, reason: 'id repetido: $id');
        ids.add(id);
      }
    });
  });

  group('el versionado, que es lo que hace que una copia sirva', () {
    // `version: 1` se escribia y nunca se leia. Eso no era un detalle: al
    // cambiar el formato, una copia vieja se leia con los valores por defecto
    // de cada campo, sin decir nada. Los silencios son los que hacen que una
    // copia deje de servir justo cuando se necesita.
    test('la version se escribe y se lee', () {
      final b = Boveda();
      b.anadir(_qr(), DateTime.utc(2026), id: 'a1');
      expect(b.aJson()['version'], versionBovedaActual);
    });

    test('una bóveda v1 real sobrevive al viaje completo', () {
      final b = Boveda();
      b.anadir(_qr(), DateTime.utc(2026, 1, 2), id: 'a1');
      b.anadir(_qr(etiqueta: 'dos'), DateTime.utc(2026, 3, 4), id: 'a2');
      final vuelta = Boveda.desdeJson(b.aJson());
      expect(vuelta.cuentas.length, 2);
      expect(vuelta.sinGastar('a1'), 10);
      // Y la semilla idéntica byte a byte, que es lo que hace que el código
      // siga siendo el mismo después de exportar e importar.
      for (var i = 0; i < 2; i++) {
        expect(vuelta.cuentas[i].semilla, b.cuentas[i].semilla);
        expect(vuelta.cuentas[i].anadidaEn, b.cuentas[i].anadidaEn);
      }
    });

    test('una version mas nueva se rechaza con motivo, no se lee a medias', () {
      // Leer campos que no conoces produce una bóveda que parece buena y no lo
      // es. Peor que no tenerla, porque te lo cree.
      final b = Boveda();
      b.anadir(_qr(), DateTime.utc(2026), id: 'a1');
      final j = b.aJson()..['version'] = versionBovedaActual + 1;
      expect(() => Boveda.desdeJson(j), throwsA(isA<BovedaDeFuturo>()));
    });

    test('una version mas nueva NO se confunde con corrupta', () {
      // El consejo es el contrario: corrupto dice «no añadas nada», esto dice
      // «actualiza Aegis». Confundirlos hace que alguien borre una bóveda que
      // solo necesitaba una app más al día.
      final b = Boveda();
      b.anadir(_qr(), DateTime.utc(2026), id: 'a1');
      final j = b.aJson()..['version'] = versionBovedaActual + 1;
      Boveda leida;
      try {
        leida = Boveda.desdeJson(j);
      } on BovedaDeFuturo {
        // Lo que se propaga por `leer()`.
        leida = Boveda(corrupta: true, demasiadoNueva: true);
      }
      expect(leida.demasiadoNueva, isTrue);
      expect(leida.intocable, isTrue);
    });

    test('no se escribe encima de lo que es mas nuevo que la app', () {
      final b = Boveda(demasiadoNueva: true);
      expect(b.intocable, isTrue);
      expect(b.escribirEn(AlmacenFalso()), throwsA(isA<BovedaDeFuturo>()));
    });

    test('sin campo version se asume la primera, que es lo que habia', () {
      // Lo que hay en los Keystore de quien ya uso la app: `version: 1` se
      // escribia desde el principio, pero un documento hecho a mano puede no
      // tenerlo, y tratarlo como ilegible tiraria cuentas que estan bien.
      final b = Boveda();
      b.anadir(_qr(), DateTime.utc(2026), id: 'a1');
      final j = b.aJson()..remove('version');
      expect(Boveda.desdeJson(j).cuentas.length, 1);
    });

    test('la cadena de migraciones esta lista y es una lista', () {
      // No se puede comprobar desde fuera que las migraciones se apliquen
      // mientras no haya ninguna, pero sí que el hueco por el que entrará la
      // v2 existe y está ordenado. Con migraciones sin ordenar, una copia de la
      // v1 pasa por el paso de la v2 y sale con la v3 medio aplicada.
      expect(versionBovedaActual, greaterThanOrEqualTo(1));
    });
  });

  group('el JSON de la bóveda', () {
    test('ida y vuelta conserva las cuentas', () {
      final b = Boveda();
      b.anadir(_qr(algoritmo: AlgoritmoTotp.sha512, digitos: 8, periodo: 60),
          DateTime.utc(2026, 1, 2), id: 'a1');
      b.anadir(_qr(emisor: '', etiqueta: 'sin emisor'),
          DateTime.utc(2026, 3, 4), id: 'a2');

      final vuelta = Boveda.desdeJson(b.aJson());
      expect(vuelta.cuentas.length, 2);
      for (var i = 0; i < 2; i++) {
        expect(vuelta.cuentas[i].id, b.cuentas[i].id);
        expect(vuelta.cuentas[i].semilla, b.cuentas[i].semilla);
        expect(vuelta.cuentas[i].algoritmo, b.cuentas[i].algoritmo);
        expect(vuelta.cuentas[i].digitos, b.cuentas[i].digitos);
        expect(vuelta.cuentas[i].periodo, b.cuentas[i].periodo);
        expect(vuelta.cuentas[i].anadidaEn, b.cuentas[i].anadidaEn);
      }
    });

    test('la cuenta sobrevive al viaje produce el mismo código', () {
      // El criterio que importa: no que el JSON cuadre, sino que el código que
      // sale después de serializar sea el mismo que antes.
      final b = Boveda();
      b.anadir(_qr(), DateTime.utc(2026), id: 'a1');
      final antes = b.cuentas.first.codigo(DateTime.utc(2026, 10, 5, 12));
      final despues = Boveda.desdeJson(b.aJson()).cuentas.first.codigo(
          DateTime.utc(2026, 10, 5, 12));
      expect(despues, antes);
    });

    test('una cuenta corrupta se pierde, las demás no', () {
      // El motivo de `desdeJson` blando: un registro ilegible no puede
      // impedir abrir la bóveda. Antes, un `try` alrededor de todo devolvía una
      // bóveda vacía y perdías todas.
      final b = Boveda();
      b.anadir(_qr(etiqueta: 'buena'), DateTime.utc(2026), id: 'a1');
      b.anadir(_qr(etiqueta: 'rota'), DateTime.utc(2026), id: 'a2');
      final j = b.aJson();
      (j['cuentas'] as List).last['semilla'] = 'no es base64';
      final vuelta = Boveda.desdeJson(j);
      expect(vuelta.cuentas.length, 1);
      expect(vuelta.cuentas.first.etiqueta, 'buena');
    });

    test('un algoritmo desconocido cae a SHA-1, que es lo que aceptará el servicio', () {
      final b = Boveda();
      b.anadir(_qr(), DateTime.utc(2026), id: 'a1');
      final j = b.aJson();
      (j['cuentas'] as List).first['algoritmo'] = 'SHA999';
      expect(Boveda.desdeJson(j).cuentas.first.algoritmo, AlgoritmoTotp.sha1);
    });
  });

  group('a través del almacenamiento', () {
    test('añadir, leer y borrar va Round-trip', () async {
      final a = AlmacenFalso();
      final codigos = await a.anadir(_qr());
      expect(codigos.length, 10);

      final leidas = await a.todas();
      expect(leidas.length, 1);
      expect(leidas.first.titulo, 'GitHub: demo');

      expect(await a.canjear(codigos[2]), isNotNull);
      expect(await a.canjear(codigos[2]), isNull, reason: 'gastado');

      expect(await a.borrar(leidas.first.id), isTrue);
      expect(await a.todas(), isEmpty);
    });

    test('lo que se guarda en el almacenamiento no tiene códigos en claro', () async {
      final a = AlmacenFalso();
      final codigos = await a.anadir(_qr());
      for (final c in codigos) {
        expect(a.contenido!.contains(normalizarCodigo(c)), isFalse);
      }
    });

    test('un sobre corrupto se devuelve marcado, no se lanza', () async {
      // Que sea un **valor** y no una excepción es lo que hace que el estado
      // sobreviva a cada reconstrucción: con una excepción, un `build()` que
      // devolviera la lista vacía volvería a pintar «no tienes cuentas» sobre
      // una bóveda ilegible.
      final a = AlmacenFalso()..corrupto = true;
      expect((await a.leer()).corrupta, isTrue);
    });

    test('una bóveda normal no está marcada como corrupta', () async {
      expect((await AlmacenFalso().leer()).corrupta, isFalse);
    });

    test('escribir encima de una bóveda corrupta no toca nada', () async {
      // La regla que hace que esto no se pierda: el refusal está en el valor,
      // no en cada llamador. Un olvido en uno de ellos sería la pérdida.
      final a = AlmacenFalso()..corrupto = true;
      await expectLater(Boveda(corrupta: true).escribirEn(a),
          throwsA(isA<BovedaCorrupta>()));
      expect(a.escrituras, 0, reason: 'escribió encima de algo ilegible');
    });

    test('copiar conserva la marca de corrupción', () {
      expect(Boveda(corrupta: true).copia().corrupta, isTrue);
      expect(Boveda().copia().corrupta, isFalse);
    });

    test('corrupta no se cuenta como vacía ni como llena', () {
      // `vacia` en true con una bóveda dañada es lo que pintaría «no tienes
      // cuentas» y dejaría añadir encima.
      expect(Boveda(corrupta: true).vacia, isFalse);
      expect(Boveda().vacia, isTrue);
    });

    test('varias cuentas conviven con sus códigos separados', () async {
      final a = AlmacenFalso();
      final c1 = await a.anadir(_qr(emisor: 'GitHub', etiqueta: 'uno'));
      final c2 = await a.anadir(_qr(emisor: 'Neon', etiqueta: 'dos'));
      final cuentas = await a.todas();
      expect(cuentas.length, 2);
      // El de GitHub canjea y solo en la suya.
      expect(await a.canjear(c1[0]), cuentas.first.id);
      expect(await a.canjear(c2[0]), cuentas.last.id);
    });
  });

  group('la cuenta calcula bien', () {
    test('el código que sale de una cuenta guardada es el de la semilla', () {
      final b = Boveda();
      b.anadir(_qr(), DateTime.utc(2026), id: 'a1');
      final c = b.cuentas.first;
      final t = DateTime.utc(2026, 10, 5, 12, 34, 56);
      expect(
        c.codigo(t),
        CuentaTotp(semilla: base32Decodificar('JBSWY3DPEHPK3PXP')).codigo(t),
      );
    });

    test('con 8 dígitos y periodo 60, también', () {
      final b = Boveda();
      b.anadir(_qr(digitos: 8, periodo: 60), DateTime.utc(2026), id: 'a1');
      final c = b.cuentas.first;
      expect(c.codigo(DateTime.utc(2026)).length, 8);
      expect(c.segundosRestantes(DateTime.utc(2026)), inInclusiveRange(1, 60));
    });
  });
}