// El puente entre lo que el bridge escribe y lo que la persona lee.
//
// El bridge dedica bastante esfuerzo a redactar el motivo de cada rechazo: un
// alias inválido viene con las reglas del patrón, un 409 del verificador dice
// exactamente qué declarar. Todo eso se escribía para leerse, y hasta aquí no
// llegaba nunca: las pantallas hacían `'$e'` sobre una `DioException`, cuyo
// `toString()` tiene el tipo, la URI y el código, pero no el body.
//
// Estos tests fijan el contrato de esa traducción. Si alguien la rompe, el
// síntoma es silencioso y malo: volverían los `Status code 400` a secas.
import 'package:flutter_test/flutter_test.dart';

import 'package:dio/dio.dart';

import 'package:aegis_console/core/network/errores.dart';

void main() {
  group('mensajeDeError', () {
    DioException con(int codigo, Object? body) => DioException(
          requestOptions: RequestOptions(path: '/algo'),
          response: Response<Object?>(
            requestOptions: RequestOptions(path: '/algo'),
            statusCode: codigo,
            data: body,
          ),
        );

    test('un 400 con detail devuelve el detail tal cual', () {
      const motivo =
          "alias inválido: 'Mal Alias'. Se permiten minúsculas, dígitos, punto, guion y guion bajo";
      final e = con(400, {'detail': motivo});
      expect(mensajeDeError(e), motivo);
    });

    test('el detalle gana al mensaje generico de Dio', () {
      // Sin esto, el trabajo de redactar el motivo se pierde: el `toString()`
      // de la excepción ya estaba disponible, y es inútil.
      final e = con(400, {'detail': 'el verificador no cabe'});
      expect(mensajeDeError(e), isNot(contains('400')));
      expect(mensajeDeError(e), isNot(contains('DioException')));
    });

    test('un 422 de validacion se aplana a texto legible', () {
      // pydantic manda una lista de objetos, y `'$e'` de una lista de mapas es
      // peor que no decir nada. Esto es lo que ve quien deja el contenido
      // vacío en el editor de la ficha.
      final e = con(422, {
        'detail': [
          {
            'loc': ['body', 'contenido'],
            'msg': 'String should have at least 1 character',
            'type': 'string_too_short',
          },
          {
            'loc': ['body', 'contenido'],
            'msg': 'String should have at most 20000 characters',
            'type': 'string_too_long',
          },
        ],
      });
      final m = mensajeDeError(e);
      expect(m, contains('at least 1 character'));
      expect(m, contains('at most 20000 characters'));
      expect(m, isNot(contains('{')), reason: 'no debeVerse la estructura cruda');
    });

    test('el 422 nombra el campo que fallo', () {
      final e = con(422, {
        'detail': [
          {'loc': ['body', 'contenido'], 'msg': 'too short'},
        ],
      });
      expect(mensajeDeError(e), 'contenido: too short');
    });

    test('sin detail pero con codigo, el codigo se dice', () {
      // El `toString()` de una DioException sin mensaje es
      // «DioException [unknown]: null», que no dice nada de nada. Con el
      // `detail` ausente pero el código presente, al menos se puede decir que
      // fue el puente y no la red.
      final e = con(500, null);
      expect(mensajeDeError(e), contains('500'));
      expect(mensajeDeError(e), isNot(contains('null')));
    });

    test('un error que no es de red pasa tal cual', () {
      // Sin respuesta HTTP no hay nada que traducir: un timeout o un fallo de
      // DNS solo tienen su propio mensaje, y es mejor que el nuestro.
      expect(mensajeDeError('se rompió'), 'se rompió');
    });

    test('un detail vacio cae al mensaje con el codigo', () {
      final e = con(400, {'detail': '   '});
      expect(mensajeDeError(e), contains('400'));
    });

    test('un cuerpo que no es un mapa no rompe nada', () {
      // El body puede ser texto plano si algo del otro lado no es el bridge.
      final e = con(500, 'texto plano');
      expect(mensajeDeError(e), contains('500'));
    });
  });

  group('esSinLlave', () {
    DioException con(int codigo) => DioException(
          requestOptions: RequestOptions(path: '/algo'),
          response: Response<Object?>(
            requestOptions: RequestOptions(path: '/algo'),
            statusCode: codigo,
            data: null,
          ),
        );

    test('un 401 es falta de llave', () {
      expect(esSinLlave(con(401)), isTrue);
    });

    test('un 404 no es falta de llave', () {
      expect(esSinLlave(con(404)), isFalse);
    });

    test('un 409 no es falta de llave', () {
      expect(esSinLlave(con(409)), isFalse);
    });
  });

  group('esFaltaVerificador', () {
    DioException verificador() => DioException(
          requestOptions: RequestOptions(path: '/autonomy/x'),
          response: Response<Object?>(
            requestOptions: RequestOptions(path: '/autonomy/x'),
            statusCode: 409,
            data: {
              'detail':
                  "'x' no tiene verificador declarado en app/projects.py, así que no hay "
                  'contra qué comprobar que el trabajo quedó bien. Decláralo antes de '
                  'darle permiso de escritura.'
            },
          ),
        );

    test('el 409 del verificador se reconoce', () {
      expect(esFaltaVerificador(verificador()), isTrue,
          reason: 'el interruptor de escritura parece roto si no se distingue '
              'este caso: la solución es declarar el verificador, no esperar');
    });

    test('otro 409 no se confunde con este', () {
      final otro = DioException(
        requestOptions: RequestOptions(path: '/x'),
        response: Response<Object?>(
          requestOptions: RequestOptions(path: '/x'),
          statusCode: 409,
          data: {'detail': 'conflicto de otra cosa'},
        ),
      );
      expect(esFaltaVerificador(otro), isFalse);
    });
  });
}