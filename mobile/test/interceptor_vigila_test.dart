// Que el interceptor que resuelve el bridge siga teniendo efecto.
//
// ## Por qué este test y no confiar en el análisis
// El interceptor funciona reescribiendo `baseUrl`, y eso **no** funciona si
// alguna llamada pide una URL absoluta: en Dio la ruta absoluta gana, y el
// discovery se queda sin hacer nada —sin error, sin aviso— hasta que la IP
// compilada muera, que es justo cuando el discovery era la solución.
// `test/base_dio_test.dart` lo demuestra con dos líneas.
//
// Por eso no basta con que el código compile: una llamada escrita como
// `_dio.get('${config.httpBase}/health')` compila perfectamente y rompe el
// discovery en silencio. Esto lo vigila.
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('ninguna llamada del repositorio lleva URL absoluta', () async {
    // Se lee el propio fichero, no el comportamiento: un test que ejecutase las
    // llamadas necesitaría un bridge de verdad, y un test que no puede correr
    // cuando falta el bridge es un test que no se ejecuta justo cuando importa.
    final fuente =
        await File('lib/data/repositories/agent_repository_impl.dart').readAsString();

    final absolutas = RegExp(
      r"_dio\.\w+\(\s*'https?://",
    ).allMatches(fuente).map((m) => m.group(0)).toList();

    expect(
      absolutas,
      isEmpty,
      reason: 'una URL absoluta en una llamada anula el interceptor del '
          'discovery. Deja solo la ruta: el destino lo pone el interceptor.',
    );
  });

  test('la descarga pide el DESTINO del APK, no su nombre de fichero', () async {
    // El bridge compone el nombre del fichero con su perfil
    // (`app-release-telefono.apk`). Pedir `/apk/app-release-telefono.apk`
    // devuelve un 404 con «destino desconocido»: un mensaje sobre un parámetro
    // mal escrito donde lo que se quería era preguntar la versión, y la app se
    // queda con «el bridge no tiene un APK» sin decir por qué.
    final fuente =
        await File('lib/data/repositories/agent_repository_impl.dart').readAsString();

    final destinos = RegExp(r"/apk/([a-zA-Z0-9._-]+)").allMatches(fuente).map((m) => m.group(1));

    expect(destinos.toSet(), {'telefono'},
        reason: 'el único destino válido del bridge es `telefono`');
    expect(fuente, isNot(contains('apk/app-release')),
        reason: 'el nombre del fichero lo compone el bridge');
  });
}