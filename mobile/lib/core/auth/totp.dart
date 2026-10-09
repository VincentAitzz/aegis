/// TOTP: el cálculo del código, y solo el cálculo.
///
/// ## Por qué esto está escrito aquí y no en un paquete
/// `otp` de pub.dev haría lo mismo en menos código. Se ha escrito a mano por una
/// razón concreta: **el test de los vectores de la RFC 6238 vive en este repo**.
/// Un autenticador cuyo correctness se delega en una caja negra de la que nadie
/// del equipo ha leído el truncamiento dinámico no es un autenticador; es una
/// dependencia que se espera que haga lo correcto. Con el cálculo aquí, el test
/// que lo demuestra se lee en `test/totp_test.dart` y se puede cambiar el código
/// sin miedo.
///
/// ## Qué es la fórmula, en una frase
/// Un contador de 30 segundos, pasado por HMAC con la semilla, del que se
///Dynamic-trunca un trozo y se toma módulo 10^dígitos. Todo lo demás son
/// detalles de codificación (Base32, big-endian) que la RFC define y por eso
/// están escritos como los define.
///
/// ## Por qué el reloj entra por parámetro y no se lee dentro
/// Porque la cuenta atrás la lleva la UI y porque un test que dependa del reloj
/// del sistema es un test que falla un día sí y otro no. Todas las funciones
/// puras reciben el instante.
/// Prefijado a propósito: los valores del enum se llaman `sha1`, `sha256` y
/// `sha512`, que son **exactamente** los nombres de las funciones de `crypto`.
/// Sin el prefijo, `AlgoritmoTotp.sha1` resuelve al enum y no al hash, y el
/// error que sale es «no se puede devolver AlgoritmoTotp desde Hash» — que no
/// señala el sitio real del problema. Nombrar el enum distinto que el hash
/// sería lo otro, y entonces `AlgoritmoTotp.sha1` se leería como «el SHA-1»,
/// que es lo que significa.
library;

import 'dart:typed_data';

import 'package:crypto/crypto.dart' as crypto;

import 'package:crypto/crypto.dart' show Hmac;

/// El hash que firma el contador.
///
/// En TOTP esto casi nunca es SHA-1: SHA-1 es lo que dice la RFC 6238 porque
/// en 2005 era lo normal, y **casi todos los servicios lo siguen usando** por
/// compatibilidad. Los otros dos existen y hay que soportarlos, porque hay
/// emisores que los usan y un autenticador que rechaza un QR válido no es un
/// autenticador.
enum AlgoritmoTotp {
  sha1('SHA1'),
  sha256('SHA256'),
  sha512('SHA512');

  const AlgoritmoTotp(this.nombre);

  /// Cómo lo escribe `otpauth://`.
  final String nombre;

  /// Lee el `algorithm=` del URI. Devuelve `null` si no hay ninguno, porque la
  /// clave de Google no lo manda y el valor por defecto correcto es SHA-1.
  static AlgoritmoTotp? desdeNombre(String? nombre) {
    if (nombre == null || nombre.isEmpty) return null;
    final limpio = nombre.toUpperCase().replaceAll('-', '');
    for (final a in AlgoritmoTotp.values) {
      if (a.nombre == limpio) return a;
    }
    return null;
  }

  crypto.Hash get _hash => switch (this) {
        AlgoritmoTotp.sha1 => crypto.sha1,
        AlgoritmoTotp.sha256 => crypto.sha256,
        AlgoritmoTotp.sha512 => crypto.sha512,
      };
}

/// La cuenta que produce el código.
///
/// No es solo la semilla: el periodo, los dígitos y el algoritmo son parte de
/// la cuenta, y un código calculado con los valores por defecto sobre una cuenta
/// que usa otros **no lo rechaza el servicio, lo acepta y es incorrecto**. Ese
/// es el fallo más caro posible aquí: no se ve, se descubre en el login.
class CuentaTotp {
  const CuentaTotp({
    required this.semilla,
    this.algoritmo = AlgoritmoTotp.sha1,
    this.digitos = 6,
    this.periodo = 30,
  });

  /// El secreto compartido, **en bytes**. No en Base32: la decodificación es
  /// cosa de [base32Decodificar] y así el cálculo no depende de cómo venía
  /// escrito en el QR.
  final Uint8List semilla;

  final AlgoritmoTotp algoritmo;

  /// 6 en la práctica. 8 aparece en bancos, y con 8 el módulo es 10^8 en vez
  /// de 10^6: si esto se calculara con enteros de 64 bits se desborda, y por
  /// eso el módulo se aplica sobre `BigInt`.
  final int digitos;

  /// 30 en todo el mundo salvo Outlook, que usa 60. Es el parámetro que más se
  /// ignora y el que más falla cuando se ignora.
  final int periodo;

  /// Un T = int(unix / periodo).
  int contador(DateTime instante) =>
      instante.millisecondsSinceEpoch ~/ 1000 ~/ periodo;

