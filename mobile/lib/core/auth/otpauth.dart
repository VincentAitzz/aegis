/// Lo que hay dentro de un `otpauth://`, y cómo se pone en la bóveda.
///
/// ## Por qué esto necesita un parser propio y no `Uri` solo
/// `Uri.parse` sí sabe descomponer el esquema, pero el formato tiene tres
/// rarezas que hacen que el parseo «correcto» dé cosas equivocadas:
///
/// 1. **El emisor aparece dos veces.** Va en el path (`otpauth://totp/GitHub:user`)
///    y otra vez en la query (`&issuer=GitHub`). Cuando coinciden no hay debate;
///    cuando no coinciden, lo que manda es el de la query, porque es el que
///    escribe la página que te está dando el QR. Un parser que se quede con el
///    del path muestra «Example» en cuentas que son de «GitHub».
/// 2. **La etiqueta y el emisor van separados por dos caracteres.** El separador
///    oficial es `:` seguido de **un espacio**, pero hay servicios que mandan
///    `:` a secas, `:` con dos espacios, o `:` con un tabulador. Sin `+` (que es
///    lo que `Uri` decodifica a espacio) el «espacio» no está.
/// 3. **La cuenta viene en Base32 y en minúsculas.** Ya se relaja en
///    [base32Decodificar]; aquí solo se normaliza el nombre.
library;

import 'dart:typed_data';

import 'totp.dart';

/// Una cuenta recién leída de un QR.
///
/// No es todavía una cuenta de la bóveda: no tiene `id` ni fecha. Esa
/// separación es a propósito, para que la UI pueda **enseñar lo que va a
/// guardar antes de guardarlo** — una app que añade una cuenta sin preguntar
/// cuál es se mete una cuenta equivocada y nadie la encuentra después.
class CuentaQr {
  const CuentaQr({
    required this.emisor,
    required this.etiqueta,
    required this.semilla,
    required this.algoritmo,
    required this.digitos,
    required this.periodo,
  });

  final String emisor;
  final String etiqueta;
  final Uint8List semilla;
  final AlgoritmoTotp algoritmo;
  final int digitos;
  final int periodo;

  /// Lo que se lee sin abrir detalles. `GitHub:demo`, o solo la etiqueta si el
  /// emisor vino vacío.
  String get titulo =>
      emisor.isEmpty ? etiqueta : (etiqueta.isEmpty ? emisor : '$emisor: $etiqueta');
}

/// Por qué no se pudo leer el QR.
///
/// Distinto de «formato desconocido» a propósito: son dos mensajes distintos
/// para el usuario y confundirlos hace que alguien con una cuenta de 8 dígitos
/// busque el error en el sitio equivocado.
class ErrorOtpauth implements Exception {
  const ErrorOtpauth(this.motivo);

  final String motivo;

  @override
  String toString() => 'ErrorOtpauth: $motivo';
}

/// Lee un `otpauth://`.
///
/// Lanza [ErrorOtpauth] con un motivo en español, porque el texto se enseña
/// tal cual. Un `FormatException('Format error at offset 7')` en la cara de
/// alguien que ha hecho todo bien es la peor forma de fallar.
CuentaQr leerOtpauth(String uri) {
  final u = Uri.tryParse(uri.trim());
  if (u == null) {
    throw const ErrorOtpauth('Eso no es un enlace válido.');
  }
  if (u.scheme.toLowerCase() != 'otpauth') {
    // Un esquema vacío no es «cualquier esquema»: es que no había enlace. Lo
    // más normal es haber escaneado algo que no es un QR de autenticación —un
    // código de barras, una URL— y el mensaje tiene que decir eso y no
    // «el enlace dice ‹›».
    if (u.scheme.isEmpty) {
      throw const ErrorOtpauth(
          'Eso no es un QR de autenticación: no empieza por «otpauth://».');
    }
    throw ErrorOtpauth('El enlace dice «${u.scheme}», y hace falta «otpauth».');
  }
  // `totp` es el único tipo implementado. `hotp` existe en el formato y aquí no
  // tiene sentido: HOTP necesita un contador, y sin servidor que lo incremente el
  // código 2 nunca llegaría. Decirlo es mejor que aceptarlo y mostrar siempre 1.
  final tipo = u.host.toLowerCase();
  if (tipo != 'totp') {
    throw ErrorOtpauth(
      tipo.isEmpty
          ? 'El enlace no dice de qué tipo es. Solo hay «totp».'
          : 'El tipo «$tipo» no está soportado; solo «totp».',
    );
  }

  final q = u.queryParameters;

  final semillaTexto = q['secret'];
  if (semillaTexto == null || semillaTexto.isEmpty) {
    throw const ErrorOtpauth('El enlace no trae la clave.');
  }

  Uint8List semilla;
  try {
    semilla = base32Decodificar(semillaTexto);
  } on FormatException catch (e) {
    throw ErrorOtpauth('La clave no se entiende (${e.message}).');
  }
  if (semilla.isEmpty) {
    throw const ErrorOtpauth('La clave viene vacía.');
  }

  // El issuer de la query manda sobre el del path. Ver la nota 1 del doc.
  final partes = _partirPath(u.path);
  final issuerQuery = (q['issuer'] ?? '').trim();
  final emisor = issuerQuery.isNotEmpty ? issuerQuery : partes.emisor;
  final etiqueta =
      (q['label'] ?? '').trim().isNotEmpty ? q['label']!.trim() : partes.etiqueta;

  final digitos = _entero(q['digits'], 6, min: 6, max: 10);
  if (digitos == null) {
    throw const ErrorOtpauth('El número de dígitos del enlace no es válido.');
  }

  final periodo = _entero(q['period'], 30, min: 5, max: 300);
  if (periodo == null) {
    throw const ErrorOtpauth('El periodo del enlace no es válido.');
  }

  final algoritmo = AlgoritmoTotp.desdeNombre(q['algorithm']);
  if (q['algorithm'] != null &&
      q['algorithm']!.isNotEmpty &&
      algoritmo == null) {
    throw ErrorOtpauth('El algoritmo «${q['algorithm']}» no se reconoce.');
  }

  return CuentaQr(
    emisor: emisor,
    etiqueta: etiqueta,
    semilla: semilla,
    // Sin `algorithm=`, SHA-1. Es lo que dice la RFC y lo que manda casi todo.
    algoritmo: algoritmo ?? AlgoritmoTotp.sha1,
    digitos: digitos,
    periodo: periodo,
  );
}

