// El ciclo de la copia: lo que sale del móvil tiene que poder volver a entrar.
//
// ## Por qué esto no es «un test más»
// Porque es el único camino por el que las semillas sobreviven a perder el
// móvil. Si el ciclo no cierra, Aegis no es una red de seguridad: es una lista
// bonita que se lleva el dispositivo. Y como el destino lo elige una persona y
// el diálogo es del sistema, **esto no se puede probar automáticamente de
// punta a punta** — por eso el simulacro de la Fase 2 lo hace una persona, y
// aquí se prueba todo lo que sí es automático.
//
// Los tres que importan, y que este fichero cubre:
//   1. El nombre propuesto **no pisa** la copia anterior.
//   2. Lo que sale del canal se puede volver a abrir con la contraseña.
//   3. Una copia manipulada se rechaza, no se lee a medias.
import 'dart:convert';

import 'package:aegis_console/core/auth/boveda.dart';
import 'package:aegis_console/core/auth/copia.dart';
import 'package:aegis_console/core/auth/copia_nativa.dart';
import 'package:aegis_console/core/auth/fichero_copia.dart';
import 'package:aegis_console/core/auth/otpauth.dart';
import 'package:aegis_console/core/auth/totp.dart';
import 'package:flutter_test/flutter_test.dart';

/// El canal de mentira: guarda lo que le pasan y devuelve lo que le dieron.
class CopiaFalsa implements CopiaNativa {
  String? contenido;
  String? motivoAlExportar;
  String? motivoAlImportar;
  String nombrePropuesto = '';
  bool cancelar = false;

  @override
  Future<String?> exportar(String texto, String nombre) async {
    nombrePropuesto = nombre;
    if (cancelar) return null;
    if (motivoAlExportar != null) return motivoAlExportar;
    contenido = texto;
    return null;
  }

  @override
  Future<String?> importar() async => cancelar ? null : contenido;
}

