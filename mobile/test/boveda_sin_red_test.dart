// Quien puede ver una semilla no puede abrir un socket.
//
// ## Qué invariante es esta
// `docs/decisiones/003-authenticador.md` dice «lo íntimo no sale», y
// `AGENTS.md` §1 lo lista entre las invariantes vigentes: *«Audio, fotogramas y
// rostros no van a terceros sin permiso explícito y medible»*. Aquí lo íntimo son
// las **semillas TOTP** de cuentas reales, y la promesa es que no salen por la
// red.
//
// ## Por qué el guardarraíl y no un test de comportamiento
// Porque hasta ahora la promesa era **una frase buena**: nadie la comprobaba. Se
// verificó a mano —la bóveda no importa `dio`, el bridge no tiene ni una
// coincidencia de «bóveda» entre sus 47 endpoints, la pantalla de claves no
// llama al repositorio— y todo era verdad. Pero nada lo iba a volver a comprobar,
// y mañana un import basta: `import 'package:dio/dio.dart'` en `boveda.dart` y los
// 393 tests siguen verdes.
//
// Es A-016 con otro disfraz, y también lo de `AGENTS.md` §2: *«un invariante que
// nadie ejecuta no es un invariante; es una intención»*. El arreglo de A-119
// —dejar de firmar en debug— no impidió que esto volviera a ser cierto; solo lo
// hizo el check.
//
// ## Por qué leer el código y no ejecutarlo
// Un test de comportamiento necesita una red real o un doble, y un doble de red
// esconde justo lo que se quiere cazar: que la bóveda **no** USE la red. Aquí lo
// que importa no es lo que hace con una respuesta, es **qué tiene importado**.
//
// ## El límite que se está dibujando
// Los ficheros de esta lista son los que **pueden ver una semilla**. Todos ellos,
// juntos, no pueden abrir un socket. Ese es el contrato: quien tiene el secreto no
// tiene la tubería.
//
// ## Lo que este guardarraíl NO cubre, y conviene decirlo
// La **copia de seguridad** sí sale del dispositivo, y es a propósito: el sobre va
// cifrado con Argon2id + AES-256-GCM y el destino lo elige la persona en un
// diálogo del sistema (`CopiaNativa.kt`), donde Drive está entre las opciones. No
// es un socket —es SAF—, así que este test pasa. Y está bien que pase: la copia es
// una acción **deliberada y confirmada** de quien la hace, no una fuga silenciosa.
// Lo que este test prohibits es lo otro: que las semillas se vayan **sin que nadie
// lo pidiera**.
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// Los ficheros que pueden llegar a ver una semilla.
const _conSemilla = <String>[
  'lib/core/auth',
  'lib/presentation/pages/claves_page.dart',
  'lib/presentation/pages/escaner_qr.dart',
  'lib/presentation/providers/boveda_providers.dart',
];

/// Paquetes que son, o contienen, un cliente de red.
///
/// Se listan por **paquete**, no por símbolo, porque un import es lo único que
/// hace falta para poder hacer red. Si mañana sale un cliente nuevo que no esté en
/// esta lista, esto no lo ve — y por eso la lista dice «añádalo aquí», no «ya
/// está todo».
const _paquetesDeRed = <String>[
  'package:dio/',
  'package:http/',
  'package:web_socket_channel/',
  'package:socket_io_client/',
  'package:grpc/',
  'package:shelf/',
];

/// Símbolos de `dart:io` que abren una conexión.
///
/// `dart:io` **sí** se importa en la bóveda —para leer y escribir ficheros— y por
/// eso no puede prohibirse el import entero. Lo que no puede aparecer es la
/// tubería: un fichero puede tener `File` y `Directory` y seguir sin poder hacer
/// red, que es exactamente lo que se quiere.
const _simbolosDeRed = <String>[
  'HttpClient',
  'HttpClientRequest',
  'HttpClientResponse',
  'HttpServer',
  'WebSocket',
  'RawSocket',
  'SecureSocket',
  'InternetAddress',
  'openConnection',
  'Uri.http',
  'Uri.https',
];

/// Los ficheros Dart que se revisan, en los sitios donde puede haber una semilla.
List<File> _dartConSemilla() {
  final raiz = Directory('lib');
  if (!raiz.existsSync()) {
    fail('no encuentro lib/ desde ${Directory.current.path}: el guardarraíl '
        'tiene que correr desde mobile/, o no está comprobando nada');
  }
  final out = <File>[];
  for (final donde in _conSemilla) {
    final d = File(donde);
    if (d.existsSync()) {
      out.add(d);
      continue;
    }
    final dir = Directory(donde);
    if (!dir.existsSync()) {
      fail('la ruta de la lista $donde ya no existe. Si se movió el fichero, '
          'actualiza _conSemilla: dejarla daría un guardarraíl que no mira nada');
    }
    out.addAll(dir
        .listSync(recursive: true)
        .whereType<File>()
        .where((f) => f.path.endsWith('.dart'))
        .where((f) => !f.path.contains('generated')));
  }
  out.sort((a, b) => a.path.compareTo(b.path));
  return out;
}

