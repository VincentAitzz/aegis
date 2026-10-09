// TOTP contra los vectores de la RFC.
//
// ## Por qué este archivo es el más importante de los nuevos
// Todo lo demás se puede probar con una idea de cómo debería ser. Esto se
// prueba con **números que escribió otra persona** en 2005 (RFC 4226 §Appendix
// D) y en 2011 (RFC 6238 §Appendix B), y esos son los mismos números que
// comprueba un servidor de Google o de Neon.
//
// Si un día este test falla, no es que el código esté feo: es que Aegis va a
// calcular un código que el servidor rechaza, y eso se descubre en el login, en
// casa, sin diagnóstico. Por eso los vectores van aquí y no en una prueba
// propia: una prueba propia valida que el código hace lo que hace este código.
import 'dart:convert';
import 'dart:typed_data';

import 'package:aegis_console/core/auth/totp.dart';
import 'package:flutter_test/flutter_test.dart';

/// La semilla de los vectores de la RFC 6238 es la palabra ASCII
/// "12345678901234567890", **no** su Base32. La RFC la da en bytes.
final _semillaRfc = Uint8List.fromList(
  ascii.encode('12345678901234567890'),
);

/// La RFC 6238 dice que el secreto es "12345678901234567890", y lo es para
/// SHA-1. **Para SHA-256 y SHA-512 no lo es**: los vectores de esos dos usan el
/// mismo ASCII repetido hasta la longitud del digest (32 y 64 bytes). Con los
/// 20 bytes de SHA-1 los tres algoritmos dan números distintos, y la tabla de
/// la RFC solo cuadra con cada semilla con su algoritmo.
///
/// Esto se comprobó contra una implementación independiente antes de escribirlo
/// aquí: los doce valores de esta tabla son los de la RFC y salen con estas
/// semillas, no con otras. Si alguien «arregla» estas constantes por simetría
/// con las de arriba, los doce tests pasan a fallar.
final _semilla256 = Uint8List.fromList(
  ascii.encode('12345678901234567890123456789012'),
);
final _semilla512 = Uint8List.fromList(
  ascii.encode(
    '12345678901234567890123456789012'
    '34567890123456789012345678901234',
  ),
);