/// Compone un `otpauth://`.
///
/// No es decorativo: es lo que hace el test del round-trip de la bóveda, y lo
/// que usaría una someday función de «exportar la cuenta como QR». Además
/// obligan a que el modelo tenga `toJson`/`fromJson` que de verdad son
/// inversos, que no es algo que se vea leyendo el otro sentido.
String escribirOtpauth(CuentaQr c) {
  final etiqueta = c.emisor.isEmpty
      ? Uri.encodeComponent(c.etiqueta)
      : Uri.encodeComponent('${c.emisor}:${c.etiqueta}');
  final parametros = <String, String>{
    'secret': base32Codificar(c.semilla),
    // Se escriben siempre, aunque sean los valores por defecto. Un QR que dice
    // lo que es no depende del que lo lee saber los defaults.
    'issuer': c.emisor,
    'algorithm': c.algoritmo.nombre,
    'digits': '${c.digitos}',
    'period': '${c.periodo}',
  };
  return Uri(
    scheme: 'otpauth',
    host: 'totp',
    path: '/$etiqueta',
    queryParameters: parametros,
  ).toString();
}

/// Separa el path en emisor y etiqueta.
///
/// ## Por qué se decodifica **antes** de cortar
/// El `:` del separador llega como `%3A` en el path, porque el emisor y la
/// etiqueta se mandan como un solo componente codificado. `Uri.path` devuelve el
/// path **sin decodificar**, así que buscar `:` en crudo no encuentra nada: el
/// emisor salía vacío y la etiqueta entera «GitHub:ana». Decodificar primero y
/// cortar después es lo que lo arregla.
///
/// Se corta por el **primer** `:` porque las etiquetas legítimas los llevan
/// («correo: ana@ejemplo.com»): cortar por el último haría que el emisor fuera
/// «Trabajo:correo».
///
/// `+` en el path es un `+`, no un espacio: los espacios van como `%20`. Por eso
/// es `decodeComponent` y no `decode`.
({String emisor, String etiqueta}) _partirPath(String path) {
  var s = path.startsWith('/') ? path.substring(1) : path;
  try {
    s = Uri.decodeComponent(s);
  } on FormatException {
    // Un '%' suelto no es un error que merezca tirar el QR entero: se queda lo
    // que haya y se sigue.
  }

  final i = s.indexOf(':');
  if (i <= 0) return (emisor: '', etiqueta: s.trim());

  // Del separador solo sobrevive el `:`; los espacios y tabuladores que le
  // siguen son decoración del formato y se van.
  return (
    emisor: s.substring(0, i).trim(),
    etiqueta: s.substring(i + 1).trim(),
  );
}

/// Un entero de la query con tope, o `null` si no lo es.
///
/// Un `period=abc` o un `period=0` no son «el valor por defecto»: son un enlace
/// roto, y aceptarlos haría que la cuenta no generara nunca un código válido
/// sin decir nada. Devolver `null` deja que el llamante lo explique.
int? _entero(String? texto, int porDefecto, {required int min, required int max}) {
  if (texto == null || texto.isEmpty) return porDefecto;
  final n = int.tryParse(texto.trim());
  if (n == null || n < min || n > max) return null;
  return n;
}