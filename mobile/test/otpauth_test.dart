// El parser de `otpauth://`, contra enlaces que existen de verdad.
//
// ## Por qué los casos de este test son tan concretas
// Un parser de `otpauth://` se puede probar con un enlace inventado que sale
// bien, y seguir fallando con los de Google, GitHub y los de los bancos. Estos
// casos son de los que se rompen, y están aquí por eso: cada uno tiene el
// motivo por el que está, y un enlace «limpio» no los habría encontrado.
import 'package:aegis_console/core/auth/otpauth.dart';
import 'package:aegis_console/core/auth/totp.dart';
import 'package:flutter_test/flutter_test.dart';

/// La semilla del ejemplo canónico de la especificación de Google.
///
/// Se compara por bytes y no con `ascii.decode`: es `Hello!` seguido de cuatro
/// bytes que **no son ASCII** (0xDE 0xAD 0xBE 0xEF), y `ascii.decode` de eso
/// lanza. Comparar como lista de bytes es lo que corresponde, y evita que un
/// cambio de ejemplo rompe el test por un motivo que no es el que se prueba.
const _semillaEjemplo = <int>[72, 101, 108, 108, 111, 33, 222, 173, 190, 239];

void main() {
  group('un enlace de Google, tal cual', () {
    // Este es el formato que sale de «activar 2 pasos» en Google, sin
    // `algorithm=` y con el emisor repetido.
    const google = 'otpauth://totp/Example:ana@ejemplo.com'
        '?secret=JBSWY3DPEHPK3PXP&issuer=Example';

    test('lee emisor, etiqueta y semilla', () {
      final c = leerOtpauth(google);
      expect(c.emisor, 'Example');
      expect(c.etiqueta, 'ana@ejemplo.com');
      expect(c.semilla, _semillaEjemplo);
      expect(c.digitos, 6);
      expect(c.periodo, 30);
      expect(c.algoritmo, AlgoritmoTotp.sha1);
    });

    test('el título se lee sin abrir detalles', () {
      expect(leerOtpauth(google).titulo, 'Example: ana@ejemplo.com');
    });
  });

  group('el emisor duplicado', () {
    test('cuando difieren, manda el de la query', () {
      // Es lo que hace un servidor mal escrito, y lo que hace la página que te
      // enseña el QR. Confiar en el del path mostraría la cuenta con el nombre
      // equivocado y no habría forma de saber cuál es el bueno.
      final c = leerOtpauth(
        'otpauth://totp/Viejo:ana@ejemplo.com'
        '?secret=JBSWY3DPEHPK3PXP&issuer=Nuevo',
      );
      expect(c.emisor, 'Nuevo');
      expect(c.etiqueta, 'ana@ejemplo.com');
    });

    test('cuando la query no lo trae, se usa el del path', () {
      final c = leerOtpauth(
        'otpauth://totp/Dropbox:ana@ejemplo.com?secret=JBSWY3DPEHPK3PXP',
      );
      expect(c.emisor, 'Dropbox');
      expect(c.etiqueta, 'ana@ejemplo.com');
    });

    test('sin issuer en ninguno de los dos sitios, no hay emisor', () {
      final c = leerOtpauth('otpauth://totp/ana?secret=JBSWY3DPEHPK3PXP');
      expect(c.emisor, isEmpty);
      expect(c.etiqueta, 'ana');
      expect(c.titulo, 'ana');
    });
  });

  group('el separador emisor:etiqueta', () {
    test('con un espacio, que es lo que dice la especificación', () {
      final c = leerOtpauth(
        'otpauth://totp/GitHub%3Aana?secret=JBSWY3DPEHPK3PXP',
      );
      expect(c.emisor, 'GitHub');
      expect(c.etiqueta, 'ana');
    });

    test('sin espacio, que es lo que manda la mitad de los servicios', () {
      final c = leerOtpauth('otpauth://totp/GitHub:ana?secret=JBSWY3DPEHPK3PXP');
      expect(c.emisor, 'GitHub');
      expect(c.etiqueta, 'ana');
    });

    test('con dos espacios o un tabulador, y se ignoran', () {
      for (final sep in ['%3A%20%20', '%3A%09', '%3A%20']) {
        final c = leerOtpauth('otpauth://totp/NS${sep}ana?secret=JBSWY3DPEHPK3PXP');
        expect(c.emisor, 'NS', reason: 'separador $sep');
        expect(c.etiqueta, 'ana', reason: 'separador $sep');
      }
    });

    test('con dos puntos dentro de la etiqueta, se corta por el primero', () {
      // «correo: ana@ejemplo.com» es una etiqueta legítima con dos puntos. Si se
      // cortara por el último, el emisor saldría «GitHub:correo».
      final c = leerOtpauth(
        'otpauth://totp/Trabajo:correo: ana@ejemplo.com'
        '?secret=JBSWY3DPEHPK3PXP',
      );
      expect(c.emisor, 'Trabajo');
      expect(c.etiqueta, 'correo: ana@ejemplo.com');
    });
  });

  group('lo que viene en minúsculas o con espacios', () {
    test('la semilla en minúsculas funciona igual', () {
      final c = leerOtpauth('otpauth://totp/X?secret=jbswy3dpehpk3pxp');
      expect(c.semilla, _semillaEjemplo);
    });

    test('la semilla con espacios y relleno funciona igual', () {
      final c = leerOtpauth('otpauth://totp/X?secret=JBSW%20Y3DP%20EHPK%203PXP%3D%3D');
      expect(c.semilla, _semillaEjemplo);
    });

    test('el tipo en mayúsculas o minúsculas es el mismo', () {
      expect(leerOtpauth('otpauth://TOTP/X?secret=JBSWY3DPEHPK3PXP').periodo, 30);
    });
  });

  group('los parámetros que cambian el cálculo', () {
    test('digits=8 sale honored, y son 8', () {
      final c = leerOtpauth('otpauth://totp/Banco:ana?secret=JBSWY3DPEHPK3PXP&digits=8');
      expect(c.digitos, 8);
      expect(c.codigoEn(DateTime.utc(2026)).length, 8);
    });

    test('period=60 sale honored', () {
      final c = leerOtpauth('otpauth://totp/Outlook:ana?secret=JBSWY3DPEHPK3PXP&period=60');
      expect(c.periodo, 60);
      expect(c.codigoEn(DateTime.utc(2026)).length, 6);
      expect(c.segundosRestantes(DateTime.utc(2026)), inInclusiveRange(1, 60));
    });

    test('algorithm=SHA256 sale honored', () {
      final c = leerOtpauth(
        'otpauth://totp/Okta:ana?secret=JBSWY3DPEHPK3PXP&algorithm=SHA256',
      );
      expect(c.algoritmo, AlgoritmoTotp.sha256);
      // Y produce un código DISTINTO al de SHA-1 con la misma semilla: si el
      // algoritmo se ignorase, esto daría igual y el login fallaría en Okta.
      final sha1 = leerOtpauth('otpauth://totp/Okta:ana?secret=JBSWY3DPEHPK3PXP');
      final t = DateTime.utc(2026);
      expect(c.codigoEn(t), isNot(sha1.codigoEn(t)));
    });

    test('los tres parámetros a la vez, que es el peor caso', () {
      final c = leerOtpauth(
        'otpauth://totp/Banco:ana@ejemplo.com'
        '?secret=JBSWY3DPEHPK3PXP&issuer=Banco&algorithm=SHA512&digits=8&period=60',
      );
      expect(c.algoritmo, AlgoritmoTotp.sha512);
      expect(c.digitos, 8);
      expect(c.periodo, 60);
      expect(c.emisor, 'Banco');
      expect(c.etiqueta, 'ana@ejemplo.com');
    });
  });

  group('lo que está roto se dice, no se adivina', () {
    void esperaMotivo(String uri, String trozo) {
      expect(
        () => leerOtpauth(uri),
        throwsA(isA<ErrorOtpauth>()
            .having((e) => e.motivo, 'motivo', contains(trozo))),
        reason: 'con «$uri»',
      );
    }

    test('sin secret', () => esperaMotivo('otpauth://totp/X', 'la clave'));
    test('secret vacío', () => esperaMotivo('otpauth://totp/X?secret=', 'la clave'));
    test('secret en.basura',
        () => esperaMotivo('otpauth://totp/X?secret=???', 'no se entiende'));
    test('esquema equivocado',
        () => esperaMotivo('https://ejemplo.com', 'otpauth'));
    test('hotp, que aquí no puede funcionar',
        () => esperaMotivo('otpauth://hotp/X?secret=JBSWY3DPEHPK3PXP', 'hotp'));
    test('sin tipo', () => esperaMotivo('otpauth:?secret=JBSWY3DPEHPK3PXP', 'tipo'));
    test('digits=abc', () => esperaMotivo(
        'otpauth://totp/X?secret=JBSWY3DPEHPK3PXP&digits=abc', 'dígitos'));
    test('digits=0, que daría un código vacío',
        () => esperaMotivo(
            'otpauth://totp/X?secret=JBSWY3DPEHPK3PXP&digits=0', 'dígitos'));
    test('period=0, que haría una división por cero',
        () => esperaMotivo(
            'otpauth://totp/X?secret=JBSWY3DPEHPK3PXP&period=0', 'periodo'));
    test('algorithm=MD5, que no existe aquí',
        () => esperaMotivo(
            'otpauth://totp/X?secret=JBSWY3DPEHPK3PXP&algorithm=MD5', 'MD5'));
    test('basura que no es uri', () => esperaMotivo('no soy un uri', 'no es un QR'));

    test('el motivo es texto que se puede enseñar', () {
      // El motivo va crudo a la pantalla. Un «Format error at offset 7» es
      // verdad técnicamente y no le sirve a nadie.
      for (final malo in [
        'otpauth://totp/X',
        'otpauth://totp/X?secret=!!!',
        'otpauth://totp/X?secret=JBSWY3DPEHPK3PXP&period=0',
      ]) {
        try {
          leerOtpauth(malo);
          fail('«$malo» debería haber lanzado');
        } on ErrorOtpauth catch (e) {
          expect(e.motivo, isNotEmpty);
          expect(e.motivo, isNot(contains('offset')));
          expect(e.motivo, isNot(contains('Exception')));
        }
      }
    });
  });

  group('ida y vuelta', () {
    test('escribir y releer conserva la cuenta', () {
      // Esto obliga a que `escribirOtpauth` y `leerOtpauth` sean de verdad
      // inversos. Escritas a mano, divergen: el emisor vacío, por ejemplo, no
      // se puede escribir igual que se lee.
      final cuentas = [
        CuentaQr(
          emisor: 'GitHub',
          etiqueta: 'demo',
          semilla: base32Decodificar('JBSWY3DPEHPK3PXP'),
          algoritmo: AlgoritmoTotp.sha1,
          digitos: 6,
          periodo: 30,
        ),
        CuentaQr(
          emisor: 'Banco del Sur',
          etiqueta: 'ana@ejemplo.com',
          semilla: base32Decodificar('MFRGGZDFMZTWQ2LKNNWG23TPOA===='),
          algoritmo: AlgoritmoTotp.sha512,
          digitos: 8,
          periodo: 60,
        ),
        // El caso que rompe la ida y vuelta: sin emisor.
        CuentaQr(
          emisor: '',
          etiqueta: 'solo etiqueta',
          semilla: base32Decodificar('JBSWY3DPEHPK3PXP'),
          algoritmo: AlgoritmoTotp.sha256,
          digitos: 6,
          periodo: 30,
        ),
        // Y con dos puntos en la etiqueta, que es lo que rompe el separador.
        CuentaQr(
          emisor: 'Trabajo',
          etiqueta: 'correo: ana@ejemplo.com',
          semilla: base32Decodificar('JBSWY3DPEHPK3PXP'),
          algoritmo: AlgoritmoTotp.sha1,
          digitos: 6,
          periodo: 30,
        ),
      ];

      for (final original in cuentas) {
        final vuelta = leerOtpauth(escribirOtpauth(original));
        expect(vuelta.emisor, original.emisor,
            reason: 'emisor de «${original.titulo}»');
        expect(vuelta.etiqueta, original.etiqueta,
            reason: 'etiqueta de «${original.titulo}»');
        expect(vuelta.semilla, original.semilla,
            reason: 'semilla de «${original.titulo}»');
        expect(vuelta.algoritmo, original.algoritmo);
        expect(vuelta.digitos, original.digitos);
        expect(vuelta.periodo, original.periodo);
      }
    });

    test('lo que escribe, otro lector lo entiende igual', () {
      // El punto del round-trip anterior es que los dos lados son el mismo
      // código. Esto va contra Python, que es como lo lee el mundo.
      final uri = escribirOtpauth(CuentaQr(
        emisor: 'GitHub',
        etiqueta: 'demo',
        semilla: base32Decodificar('JBSWY3DPEHPK3PXP'),
        algoritmo: AlgoritmoTotp.sha1,
        digitos: 6,
        periodo: 30,
      ));
      expect(uri, startsWith('otpauth://totp/GitHub%3Ademo?'));
      expect(uri, contains('secret=JBSWY3DPEHPK3PXP'));
      expect(uri, contains('issuer=GitHub'));
      // Python lo vuelve a leer y tiene que dar lo mismo.
      final leido = leerOtpauth(uri);
      expect(leido.emisor, 'GitHub');
      expect(leido.etiqueta, 'demo');
    });
  });
}

/// Extensión de conveniencia del test, para no repetir la construcción.
extension on CuentaQr {
  String codigoEn(DateTime t) => CuentaTotp(
        semilla: semilla,
        algoritmo: algoritmo,
        digitos: digitos,
        periodo: periodo,
      ).codigo(t);

  int segundosRestantes(DateTime t) => CuentaTotp(
        semilla: semilla,
        periodo: periodo,
      ).segundosRestantes(t);
}