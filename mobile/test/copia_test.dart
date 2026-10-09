// La copia cifrada.
//
// ## Por qué estos tests existen y no son un lujo
// Una copia de seguridad que se puede abrir con la contraseña equivocada, o que
// devuelve una bóveda vacía en vez de un error, son los dos fallos que hacen
// que alguien **no tenga copia** sin enterarse de que no la tiene. Un backup
// que parece funcionar y no sirve es peor que no tener backup.
import 'dart:convert';
import 'dart:io';

import 'package:aegis_console/core/auth/boveda.dart';
import 'package:aegis_console/core/auth/copia.dart';
import 'package:aegis_console/core/auth/otpauth.dart';
import 'package:aegis_console/core/auth/totp.dart';
import 'package:flutter_test/flutter_test.dart';

Boveda _boveda() {
  final b = Boveda();
  b.anadir(
    CuentaQr(
      emisor: 'GitHub',
      etiqueta: 'demo',
      semilla: base32Decodificar('JBSWY3DPEHPK3PXP'),
      algoritmo: AlgoritmoTotp.sha1,
      digitos: 6,
      periodo: 30,
    ),
    DateTime.utc(2026, 1, 2),
    id: 'a1',
  );
  b.anadir(
    CuentaQr(
      emisor: 'Banco',
      etiqueta: 'ana@ejemplo.com',
      semilla: base32Decodificar('MFRGGZDFMZTWQ2LKNNWG23TPOA'),
      algoritmo: AlgoritmoTotp.sha512,
      digitos: 8,
      periodo: 60,
    ),
    DateTime.utc(2026, 3, 4),
    id: 'a2',
  );
  return b;
}