void main() {
  group('la bóveda no tiene tubería hacia la red', () {
    test('la lista de ficheros con semilla no está vacía', () {
      // Un guardarraíl que no mira nada pasa siempre, y por eso empieza
      // mirando que mire algo. Sin esta línea, un rename que dejara
      // `_conSemilla` llena de rutas muertas seguiría en verde.
      final ficheros = _dartConSemilla();
      expect(ficheros, isNotEmpty);
      // Se comparan las rutas exactas, no un `startsWith` suelto: con los
      // prefijos, un fichero renombrado a `boveda_v2.dart` pasaba el test y el
      // guardarraíl se quedaba mirando el hueco sin decirlo.
      final rutas = ficheros.map((f) => f.path).toList();
      expect(rutas, contains('lib/core/auth/boveda.dart'),
          reason: 'la bóveda tiene que estar en la lista; si se renombró, '
              'actualiza _conSemilla o este guardarraíl no vigila el secreto');
      // Y que la lista no se haya quedado en dos pantallas sin el almacén: el
      // fichero que **escribe** en el Keystore es tan importante como el que
      // calcula el código.
      expect(rutas.any((r) => r.startsWith('lib/core/auth/')), isTrue);
    });

    test('ninguno importa un cliente de red', () {
      final operating = <String>[];
      for (final f in _dartConSemilla()) {
        final lineas = f.readAsLinesSync();
        for (var i = 0; i < lineas.length; i++) {
          final linea = lineas[i];
          if (!linea.contains('import')) continue;
          for (final paquete in _paquetesDeRed) {
            if (linea.contains(paquete)) {
             operating.add('${f.path}:${i + 1} importa $paquete');
            }
          }
        }
      }
      expect(operating, isEmpty,
          reason: 'un fichero que ve una semilla no puede importar un cliente de '
              'red. Si de verdad necesita uno, repasa la invariante antes de '
              'quitar esto:\n  ${operating.join('\n  ')}');
    });

    test('ninguno nombra un símbolo que abra una conexión', () {
      final offen = <String>[];
      for (final f in _dartConSemilla()) {
        final lineas = f.readAsLinesSync();
        for (var i = 0; i < lineas.length; i++) {
          for (final simbolo in _simbolosDeRed) {
            if (lineas[i].contains(simbolo)) {
              offen.add('${f.path}:${i + 1} nombra $simbolo');
            }
          }
        }
      }
      expect(offen, isEmpty,
          reason: 'dart:io sí se puede importar para ficheros; lo que no puede '
              'aparecer es la tubería:\n  ${offen.join('\n  ')}');
    });
  });

  group('y ni un log que se la lleve', () {
    test('nada imprime la semilla ni el otpauth', () {
      // Un `print` en el camino de añadir una cuenta se lleva la semilla al
      // logcat, que es legible por cualquier app del sistema y por `adb logcat`.
      // Es la fuga más tonta y la más difícil de notar: el log se escribe, la app
      // funciona y no sale ningún error.
      final impresiones = <String>[];
      // Regex y no subcadena, y hay una razón concreta: **`log(` casa con
      // `diálogo(`**. Una versión de este guardarraíl que buscaba la subcadena
      // marcaba siete falsos positivos en `claves_page.dart` — todos «diálogo» —
      // y un guardarraíl rojo se apaga, que es peor que no tenerlo.
      final llamadas = <RegExp>[
        RegExp(r'\bprint\s*\('),
        RegExp(r'\bdebugPrint\s*\('),
        RegExp(r'\bdeveloper\s*\.\s*log\b'),
        RegExp(r'\b(?:stdout|stderr)\s*\.\s*writeln'),
        RegExp(r'\blog\s*\('),
      ];
      for (final f in _dartConSemilla()) {
        final lineas = f.readAsLinesSync();
        for (var i = 0; i < lineas.length; i++) {
          final linea = lineas[i];
          // Los comentarios hablan del problema y no son el problema. Sin esto,
          // este mismo fichero —que nombra `print(` y `log(` al explicarlos—
          // fallaría su propio guardarraíl.
          if (linea.trimLeft().startsWith('//')) continue;
          for (final marca in llamadas) {
            if (marca.hasMatch(linea)) {
              impresiones.add('${f.path}:${i + 1} → ${marca.pattern}');
            }
          }
        }
      }
      expect(impresiones, isEmpty,
          reason: 'nada en el camino de la semilla escribe en el log:\n  '
              '${impresiones.join('\n  ')}');
    });
  });
}