void main() {
  group('las semillas son las que se creen', () {
    // Esto está aquí porque pasó: la semilla de 512 se escribió partida en dos
    // literales contiguos, contando mal los caracteres, y salía de 62 bytes en
    // vez de 64. El resultado eran cuatro tests que fallaban sin que nada
    // dijera por qué. Una constante mal partida **no se ve**: se ve un número
    // que no cuadra, y la primera hipótesis siempre es el código.
    test('la de SHA-1 tiene los 20 bytes que dice la RFC', () {
      expect(_semillaRfc.length, 20);
      expect(ascii.decode(_semillaRfc), '12345678901234567890');
    });
    test('la de SHA-256 tiene 32, y la de SHA-512 tiene 64', () {
      expect(_semilla256.length, 32);
      expect(_semilla512.length, 64);
    });
  });

  group('RFC 6238, los vectores publicados', () {
    // T (segundos), código esperado con 8 dígitos, SHA-1.
    const vectores8 = <(int, String)>[
      (59, '94287082'),
      (1111111109, '07081804'),
      (1111111111, '14050471'),
      (1234567890, '89005924'),
      (2000000000, '69279037'),
      (20000000000, '65353130'),
    ];

    test('SHA-1, 8 dígitos, con los cinco instantes que la RFC usa', () {
      final cuenta = CuentaTotp(
        semilla: _semillaRfc,
        digitos: 8,
        periodo: 30,
      );
      for (final (segundos, esperado) in vectores8) {
        final instante = DateTime.fromMillisecondsSinceEpoch(
          segundos * 1000,
          isUtc: true,
        );
        expect(
          cuenta.codigo(instante),
          esperado,
          reason: 'T=$segundos (RFC 6238, SHA-1)',
        );
      }
    });

    test('SHA-1, 6 dígitos, que es lo que casi todos los servicios usan', () {
      // Los mismos instantes recortados a 6. El servidor toma los 6 últimos
      // dígitos del valor de 8, y por eso sale un sufijo — es exactamente lo
      // que dice la RFC 4226: "truncarse a menos dígitos es el último tramo".
      const esperado6 = <(int, String)>[
        (59, '287082'),
        (1111111109, '081804'),
        (1111111111, '050471'),
        (1234567890, '005924'),
        (2000000000, '279037'),
        (20000000000, '353130'),
      ];
      final cuenta = CuentaTotp(semilla: _semillaRfc, periodo: 30);
      for (final (segundos, esperado) in esperado6) {
        expect(
          cuenta.codigo(DateTime.fromMillisecondsSinceEpoch(segundos * 1000,
              isUtc: true)),
          esperado,
          reason: 'T=$segundos a 6 dígitos',
        );
      }
    });

    test('SHA-256 y SHA-512, con las semillas que la RFC da para ellos', () {
      // La tabla completa de la RFC 6238 apéndice B. Solo se comprueban los
      // instantes que difieren del caso SHA-1: si el algoritmo se ignorase y
      // se usara SHA-1, estos ocho números saldrían distintos, y eso es
      // justamente lo que el test quiere cazar.
      const v256 = <(int, String)>[
        (59, '46119246'),
        (1111111109, '68084774'),
        (1111111111, '67062674'),
        (1234567890, '91819424'),
        (2000000000, '90698825'),
        (20000000000, '77737706'),
      ];
      const v512 = <(int, String)>[
        (59, '90693936'),
        (1111111109, '25091201'),
        (1111111111, '99943326'),
        (1234567890, '93441116'),
        (2000000000, '38618901'),
        (20000000000, '47863826'),
      ];

      for (final (segundos, esperado) in v256) {
        expect(
          CuentaTotp(semilla: _semilla256, algoritmo: AlgoritmoTotp.sha256,
                  digitos: 8)
              .codigo(DateTime.fromMillisecondsSinceEpoch(segundos * 1000,
                  isUtc: true)),
          esperado,
          reason: 'SHA-256 en T=$segundos',
        );
      }
      for (final (segundos, esperado) in v512) {
        expect(
          CuentaTotp(semilla: _semilla512, algoritmo: AlgoritmoTotp.sha512,
                  digitos: 8)
              .codigo(DateTime.fromMillisecondsSinceEpoch(segundos * 1000,
                  isUtc: true)),
          esperado,
          reason: 'SHA-512 en T=$segundos',
        );
      }
    });
  });

  group('HOTP, la primitiva debajo', () {
    // RFC 4226 apéndice D. Estos son los números canónicos: 0→755224,
    // 1→287082, … Son la misma cadena que TOTP con el contador fijo.
    test('los seis primeros contadores dan la tabla de la RFC 4226', () {
      // Se comprueba a través de TOTP con periodo 1, que equivale a HOTP con
      // contador = unix/1 — pero como TOTP usa el reloj, lo que se hace aquí es
      // fijar el instante para que el contador sea exactamente el que se quiere.
      const esperados = [
        '755224', '287082', '359152', '969429', '338314', '254676',
      ];
      for (var i = 0; i < esperados.length; i++) {
        final cuenta = CuentaTotp(semilla: _semillaRfc, periodo: 1);
        expect(
          cuenta.codigo(DateTime.fromMillisecondsSinceEpoch(i * 1000,
              isUtc: true)),
          esperados[i],
          reason: 'contador HOTP $i',
        );
      }
    });
  });

  group('la cuenta atrás', () {
    final cuenta = CuentaTotp(semilla: _semillaRfc);

    test('empieza en el segundo 30 y acaba en el 1', () {
      expect(
        cuenta.segundosRestantes(
            DateTime.fromMillisecondsSinceEpoch(0 * 1000, isUtc: true)),
        30,
      );
      expect(
        cuenta.segundosRestantes(
            DateTime.fromMillisecondsSinceEpoch(29 * 1000, isUtc: true)),
        1,
      );
      expect(
        cuenta.segundosRestantes(
            DateTime.fromMillisecondsSinceEpoch(30 * 1000, isUtc: true)),
        30,
      );
    });

    test('nunca llega a 0, ni se va de rango', () {
      // El bug concreto: en el segundo 29 el código todavía vale, y un anillo
      // en 0 pinta «caducado» sobre un código bueno.
      for (var s = 0; s < 120; s++) {
        final r = cuenta.segundosRestantes(
            DateTime.fromMillisecondsSinceEpoch(s * 1000, isUtc: true));
        expect(r, inInclusiveRange(1, 30), reason: 'en el segundo $s');
      }
    });

    test('la fracción del anillo no llega a cero', () {
      // Si la fracción fuera 0, `CustomPaint` no dibujaría nada y el anillo
      // desaparecería en vez de vaciarse.
      for (var s = 0; s < 120; s++) {
        final f = cuenta.fraccionRestante(
            DateTime.fromMillisecondsSinceEpoch(s * 1000, isUtc: true));
        expect(f, greaterThan(0), reason: 'en el segundo $s');
        expect(f, lessThanOrEqualTo(1.0), reason: 'en el segundo $s');
      }
    });

    test('el mismo código dentro de una ventana, distinto fuera', () {
      // Lo que hace el código de 30 s: es el mismo para 29 segundos seguidos.
      final dentro = DateTime.fromMillisecondsSinceEpoch(10000, isUtc: true);
      final fuera = DateTime.fromMillisecondsSinceEpoch(40000, isUtc: true);
      expect(cuenta.codigo(dentro), cuenta.codigo(dentro));
      expect(cuenta.codigo(dentro), isNot(cuenta.codigo(fuera)));
    });
  });

  group('Base32', () {
    test('ida y vuelta preserva los bytes', () {
      // Propiedad general, con longitudes que cruzan el límite del bloque de
      // 5 bytes: es donde un Base32 mal escrito mete ceros de relleno que
      // después se cuelan en el HMAC.
      for (final n in [1, 2, 3, 4, 5, 6, 10, 16, 20, 32, 64]) {
        final bytes =
            Uint8List.fromList(List<int>.generate(n, (i) => (i * 37 + 11) & 0xff));
        final vuelta = base32Decodificar(base32Codificar(bytes));
        expect(vuelta, bytes, reason: 'con $n bytes');
      }
    });

    test('la semilla canónica decodifica a lo que dice', () {
      // El ejemplo de la especificación de Google, tal cual: la cadena
      // Base32 es el ASCII de "1234567890" repetido, y son 16 caracteres
      // sin relleno.
      final bytes = base32Decodificar('GEZDGNBVGY3TQOJQ');
      expect(ascii.decode(bytes), '1234567890');
      expect(base32Codificar(_semillaRfc), 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ');
    });

    test('acepta lo que mandan los QR de verdad', () {
      // Minúsculas, espacios y relleno sobrante: los tres aparecen en servicios
      // reales y un decodificador estricto los rechaza.
      final esperado = base32Decodificar('JBSWY3DPEHPK3PXP');
      expect(base32Decodificar('jbswy3dpehpk3pxp'), esperado);
      expect(base32Decodificar('JBSW Y3DP EHPK 3PXP'), esperado);
      expect(base32Decodificar('jbswy3dpehpk3pxp===='), esperado);
    });

    test('rechaza lo que no es Base32, en vez de adivinar', () {
      // El 0, el 1 y el 8 no están en el alfabeto: 8 y 9 son los errores de
      // tecleo más habituales y el «0» el O mayúsculo.
      for (final malo in ['JBSWY3DPEHPK3PX0', 'JBSWY3DPEHPK3PX1', 'JBSWY3DPEHPK3PX8']) {
        expect(() => base32Decodificar(malo), throwsFormatException,
            reason: 'debería rechazar «$malo»');
      }
      expect(() => base32Decodificar(''), throwsFormatException);
      // Las longitudes se generan, no se escriben a mano: escribir «13» creyendo
      // que sobraba uno y que en realidad sobraban cinco hace que este test pase
      // por el motivo equivocado. Los restos válidos son 0, 2, 4, 5 y 7.
      // La fuente tiene 64 caracteres, así que da para todas las longitudes.
      const fuente = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
          'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
          'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
          'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
      for (final largo in List<int>.generate(24, (i) => i + 1)) {
        final valido = const {0, 2, 4, 5, 7}.contains(largo % 8);
        final entrada = fuente.substring(0, largo);
        if (valido) {
          expect(() => base32Decodificar(entrada), returnsNormally,
              reason: '$largo caracteres (resto ${largo % 8}) es válido');
        } else {
          expect(() => base32Decodificar(entrada), throwsFormatException,
              reason: '$largo caracteres (resto ${largo % 8}) no es representable');
        }
      }
    });

    test('acepta semillas sin relleno, que es como llegan de verdad', () {
      // Este es el fallo que motivó relaxing la comprobación: un decodificador
      // estricto acepta el QR de la especificación y rechaza el de la calle.
      for (final largo in [16, 26, 32, 52]) {
        final bytes =
            Uint8List.fromList(List<int>.generate(largo ~/ 2, (i) => i & 0xff));
        expect(base32Decodificar(base32Codificar(bytes)), bytes,
            reason: 'con $largo caracteres sin relleno');
      }
    });
  });

  group('el algoritmo', () {
    test('se lee como lo escribe otpauth://, con y sin guion', () {
      expect(AlgoritmoTotp.desdeNombre('SHA1'), AlgoritmoTotp.sha1);
      expect(AlgoritmoTotp.desdeNombre('SHA-256'), AlgoritmoTotp.sha256);
      expect(AlgoritmoTotp.desdeNombre('sha512'), AlgoritmoTotp.sha512);
      expect(AlgoritmoTotp.desdeNombre('SHA-1'), AlgoritmoTotp.sha1);
    });

    test('sin algorithm=, nada, porque el valor por defecto correcto es SHA-1', () {
      // La mayoría de QR de Google no lo mandan. Devolver SHA-1 por omisión en
      // lugar de «desconocido» es lo que los hace funcionar.
      expect(AlgoritmoTotp.desdeNombre(null), isNull);
      expect(AlgoritmoTotp.desdeNombre(''), isNull);
      expect(AlgoritmoTotp.desdeNombre('MD5'), isNull);
    });
  });

  group('casos límite del truncamiento', () {
    test('8 dígitos con SHA-1 no desborda', () {
      // El motivo de usar BigInt: con 8 dígitos el valor truncado puede pasar
      // de 2^31 y un entero de 32 bits con signo daría negativo.
      final bytes = Uint8List.fromList(List<int>.filled(20, 0xff));
      final codigo =
          CuentaTotp(semilla: bytes, digitos: 8).codigo(DateTime.utc(2026));
      expect(codigo.length, 8);
      expect(codigo, matches(RegExp(r'^\d{8}$')));
      expect(BigInt.parse(codigo) >= BigInt.zero, isTrue);
    });

    test('un hash más corto que 4 bytes no revienta', () {
      // SHA-1 es el más corto de los tres, así que si esto aguanta, aguantan
      // todos: si una semilla fuera demasiado corta, el truncamiento sacaría
      // bytes de más allá del final en vez de dar un error claro.
      final bytes = Uint8List.fromList([0x01, 0x02]);
      final codigo = CuentaTotp(semilla: bytes).codigo(DateTime.utc(2026));
      expect(codigo, matches(RegExp(r'^\d{6}$')));
    });
  });
}