void main() {
  // Argon2id con 64 MB cuesta ~200 ms por operación. Con cuatro o cinco
  // pruebas son ~1 s. Con veinte, el test se hace lento y la gente empieza a
  // saltárselo — y un test que se salta no vigila nada. Por eso las pruebas
  //.round-trip. se sharean en `setUpAll` y las demás no vuelven a derivar.
  late String sobre;
  late Boveda original;

  setUpAll(() async {
    original = _boveda();
    sobre = await cifrarBoveda(original, 'la contraseña correcta');
  });

  group('cifrar y abrir', () {
    test('la bóveda vuelve igual', () async {
      final vuelta = await abrirCopia(sobre, 'la contraseña correcta');
      expect(vuelta.cuentas.length, 2);
      for (var i = 0; i < 2; i++) {
        expect(vuelta.cuentas[i].id, original.cuentas[i].id);
        expect(vuelta.cuentas[i].semilla, original.cuentas[i].semilla);
        expect(vuelta.cuentas[i].algoritmo, original.cuentas[i].algoritmo);
        expect(vuelta.cuentas[i].digitos, original.cuentas[i].digitos);
        expect(vuelta.cuentas[i].periodo, original.cuentas[i].periodo);
      }
    });

    test('y produce los mismos códigos, que es lo que importa', () async {
      final vuelta = await abrirCopia(sobre, 'la contraseña correcta');
      final t = DateTime.utc(2026, 10, 5, 12, 34, 56);
      for (var i = 0; i < 2; i++) {
        expect(vuelta.cuentas[i].codigo(t), original.cuentas[i].codigo(t));
      }
    });

    test('los códigos de recuperación siguen ahí, hasheados', () async {
      final vuelta = await abrirCopia(sobre, 'la contraseña correcta');
      expect(vuelta.sinGastar('a1'), 10);
      expect(vuelta.sinGastar('a2'), 10);
    });
  });

  group('el fichero no enseña nada', () {
    test('no contiene ninguna semilla en claro', () {
      // Si esto falla, alguien ha metido la cuenta en el sobre sin cifrar.
      for (final c in original.cuentas) {
        expect(sobre.contains(base64Encode(c.semilla)), isFalse,
            reason: 'la semilla de ${c.titulo} aparece en claro');
        expect(sobre.contains(c.etiqueta), isFalse);
        expect(sobre.contains(c.emisor), isFalse);
      }
    });

    test('no contiene los códigos de recuperación en claro', () async {
      // Ni siquiera hasheados en la forma que se pueden canjear: van dentro
      // del texto cifrado.
      final vuelta = await abrirCopia(sobre, 'la contraseña correcta');
      for (final cod in vuelta.recuperacionDe('a1')) {
        expect(sobre.contains(cod.hash), isFalse,
            reason: 'el hash de un código de recuperación se lee en el fichero');
      }
    });

    test('el sobre declara su versión y su KDF, y no la contraseña', () {
      final j = jsonDecode(sobre) as Map<String, dynamic>;
      expect(j['version'], 1);
      expect(j['kdf'], 'argon2id');
      expect(j['sal'], isNotEmpty);
      expect(j['nonce'], isNotEmpty);
      expect(sobre.contains('la contraseña correcta'), isFalse);
    });

    test('dos cifrados de lo mismo son distintos, porque la sal cambia', () async {
      // Si fueran iguales, dos copias con la misma contraseña darían la misma
      // clave, y la sal dejaría de estar haciendo su trabajo.
      final otro = await cifrarBoveda(original, 'la contraseña correcta');
      expect(otro, isNot(sobre));
      final a = jsonDecode(sobre) as Map<String, dynamic>;
      final b = jsonDecode(otro) as Map<String, dynamic>;
      expect(a['sal'], isNot(b['sal']));
      // Pero las dos abren igual.
      expect((await abrirCopia(otro, 'la contraseña correcta')).cuentas.length,
          2);
    });
  });

  group('la contraseña incorrecta', () {
    test('falla, y se dice que es la contraseña', () async {
      // Distinguir «contraseña» de «fichero dañado» es lo que evita que alguien
      // con la contraseña buena repita contra un fichero roto y acabe creyendo
      // que la contraseña es otra.
      try {
        await abrirCopia(sobre, 'no es la buena');
        fail('debería haber fallado');
      } on ErrorCopia catch (e) {
        expect(e.contrasenaIncorrecta, isTrue);
        expect(e.motivo, contains('contraseña'));
      }
    });

    test('no devuelve una bóveda vacía, que sería el fallo grave', () async {
      // Devolver vacío en vez de fallar es lo que hace que un backup roto
      // parezca un backup vacío. Este test falla si alguien cambia eso.
      Object? error;
      try {
        await abrirCopia(sobre, 'incorrecta');
      } catch (e) {
        error = e;
      }
      expect(error, isNotNull);
      expect(error, isNot(isA<Boveda>()));
    });

    test('una contraseña vacía también falla', () async {
      expect(() => abrirCopia(sobre, ''), throwsA(isA<ErrorCopia>()));
    });
  });

  group('lo que no es una copia', () {
    void fallaCon(String contenido, {bool porContrasena = false}) async {
      try {
        await abrirCopia(contenido, 'la contraseña correcta');
        fail('«$contenido» debería haber fallado');
      } on ErrorCopia catch (e) {
        expect(e.contrasenaIncorrecta, porContrasena,
            reason: 'con «$contenido»');
      }
    }

    test('texto que no es JSON', () => fallaCon('esto no es json'));
    test('JSON que no es un objeto', () => fallaCon('[1,2,3]'));
    test('un objeto vacío', () => fallaCon('{}'));
    test('sin campos', () => fallaCon('{"foo":"bar"}'));

    test('una versión que esta app no entiende', () async {
      // Una copia de un futuro es un caso real: la app se actualizó y la copia
      // es de una build más nueva. Decirlo es mejor que «contraseña
      // incorrecta», porque aquí no hay contraseña que cambiar.
      final j = jsonDecode(sobre) as Map<String, dynamic>;
      j['version'] = 99;
      Object? error;
      try {
        await abrirCopia(jsonEncode(j), 'la contraseña correcta');
      } catch (e) {
        error = e;
      }
      expect(error, isA<ErrorCopia>());
      expect((error! as ErrorCopia).motivo, contains('99'));
    });

    test('un KDF desconocido', () async {
      final j = jsonDecode(sobre) as Map<String, dynamic>;
      j['kdf'] = 'scrypt';
      Object? error;
      try {
        await abrirCopia(jsonEncode(j), 'la contraseña correcta');
      } catch (e) {
        error = e;
      }
      expect((error! as ErrorCopia).motivo, contains('scrypt'));
    });

    test('una copia manipiada', () async {
      // Alguien que cambia un byte del cifrado. El GCM tiene que detectinglo.
      final j = jsonDecode(sobre) as Map<String, dynamic>;
      final cifrado = j['cifrado'] as String;
      // Cambia el primer carácter del base64. Sigue siendo base64 válido.
      final cambiado =
          (cifrado[0] == 'A' ? 'B' : 'A') + cifrado.substring(1);
      j['cifrado'] = cambiado;
      Object? error;
      try {
        await abrirCopia(jsonEncode(j), 'la contraseña correcta');
      } catch (e) {
        error = e;
      }
      expect(error, isA<ErrorCopia>());
    });

    test('el motivo es texto enseñable, sin jargon', () async {
      for (final malo in ['nada', '{}', '[1]', 'null']) {
        try {
          await abrirCopia(malo, 'x');
          fail('«$malo» debería haber fallado');
        } on ErrorCopia catch (e) {
          expect(e.motivo, isNotEmpty);
          expect(e.motivo, isNot(contains('Exception')));
          expect(e.motivo, isNot(contains('FormatException')));
          expect(e.motivo, isNot(contains('null')));
        }
      }
    });
  });

  group('el fichero de verdad', () {
    // Un test que solo trabaja con strings en memoria no comprueba que lo que
    // se escribe a disco se puede volver a leer. Se escribe y se lee de verdad.
    late Directory temp;

    setUp(() async => temp = await Directory.systemTemp.createTemp('aegis_copia'));
    tearDown(() async {
      if (temp.existsSync()) await temp.delete(recursive: true);
    });

    test('lo que se escribe en disco se vuelve a abrir', () async {
      final ruta = '${temp.path}/aegis-copia.json';
      final b = _boveda();
      await File(ruta).writeAsString(await cifrarBoveda(b, 'la contraseña correcta'));
      final leido = await File(ruta).readAsString();
      final vuelta = await abrirCopia(leido, 'la contraseña correcta');
      expect(vuelta.cuentas.length, 2);
      expect(vuelta.cuentas.first.titulo, 'GitHub: demo');
    });

    test('un fichero vacío o que no existe se dice, no se traga', () async {
      expect(() => abrirCopia('', 'x'), throwsA(isA<ErrorCopia>()));
      expect(() => abrirCopia('   ', 'x'), throwsA(isA<ErrorCopia>()));
    });
  });

  group('el coste', () {
    test('derivar la clave tarda lo suficiente', () async {
      // No es un test de rendimiento flaky: comprueba que Argon2id está
      // realmente configurado con memoria. Con 64 MB cuesta cientos de ms; si
      // alguien baja la memoria para que el test vaya más rápido, esto salta.
      final inicio = DateTime.now();
      await cifrarBoveda(_boveda(), 'contraseña');
      final ms = DateTime.now().difference(inicio).inMilliseconds;
      expect(ms, greaterThan(50),
          reason: 'derivó en ${ms}ms: la KDF no está costando lo que debe');
    });
  });
}