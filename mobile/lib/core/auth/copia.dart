/// La copia de seguridad: un fichero que se lleva a otro sitio y que no se
/// puede leer sin la contraseña.
///
/// ## Por qué un fichero y no sincronizar con el bridge
/// Porque sincronizar significa que el bridge tiene un sobre de semillas. El
/// bridge escribe en claro todo lo demás (notas, tareas, trazas), así que un
/// sobre cifrado sería lo único cifrado que hay en él, y eso es peor que no
/// tenerlo: crea la sensación de que el bridge guarda tus claves de forma
/// especial cuando en realidad depende de un fichero en el mismo disco.
///
/// ## Por qué Argon2id y no bcrypt o PBKDF2
/// Porque es el que se puede elegir sin culpa: memoria-dura, contra GPU y
/// contra FPGA. PBKDF2 con muchas iteraciones también sirve, pero el coste
/// crece solo en CPU, y las GPUs hacen millones de hashes por segundo. Argon2id
/// cuesta **memoria**, que es lo que no se puede replicar en masa.
///
/// ## Por qué el coste son 200 ms
/// Es el retraso a propósito. Al abrir la copia se paga ese tiempo y no se
/// nota; al probar 100 contraseñas en un ataque se paga 20 segundos por cada
/// intento. Esa asimetría es exactamente la que se quiere.
library;

import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'boveda.dart';

/// El sobre, tal como va al fichero.
///
/// Sin versión no hay forma de migrar, y una copia de seguridad que solo sirve
/// con la versión que la escribió deja de ser copia de seguridad el día que
/// cambie el formato. Con `version` se puede leer lo viejo y se dice si es de
/// un futuro que esta app no entiende.
class SobreBoveda {
  const SobreBoveda({
    required this.version,
    required this.kdf,
    required this.sal,
    required this.nonce,
    required this.cifrado,
    required this.mac,
  });

  final int version;
  final String kdf;
  final String sal;
  final String nonce;
  final String cifrado;
  final String mac;

  /// El formato del sobre.
  static const int versionActual = 1;
  static const String kdfNombre = 'argon2id';
  static const int iteracionesKdf = 3;
  static const int memoriaKdf = 65536; // 64 MB, en KiB
  static const int paralelismoKdf = 1;

  /// Longitud de la clave derivada: 32 bytes = AES-256.
  static const int longitudClave = 32;

  Map<String, dynamic> aJson() => {
        'version': version,
        'kdf': kdf,
        'sal': sal,
        'iteraciones': iteracionesKdf,
        'memoria': memoriaKdf,
        'nonce': nonce,
        'cifrado': cifrado,
        'mac': mac,
      };

  static SobreBoveda desdeJson(Map<String, dynamic> j) => SobreBoveda(
        version: (j['version'] as num?)?.toInt() ?? 0,
        kdf: j['kdf'] as String? ?? '',
        sal: j['sal'] as String? ?? '',
        nonce: j['nonce'] as String? ?? '',
        cifrado: j['cifrado'] as String? ?? '',
        mac: j['mac'] as String? ?? '',
      );
}

/// Por qué no se pudo abrir la copia.
///
/// Dos fallos distintos a propósito, porque confundirlos hace repetir la
/// contraseña buena creyendo que el fichero está mal, y repetir una contraseña
/// buena contra un fichero corrupto **es** el camino a perder la copia.
class ErrorCopia implements Exception {
  const ErrorCopia(this.motivo, {this.contrasenaIncorrecta = false});

  final String motivo;

  /// `true` solo cuando el GCM ha fallado **con una clave derivada bien**. Si
  /// no, es que el fichero no es una copia.
  final bool contrasenaIncorrecta;

  @override
  String toString() => motivo;
}