Boveda _bovedaConUnaCuenta() {
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

void main() {
  group('el nombre propuesto', () {
    // Exportar dos veces sin querer **pisa** la copia anterior, y una copia que
    // se sobrescribe sin preguntar no era una copia.
    test('lleva fecha y hora, y por eso dos exportaciones no chocan', () {
      final a = nombreCopiaConFecha(DateTime.utc(2026, 10, 9, 20, 5));
      final b = nombreCopiaConFecha(DateTime.utc(2026, 10, 9, 20, 6));
      expect(a, isNot(b));
      expect(a, endsWith('.json'));
      expect(a, contains('20261009'));
      expect(a, contains('2005'));
    });

    test('el mismo minuto da el mismo nombre, que es lo correcto', () {
      final t = DateTime.utc(2026, 10, 9, 20, 5);
      expect(nombreCopiaConFecha(t), nombreCopiaConFecha(t));
    });

    test('el nombre local NO lleva fecha: solo hay una y se regenera', () {
      // Si el local llevara fecha, cada exportación crearía un fichero y la
      // copia automática —la que salva en este móvil— se acumularía sin que
      // nadie sepa cuál es la buena.
      expect(nombreCopia, 'aegis-claves.json');
      expect(nombreCopia.contains('2026'), isFalse);
    });

    test('mes y día van con cero delante, para que ordene bien', () {
      // Sin el cero, «202699» ordena antes que «202610» y el fichero más
      // reciente acaba siendo el más antiguo.
      final nombre = nombreCopiaConFecha(DateTime.utc(2026, 1, 2, 3, 4));
      expect(nombre, contains('20260102'));
      expect(nombre, contains('0304'));
    });
  });

  group('el ciclo completo: sale y vuelve', () {
    test('lo que sale del canal se puede volver a abrir', () async {
      final b = _bovedaConUnaCuenta();
      final sobre = await cifrarBoveda(b, 'la contraseña');

      final canal = CopiaFalsa();
      final motivo = await canal.exportar(sobre, nombreCopiaConFecha());
      expect(motivo, isNull, reason: 'guardar bien no es un motivo de error');

      // Y lo que vuelve por el otro lado del canal…
      final vuelto = await canal.importar();
      expect(vuelto, sobre);

      // …se abre con la misma contraseña y conserva la semilla.
      final recuperada = await abrirCopia(vuelto!, 'la contraseña');
      expect(recuperada.cuentas.length, 1);
      expect(recuperada.cuentas.first.semilla, b.cuentas.first.semilla);
      expect(recuperada.sinGastar('a1'), 10);
    });

    test('el código que sale después del viaje es el mismo', () async {
      // El criterio que de verdad importa: no que el JSON cuadre, sino que la
      // cuenta siga dando el mismo código. Los vectores de la RFC garantizan la
      // fórmula; esto garantiza que el viaje no la toca.
      final b = _bovedaConUnaCuenta();
      final canal = CopiaFalsa();
      await canal.exportar(await cifrarBoveda(b, 'la contraseña'), 'x.json');
      final recuperada =
          await abrirCopia((await canal.importar())!, 'la contraseña');
      final t = DateTime.utc(2026, 10, 9, 20, 5, 30);
      expect(recuperada.cuentas.first.codigo(t), b.cuentas.first.codigo(t));
    });

    test('cancelar no es fallar', () async {
      // Cancelar es una decisión. Si devolviera un motivo de error, alguien que
      // cambió de opinión vería un mensaje que dice que algo se rompió.
      final canal = CopiaFalsa()..cancelar = true;
      expect(await canal.exportar('lo que sea', 'x.json'), isNull);
      expect(await canal.importar(), isNull);
    });

    test('un destino que falla dice por qué', () async {
      final canal = CopiaFalsa()..motivoAlExportar = 'el destino no se pudo abrir';
      expect(await canal.exportar('x', 'x.json'), 'el destino no se pudo abrir');
    });
  });

  group('el sobre que sale, en la mano de otra persona', () {
    test('no lleva nada legible dentro', () async {
      final b = _bovedaConUnaCuenta();
      final sobre = await cifrarBoveda(b, 'la contraseña');
      for (final prohibido in [
        'GitHub', 'demo', base64Encode(b.cuentas.first.semilla), 'periodo',
        'semilla', 'ejemplo',
      ]) {
        expect(sobre.contains(prohibido), isFalse,
            reason: '«$prohibido» se lee en el fichero');
      }
    });

    test('sin la contraseña no se abre, y se dice que es la contraseña', () async {
      final sobre = await cifrarBoveda(_bovedaConUnaCuenta(), 'la buena');
      try {
        await abrirCopia(sobre, 'la mala');
        fail('debería haber fallado');
      } on ErrorCopia catch (e) {
        expect(e.contrasenaIncorrecta, isTrue,
            reason: 'es un problema de contraseña, no de fichero: decirlo '
                'distinto hace que nadie repita la buena contra algo roto');
      }
    });

    test('una copia manipulada se rechaza', () async {
      final sobre = await cifrarBoveda(_bovedaConUnaCuenta(), 'la buena');
      final j = jsonDecode(sobre) as Map<String, dynamic>;
      final cifrado = j['cifrado'] as String;
      j['cifrado'] = (cifrado[0] == 'A' ? 'B' : 'A') + cifrado.substring(1);
      expect(() => abrirCopia(jsonEncode(j), 'la buena'),
          throwsA(isA<ErrorCopia>()),
          reason: 'si un byte cambia y se lee igual, el cifrado no cifra nada');
    });

    test('una copia de una versión futura no se lee a medias', () async {
      // La copia guardada con una app más nueva que esta. Leyendo lo que se
      // conoce se produciría una bóveda que parece buena y no lo es.
      final sobre = await cifrarBoveda(_bovedaConUnaCuenta(), 'la buena');
      final j = jsonDecode(sobre) as Map<String, dynamic>..['version'] = 99;
      expect(() => abrirCopia(jsonEncode(j), 'la buena'),
          throwsA(isA<ErrorCopia>()));
    });
  });
}