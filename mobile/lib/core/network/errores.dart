/// Traduce una excepción de red a un mensaje que se pueda leer.
///
/// ## Por qué existe esto
/// El bridge escribe sus errores con cuidado: un `alias` inválido llega como
/// «alias inválido: 'Mal Alias'. Se permiten minúsculas, dígitos, punto, guion
/// y guion bajo», y un 409 del verificador llega diciendo exactamente qué
/// declarar. Todo eso se escribía para que lo **leyera una persona**.
///
/// Y hasta ahora no llegaba. Las pantallas hacen `'$e'` sobre una
/// `DioException`, y su `toString()` lleva el tipo, la URI y el código, pero no
/// el cuerpo de la respuesta. El resultado era que un usuario que escribía un
/// alias con mayúsculas veía `DioException [bad response]: Status code 400` y
/// nada más. El trabajo de escribir el motivo se quedaba en el log del bridge.
///
/// ## Por qué una función y no excepciones de dominio
/// El repositorio devuelve `Future<T>` y deja volar el error; una jerarquía de
/// excepciones obligaría a revisar las trece pantallas que ya hacen `catch (e)`
/// y `'$e'`, y el cambio sería invisible para el usuario. Aquí se traduce en un
/// solo punto —el que llama— sin tocar ninguna pantalla que no quiera tocar.
///
/// ## Los tres casos que importan
/// - **400/404/409 con `detail`**: es texto escrito para leerse, y es lo que
///   se devuelve tal cual.
/// - **422 de validación**: pydantic manda una *lista* de objetos con `loc` y
///   `msg`, no un texto. Sin aplanarla, `'$e'` de una lista de mapas sería peor
///   que el `'$e'` de la excepción.
/// - **401**: tiene su propio texto porque es el único fallo cuya solución la
///   tiene que hacer quien la ve (recompilar el APK con la clave nueva).
library;

import 'package:dio/dio.dart';

/// Devuelve el mensaje que la app debe enseñar de [e].
///
/// Si el body trae algo legible, eso gana. Y si no lo trae pero sí se sabe el
/// código, el mensaje lo dice: el `toString()` de una `DioException` construida
/// a mano es `DioException [unknown]: null`, que no dice ni qué pasó ni dónde.
/// Añadir el código es la diferencia entre «algo falló» y «el bridge devolvió
/// 500».
///
/// Cuando no hay ni body ni código —un timeout, un fallo de DNS— devuelve [e]
/// tal cual, que es lo único que hay.
String mensajeDeError(Object e) {
  final detalle = _detailDe(e);
  if (detalle != null && detalle.isNotEmpty) {
    return detalle;
  }
  final codigo = _responseDe(e)?.statusCode;
  if (codigo != null) {
    return 'El puente devolvió $codigo sin explicación.';
  }
  return '$e';
}

/// ¿Este error es «no hay llave»?
///
/// Vale para pintar el aviso de reinstalar el APK, que es lo único que lo
/// arregla: rotar la clave en el bridge sin recompilar deja el móvil fuera, y
/// sin esta pregunta la app lo cuenta como un problema de red más.
bool esSinLlave(Object e) {
  final r = _responseDe(e);
  return r?.statusCode == 401;
}

/// ¿Este error es «aún no puedes escribir aquí porque no hay verificador»?
///
/// El 409 de `POST /autonomy/{alias}`. Es su propio caso porque la pantalla de
/// proyectos tiene un interruptor que parece roto cuando en realidad el bridge
/// está pidiendo algo concreto que hay que declarar antes.
bool esFaltaVerificador(Object e) {
  final r = _responseDe(e);
  if (r?.statusCode != 409) {
    return false;
  }
  return _detailDe(e)?.contains('verificador') ?? false;
}

Response<dynamic>? _responseDe(Object e) {
  if (e is DioException) {
    return e.response;
  }
  return null;
}

/// El `detail` del body, aplanado a texto legible.
String? _detailDe(Object e) {
  final data = _responseDe(e)?.data;
  if (data is! Map) {
    return null;
  }
  final detail = data['detail'];
  if (detail is String) {
    return detail.trim();
  }
  // 422 de pydantic: `[{loc: [...], msg: "...", type: "..."}, ...]`. Se
  // recoge solo el `msg`, que es la parte en español que escribió el modelo,
  // y se añade el campo de `loc` para que se sepa *qué* campo lo pidió.
  if (detail is List) {
    final partes = <String>[];
    for (final item in detail) {
      if (item is Map) {
        final msg = item['msg'];
        if (msg is String && msg.isNotEmpty) {
          final loc = item['loc'];
          final campo = loc is List && loc.isNotEmpty ? '${loc.last}: ' : '';
          partes.add('$campo$msg');
        }
      }
    }
    if (partes.isNotEmpty) {
      return partes.join('\n');
    }
  }
  return null;
}