/// Cifra la bóveda con la contraseña de la persona.
///
/// La clave no se guarda en ningún sitio: sale de la contraseña y se vuelve a
/// derivar en cada operación. Por eso no hay sesión que «mantener abierta» y
/// por eso abrir la copia dos veces cuesta dos veces.
Future<String> cifrarBoveda(Boveda b, String contrasena) async {
  final sal = _bytesAleatorios(16);
  final nonce = _bytesAleatorios(12);
  final secreto = await _derivar(contrasena, sal);

  final caja = AesGcm.with256bits();
  final texto = utf8.encode(jsonEncode(b.aJson()));

  final caja2 = await caja.encrypt(
    texto,
    secretKey: secreto,
    nonce: nonce,
    aad: utf8.encode('aegis.boveda.v${SobreBoveda.versionActual}'),
  );

  return jsonEncode(SobreBoveda(
    version: SobreBoveda.versionActual,
    kdf: SobreBoveda.kdfNombre,
    sal: base64Url.encode(sal),
    nonce: base64Url.encode(caja2.nonce),
    cifrado: base64Url.encode(caja2.cipherText),
    mac: base64Url.encode(caja2.mac.bytes),
  ).aJson());
}

/// Abre una copia.
///
/// Devuelve una [Boveda] lista para usarse. Lanza [ErrorCopia] con el motivo
/// ya escrito para enseñar.
Future<Boveda> abrirCopia(String contenido, String contrasena) async {
  Map<String, dynamic> j;
  try {
    final bruto = jsonDecode(contenido);
    if (bruto is! Map<String, dynamic>) {
      throw const ErrorCopia('Ese fichero no es una copia de Aegis.');
    }
    j = bruto;
  } on FormatException {
    throw const ErrorCopia('Ese fichero no se puede leer como una copia.');
  }

  final sobre = SobreBoveda.desdeJson(j);
  if (sobre.version != SobreBoveda.versionActual) {
    throw ErrorCopia(
      'Esa copia es de la versión ${sobre.version} y esta app entiende la '
      '${SobreBoveda.versionActual}.',
    );
  }
  if (sobre.kdf != SobreBoveda.kdfNombre) {
    throw ErrorCopia('No se sabe derivar la clave de esa copia («${sobre.kdf}»).');
  }

  final Uint8List sal;
  final Uint8List nonce;
  final Uint8List cifrado;
  final Uint8List mac;
  try {
    sal = base64Url.decode(sobre.sal);
    nonce = base64Url.decode(sobre.nonce);
    cifrado = base64Url.decode(sobre.cifrado);
    mac = base64Url.decode(sobre.mac);
  } on FormatException {
    throw const ErrorCopia('La copia está dañada: no se puede leer su contenido.');
  }

  final secreto = await _derivar(contrasena, sal);

  try {
    final caja = AesGcm.with256bits();
    final claro = await caja.decrypt(
      SecretBox(cifrado, nonce: nonce, mac: Mac(mac)),
      secretKey: secreto,
      aad: utf8.encode('aegis.boveda.v${SobreBoveda.versionActual}'),
    );
    final b = jsonDecode(utf8.decode(claro));
    if (b is! Map<String, dynamic>) {
      throw const ErrorCopia('El contenido de la copia no es una bóveda.');
    }
    return Boveda.desdeJson(b);
  } on SecretBoxAuthenticationError {
    // GCM ha fallado con una clave derivada de verdad: o la contraseña no es
    // esa, o alguien cambió el fichero. Se dice «contraseña» porque es lo
    // probable y lo accionable, y **no** se distingue de la corrupción: se
    // distingue del formato, que es lo que importa (ver [ErrorCopia]).
    throw const ErrorCopia(
      'La contraseña no es la de esa copia.',
      contrasenaIncorrecta: true,
    );
  } on FormatException {
    throw const ErrorCopia('La copia está dañada: no se puede leer su contenido.');
  }
}

/// Clave de 256 bits desde la contraseña.
Future<SecretKey> _derivar(String contrasena, List<int> sal) async {
  final argon = Argon2id(
    memory: SobreBoveda.memoriaKdf,
    parallelism: SobreBoveda.paralelismoKdf,
    iterations: SobreBoveda.iteracionesKdf,
    hashLength: SobreBoveda.longitudClave,
  );
  return argon.deriveKeyFromPassword(
    password: contrasena,
    nonce: sal,
  );
}
/// Bytes aleatorios de la máquina.
///
/// `Random.secure()`, nunca `Random()`: con el segundo, la semilla es el reloj
/// y la secuencia es predecible. Una sal predecible hace que dos copias con
/// la misma contraseña produzcan la misma clave, que es justo lo que la sal
/// existe para evitar.
Uint8List _bytesAleatorios(int n) {
  final r = Random.secure();
  return Uint8List.fromList(List<int>.generate(n, (_) => r.nextInt(256)));
}