  /// El código en [instante], como cadena de [digitos] con ceros a la izquierda.
  ///
  /// Los ceros del principio son lo que más se olvida y lo que más duele: un
  /// código de 5 dígitos donde tocaba poner `0` no falla, se copia mal.
  String codigo(DateTime instante) {
    // El contador va como 8 bytes big-endian (RFC 4226 §5.3), no como texto.
    final c = contador(instante);
    final msg = ByteData(8)..setUint64(0, c, Endian.big);

    final hmac = Hmac(algoritmo._hash, semilla)
        .convert(msg.buffer.asUint8List());
    final h = hmac.bytes;

    // Truncamiento dinámico (RFC 4226 §5.3): el byte bajo del último nibble dice
    // **qué** trozo se corta, y ese byte puede ser mayor que el tamaño del
    // hash en SHA-1 — por eso el módulo y no el índice directo.
    final offset = h[h.length - 1] & 0x0f;
    final binario = ((h[offset] & 0x7f) << 24) |
        ((h[offset + 1] & 0xff) << 16) |
        ((h[offset + 2] & 0xff) << 8) |
        (h[offset + 3] & 0xff);

    final modulo = BigInt.from(10).pow(digitos);
    return (BigInt.from(binario) % modulo)
        .toString()
        .padLeft(digitos, '0');
  }

  /// Cuántos segundos quedan para que este código caduque.
  ///
  /// Devuelve un valor en [1, periodo], nunca 0 ni negativo: un anillo que llega
  /// a 0 mientras el código todavía es válido se ve como «caducado» cuando no
  /// lo está, y hace pulsar «refrescar» a alguien que no hacía falta.
  int segundosRestantes(DateTime instante) {
    final elapsed = (instante.millisecondsSinceEpoch ~/ 1000) % periodo;
    final resto = periodo - elapsed;
    return resto <= 0 ? periodo : resto;
  }

  /// La fracción de ventana que queda, de 1 (nada) a 0 (todo gastado), para el
  /// anillo. Se acota por abajo para no dibujar un anillo invisible.
  double fraccionRestante(DateTime instante) {
    final s = segundosRestantes(instante);
    final f = s / periodo;
    return f < 0.02 ? 0.02 : f;
  }
}

/// Base32 (RFC 4648), el alfabeto en que viajan las semillas.
///
/// ## Por qué acepta longitudes sin relleno
/// Base32 canónico rellena a múltiplo de 8 con `=`, y **casi ningún emisor lo
/// hace**: la clave de Google llega con 16, 32 o 26 caracteres y nada de
/// relleno. Comprobar `length % 8 == 0` como primer filtro —que es lo que hace
/// un decodificador estricto— rechaza justo las semillas que de verdad se usan.
///
/// Lo que sí se comprueba es que la longitud sea **representable**: los restos
/// 1 y 3 y 6 no corresponden a ningún número de bytes, así que sí son un error
/// de formato y no una variante. Los restos 0, 2, 4, 5 y 7 sí valen, con o sin
/// relleno.
Uint8List base32Decodificar(String entrada) {
  final limpio = entrada.toUpperCase().replaceAll(RegExp(r'[\s=]'), '');
  if (limpio.isEmpty) {
    throw const FormatException('semilla vacía');
  }
  // 1, 3 y 6 caracteres sobran no describen ningún número de bytes entero.
  if (!const {0, 2, 4, 5, 7}.contains(limpio.length % 8)) {
    throw FormatException('Base32 con longitud no representable: '
        '${limpio.length} caracteres');
  }

  final bytes = <int>[];
  var buffer = 0;
  var bits = 0;
  for (final c in limpio.codeUnits) {
    final v = _base32Valor(c);
    if (v < 0) {
      throw FormatException('carácter no Base32: ${String.fromCharCode(c)}');
    }
    buffer = (buffer << 5) | v;
    bits += 5;
    if (bits >= 8) {
      bits -= 8;
      bytes.add((buffer >> bits) & 0xff);
    }
  }
  return Uint8List.fromList(bytes);
}

/// Codifica a Base32. Existe para el round-trip del test y para exportar, no
/// porque el cálculo la necesite en ningún sentido.
String base32Codificar(Uint8List bytes) {
  if (bytes.isEmpty) return '';
  var buffer = 0;
  var bits = 0;
  final out = StringBuffer();
  for (final b in bytes) {
    buffer = (buffer << 8) | b;
    bits += 8;
    while (bits >= 5) {
      bits -= 5;
      out.write(_base32Alfabeto[(buffer >> bits) & 0x1f]);
    }
  }
  if (bits > 0) {
    out.write(_base32Alfabeto[(buffer << (5 - bits)) & 0x1f]);
  }
  return out.toString();
}

const _base32Alfabeto = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

/// -1 si el carácter no es del alfabeto. Se usa -1 y no una excepción para no
/// pagar una excepción por carácter en el camino caliente de un QR válido.
int _base32Valor(int c) {
  if (c >= 0x41 && c <= 0x5a) return c - 0x41; // A-Z
  if (c >= 0x32 && c <= 0x37) return c - 0x32 + 26; // 2-7
  return -1;
}