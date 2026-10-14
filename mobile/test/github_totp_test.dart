// El camino completo de GitHub, contra una implementación independiente.
//
// ## Por qué este test existe
// Porque Aegis dejó de calcular bien el código de GitHub y **nada falló**: la
// app pintaba seis dígitos, el anillo de cuenta atrás iba bien, y el servicio
// los rechazaba. Ningún test miraba el problema, porque todos miraban
// **partes**: los vectores de la RFC 6238 probaban el HMAC, y los tests de
// `otpauth` probaban el parseo. Lo que ninguno probaba era **las dos cosas
// juntas**, que es exactamente lo que hace GitHub cuando le entregas un código.
//
// ## Qué es una implementación independiente
// `test/totp_test.dart` ya contrasta los vectores publicados de la RFC 6238.
// Eso demuestra que el HMAC y el truncamiento son los correctos. Lo que este test
// añade es el tramo que va del **QR de GitHub** al **código**: la URL entera, con
// su emisor, su etiqueta, su `algorithm=SHA1` y sus parámetros por defecto, pasa
// por `leerOtpauth` y sale por `codigo`. Si un parámetro se ignora —el periodo,
// sobre todo, que es el que GitHub manda explícitamente— aquí se ve.
//
// ## Por qué el instante es fijo
// Porque un test que llama a `DateTime.now()` falla un día sí y otro no, y el día
// que falla parece un fallo del código cuando lo que se movió fue el reloj.
import 'package:aegis_console/core/auth/otpauth.dart';
import 'package:aegis_console/core/auth/totp.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  // La URL que **de verdad** emite GitHub al activar «Authenticator app». Con el
  // emisor repetido en el path y en la query, que es como la manda GitHub y como
  // lo hace casi todo el mundo.
  const secret = 'JBSWY3DPEHPK3PXP'; // 16 chars: Base32 sin relleno, como GitHub
  const url = 'otpauth://totp/GitHub:demo'
      '?secret=$secret&issuer=GitHub&algorithm=SHA1&digits=6&period=30';

  // Los **instantes** de la RFC 6238, calculados con el secreto de arriba por una
  // implementación de referencia aparte —Python, `hmac` + `hashlib` + el
  // truncamiento de la RFC 4226 §5.3—. No son los vectores publicados de la RFC
  // (esos usan otro secreto, `12345678901234567890`, y están en `totp_test.dart`);
  // son **los mismos instantes con una semilla con forma de GitHub**, que es lo
  // que de hecho entra por el QR.
  //
  // Si Aegis y esto difieren, el fallo es de Aegis y no del reloj ni de GitHub.
  const esperado59 = '996554';
  const esperado1111111109 = '071271';
  const esperado1111111111 = '358462';
  const esperado1234567890 = '742275';
  const esperado20000000000 = '752434';

  group('el QR de GitHub, de principio a fin', () {
    late CuentaQr cuenta;

    setUp(() => cuenta = leerOtpauth(url));

    test('lee el emisor y la etiqueta que manda GitHub', () {
      expect(cuenta.emisor, 'GitHub');
      expect(cuenta.etiqueta, 'demo');
    });

    test('usa los parámetros de GitHub: SHA-1, 6 dígitos, 30 segundos', () {
      expect(cuenta.algoritmo, AlgoritmoTotp.sha1);
      expect(cuenta.digitos, 6);
      expect(cuenta.periodo, 30);
    });

    test('decodifica una semilla Base32 sin relleno', () {
      // Sin el `=` de relleno, que es como los da GitHub. Una decodificación que
      // exigiera relleno produciría una semilla distinta, y por tanto códigos
      // distintos, sin ningún error visible.
      final c = CuentaTotp(semilla: cuenta.semilla);
      expect(c.codigo(DateTime.fromMillisecondsSinceEpoch(59 * 1000, isUtc: true)),
          esperado59);
    });

    test('el código coincide con la referencia en los instantes de la RFC', () {
      // Los mismos cinco vectores que usa `totp_test.dart`, pero **entrando por
      // la URL** y no por la función pura. Es la diferencia entre probar el motor
      // y probar el coche con carretera.
      final c = CuentaTotp(semilla: cuenta.semilla);
      String codigoEn(int segundos) => c.codigo(
          DateTime.fromMillisecondsSinceEpoch(segundos * 1000, isUtc: true));

      expect(codigoEn(59), esperado59);
      expect(codigoEn(1111111109), esperado1111111109);
      expect(codigoEn(1111111111), esperado1111111111);
      expect(codigoEn(1234567890), esperado1234567890);
      expect(codigoEn(20000000000), esperado20000000000);
    });

    test('un desfase de reloj de 30 s cambia el código, y eso explica un rechazo', () {
      // No es un test de que Aegis esté bien: es la **explicación** del síntoma.
      // Con dos ventanas de 30 s separadas, los códigos son distintos, y el
      // servicio rechaza el que no le toca. Lo que hace este test es dejar escrito
      // que «el reloj va bien» hay que demostrarlo, no suponerlo.
      final c = CuentaTotp(semilla: cuenta.semilla);
      final ahora = DateTime.fromMillisecondsSinceEpoch(20000000000 * 1000, isUtc: true);
      final dentroDe30 = c.codigo(ahora.add(const Duration(seconds: 30)));
      expect(dentroDe30, isNot(c.codigo(ahora)));
    });

    test('el periodo manda: 60 segundos daría otros códigos', () {
      // Outlook usa 60. Si `periodo` se ignorara y se quedara en 30, los códigos
      // saldrían bien para GitHub y **mal** para Outlook, y el fallo aparecería
      // en un servicio distinto con la misma app. Aquí queda atado.
      final con60 = CuentaTotp(
          semilla: cuenta.semilla, periodo: 60);
      final con30 = CuentaTotp(semilla: cuenta.semilla, periodo: 30);
      final t = DateTime.fromMillisecondsSinceEpoch(1111111109 * 1000, isUtc: true);
      expect(con60.codigo(t), isNot(con30.codigo(t)));
    });
  });
}