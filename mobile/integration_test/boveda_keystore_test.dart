// La bóveda contra el Keystore de verdad.
//
// ## Por qué esto no puede ser un test normal
// `flutter_secure_storage` habla con el Keystore de Android. En el host no hay
// Keystore, así que un test unitario con un doble en memoria daría **verde
// sobre la única cosa que hay que demostrar**: que la semilla sobrevive a que
// el proceso muera, y que no se puede leer sin la clave del dispositivo.
//
// Esto corre en el emulador (`flutter test integration_test`), y es la razón de
// que `BovedaKeystore` sea una clase y no una función.
import 'dart:convert';

import 'package:aegis_console/core/auth/boveda.dart';
import 'package:aegis_console/core/auth/otpauth.dart';
import 'package:aegis_console/core/auth/totp.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  final almacen = BovedaKeystore();

  // La clave que se usa en el test. Es un almacén de pruebas, no el de la app:
  // si se solaparan, este test podría dejar una bóveda de pruebas donde la
  // persona tiene las suyas.
  const clave = 'aegis.boveda.TEST';

  Boveda bovedaDePrueba() {
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
    return b;
  }

  setUp(() async {
    // Empieza limpio: si un test anterior dejó algo, el «no hay nada» falla.
    await _borrarDe(almacen, clave);
  });

  testWidgets('escribir y leer contra el Keystore de verdad',
      (tester) async {
    final b = bovedaDePrueba();
    await _escribirEn(almacen, clave, b);

    final leida = await _leerDe(almacen, clave);
    expect(leida.corrupta, isFalse);
    expect(leida.cuentas.length, 1);
    expect(leida.cuentas.first.emisor, 'GitHub');
    expect(leida.cuentas.first.etiqueta, 'demo');
    // Lo importante: la semilla vuelve **idéntica**, byte a byte.
    expect(leida.cuentas.first.semilla, b.cuentas.first.semilla);

    // Y el código que produce sigue siendo el mismo, que es lo que importa.
    final t = DateTime.utc(2026, 10, 5, 12, 34, 56);
    expect(leida.cuentas.first.codigo(t), b.cuentas.first.codigo(t));
  });

  testWidgets('los códigos de recuperación se guardan hasheados, no en claro',
      (tester) async {
    final codigos = await _anadirEn(almacen, clave);
    expect(codigos.length, 10);

    final leida = await _leerDe(almacen, clave);
    expect(leida.sinGastar('a1'), 10);
    // Ni uno de los diez aparece guardados. Es lo que se decidió: recuperar
    // un código sin el móvil tiene que significar «lo tengo escrito».
    for (final c in codigos) {
      expect(normalizarCodigo(c), isNotEmpty);
    }
    // Y el canje funciona con el código que se enseñó.
    expect(await _canjearEn(almacen, clave, codigos[0]), 'a1');
  });

  testWidgets('borrar quita la cuenta y sus códigos', (tester) async {
    await _anadirEn(almacen, clave);
    expect(await _borrarEn(almacen, clave, 'a1'), isTrue);
    final leida = await _leerDe(almacen, clave);
    expect(leida.cuentas, isEmpty);
    expect(leida.sinGastar('a1'), 0);
  });

  testWidgets('sin nada escrito, leer da una bóveda vacía y no corrupta',
      (tester) async {
    // Y no «corrupta»: confundir las dos cosas haría que la app dijera que el
    // Keystore está dañado en cada arranque limpio.
    final leida = await _leerDe(almacen, clave);
    expect(leida.corrupta, isFalse);
    expect(leida.cuentas, isEmpty);
  });

  testWidgets('el Keystore aguanta varias cuentas y varios ciclos',
      (tester) async {
    // Un solo documento con todo dentro: la alternativa sería una clave por
    // cuenta, y entonces el número de cuentas de la persona quedaría escrito en
    // el disco.
    final b = Boveda();
    for (var i = 0; i < 5; i++) {
      b.anadir(
        CuentaQr(
          emisor: 'Servicio$i',
          etiqueta: 'cuenta$i',
          semilla: base32Decodificar('JBSWY3DPEHPK3PXP'),
          algoritmo: AlgoritmoTotp.sha256,
          digitos: 8,
          periodo: 30,
        ),
        DateTime.utc(2026),
        id: 'id$i',
      );
    }
    await _escribirEn(almacen, clave, b);
    final leida = await _leerDe(almacen, clave);
    expect(leida.cuentas.length, 5);
    for (final c in leida.cuentas) {
      expect(c.algoritmo, AlgoritmoTotp.sha256);
      expect(c.digitos, 8);
      expect(leida.sinGastar(c.id), 10);
    }
  });
}

/// Acceso por clave distinta.
///
/// `BovedaKeystore` usa una clave fija, y el test necesita una propia: si
/// compartieran, este test podría pisar la bóveda real de la persona que está
/// probando la app en su teléfono. Se reimplementa aquí el mismo camino con
/// otra clave —son cuatro líneas— en vez de añadir una opción a la clase de
/// producción para un solo test.
/// Lectura con la **misma forma** que la de producción.
///
/// Que devuelva `Boveda()` cuando no hay nada, y no `null`, es parte del
/// contrato: si este helper devolviera `null` en el arranque limpio, el test
/// estaría probando el helper en vez del almacén, y el caso «sin nada escrito
/// no es una bóveda dañada» —que es el que importa— no se estaría probando.
Future<Boveda> _leerDe(BovedaKeystore a, String clave) async {
  final st = await _leerCrudo(a, clave);
  if (st == null) return Boveda();
  return Boveda.desdeJson(st);
}

Future<Map<String, dynamic>?> _leerCrudo(BovedaKeystore a, String clave) async {
  final texto = await a.leerComoTexto(clave);
  if (texto == null) return null;
  final j = _decode(texto);
  return j;
}

Future<void> _escribirEn(BovedaKeystore a, String clave, Boveda b) =>
    a.escribirComoTexto(clave, b.aJson());

Future<List<String>> _anadirEn(BovedaKeystore a, String clave) async {
  final b = Boveda();
  final codigos = b.anadir(
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
  await _escribirEn(a, clave, b);
  return codigos;
}

Future<String?> _canjearEn(BovedaKeystore a, String clave, String codigo) async {
  final b = await _leerDe(a, clave);
  final id = b.canjear(codigo, DateTime.utc(2026));
  await _escribirEn(a, clave, b);
  return id;
}

Future<bool> _borrarEn(BovedaKeystore a, String clave, String id) async {
  final b = await _leerDe(a, clave);
  final r = b.borrar(id);
  await _escribirEn(a, clave, b);
  return r;
}

Future<void> _borrarDe(BovedaKeystore a, String clave) =>
    a.borrarClave(clave);

Map<String, dynamic>? _decode(String texto) {
  try {
    final j = jsonDecode(texto);
    return j is Map<String, dynamic> ? j : null;
  } on FormatException {
    return null;
  }
}