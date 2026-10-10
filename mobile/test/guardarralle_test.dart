// La clase de fallo, no el fallo.
//
// ## Qué pasó
// Los dos botones principales de la pantalla de claves no hacían nada. La
// causa era `alEscanear: () => _escanear`, que devuelve una **referencia** al
// método en vez de llamarlo, y eso es asignable a `void Function()` porque en
// Dart el tipo de retorno `void` descarta cualquier valor.
//
// Dos cosas tenían que haberlo parado y ninguna lo hizo:
// - `flutter analyze`, porque `void` acepta cualquier valor de retorno.
// - Los tests, porque solo comprobaban que el botón **existía**.
//
// ## Por qué un guardarraíl sobre el código y no un test más
// Porque el arreglo de verdad es el **tipo**: `AccionAegis` hace que
// `() => _escanear` no compile. El guardarraíl de aquí es la red por debajo de
// esa red, para cuando alguien escriba un `VoidCallback` nuevo y
// reintroduzca el hueco por otra puerta.
//
// ## Por qué no es una regla del analizador
// Añadir una necesita un paquete y una configuración en `analysis_options.yaml`
// que nadie va a mirar después. Un test que lee el código y falla está en el
// sitio donde ya se mira: `flutter test`.
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// Los ficheros Dart que se revisan.
///
/// No `lib/` entero: los `generated*.dart` de Flutter vienen de la herramienta
/// y no son código de nadie.
List<File> _dartDe({String? subdirectorio}) {
  final raiz = Directory(subdirectorio ?? 'lib');
  return raiz
      .listSync(recursive: true)
      .whereType<File>()
      .where((f) => f.path.endsWith('.dart'))
      .where((f) => !f.path.contains('generated'))
      .toList()
    ..sort((a, b) => a.path.compareTo(b.path));
}

/// Quita los comentarios, para no encontrar el patrón en la explicación del
/// propio arreglo.
///
/// Sin esto, un comentario que escribe `() => _metodo` —como el de
/// `acciones.dart`— haría fallar el guardarraíl por el motivo equivocado, que
/// es peor que no tenerlo: entrena a ignorar el aviso.
String _sinComentarios(String fuente) => fuente
    .split('\n')
    .where((l) {
      final t = l.trimLeft();
      return !(t.startsWith('//') || t.startsWith('*') || t.startsWith('/*'));
    })
    .join('\n');

void main() {
  group('nadie escribe un método sin llamarlo por accidente', () {
    test('no hay `() => _algo,` donde _algo no lleva paréntesis', () {
      final culpables = <String>[];
      for (final f in _dartDe()) {
        final limpio = _sinComentarios(f.readAsStringSync());
        // `algo: () => _metodo,` — la coma al final es lo que delata que es la
        // forma de un valor de argumento, no una llamada en otra parte.
        final re = RegExp(r'=>\s*(_[A-Za-z][A-Za-z0-9]*)\s*,\s*$', multiLine: true);
        for (final m in re.allMatches(limpio)) {
          culpables.add('${f.path}: ${m.group(1)} — devuelve una referencia, '
              'no la llama; escribe ${m.group(1)}()');
        }
      }
      expect(culpables, isEmpty,
          reason: 'Un método devuelto sin llamar no hace nada y el analizador '
              'no lo ve:\n  ${culpables.join('\n  ')}');
    });

    test('no hay `() => _metodo,` con dos espacios ni tabulador', () {
      // La misma regla con la otra forma en que se escribe: `() =>  _metodo`.
      final culpables = <String>[];
      for (final f in _dartDe()) {
        final limpio = _sinComentarios(f.readAsStringSync());
        final re = RegExp(r'=>\s{2,}(_[A-Za-z][A-Za-z0-9]*)\s*,\s*$',
            multiLine: true);
        for (final m in re.allMatches(limpio)) {
          culpables.add('${f.path}: ${m.group(1)}');
        }
      }
      expect(culpables, isEmpty,
          reason: 'mismo fallo, otra forma:\n  ${culpables.join('\n  ')}');
    });
  });

  group('el arreglo está puesto y no se puede deshacer sin que se note', () {
    test('las acciones usan el tipo que no admite el fallo', () {
      // Si alguien vuelve a `VoidCallback`, este test lo dice aunque el
      // guardarraíl de arriba no llegue a encontrar ninguna llamada rota: el
      // hueco vuelve a existir aunque hoy no lo rellene nadie.
      final fuente = File('lib/presentation/pages/claves_page.dart')
          .readAsStringSync();
      expect(fuente.contains('final VoidCallback alEscanear'), isFalse,
          reason: 'VoidCallback admite devolver un método sin llamarlo');
      expect(fuente.contains('final VoidCallback alCopiar'), isFalse,
          reason: 'igual que alEscanear');
    });

    test('AccionAegis es un Future, que es lo que la hace inútil de romper', () {
      final fuente = File('lib/core/widgets/acciones.dart').readAsStringSync();
      expect(fuente.contains('typedef AccionAegis = Future<void> Function()'),
          isTrue);
    });
  });

  group('la app no pide permisos que no necesita', () {
    test('el registro de permisos cuadra con lo que hay en el manifest', () {
      // ## Por qué este test existe
      // Un registro de permisos se pudre solo: alguien añade un permiso al
      // manifest —porque una función nueva lo necesita— y no lo añade al
      // registro, y el asistente deja de pedirlo **sin que nada se entere**.
      // Es el mismo problema que el sello que no cuadra con el APK: una puerta
      // que comprueba una cosa y responde por otra.
      final manifest = File(
        'android/app/src/main/AndroidManifest.xml',
      ).readAsStringSync();
      final declarados = RegExp(r'android:name="android\.permission\.([A-Z_]+)"')
          .allMatches(manifest)
          .map((m) => m.group(1)!)
          .toSet();

      // Lo que Aegis necesita en runtime. Los otros del manifest no se piden:
      // `INTERNET` no es un permiso runtime, y `REQUEST_INSTALL_PACKAGES` es
      // acceso especial de Android sin diálogo posible — se comprueba aparte.
      final runtime = declarados.where((p) => !const {
        'INTERNET',
        'REQUEST_INSTALL_PACKAGES',
        'CAMERA', // lo pide `mobile_scanner` al abrir el escáner
      }.contains(p));

      expect(runtime, isNotEmpty, reason: 'no queda ningún permiso que pedir');
      for (final p in runtime) {
        expect(File('lib/core/permisos.dart').readAsStringSync(),
            contains(p),
            reason: 'el permiso $p está en el manifest y no en el registro: '
                'la app no lo pedirá y nadie se enterará');
      }
    });

    test('la cámara no se pide en el primer arranque', () {
      // `mobile_scanner` la pide solo, al abrir el escáner, y con contexto:
      // la persona ya está apuntando a un QR. Meterla en el registro la
      // preguntaría **al arrancar**, que es lo que este repo ya escribió una
      // vez que no hay que hacer.
      //
      // Se mira la **lista** (`PermisoApp(...)`), no el fichero entero: el
      // nombre `CAMERA` aparece en el comentario que explica por qué no está,
      // y un test que lo buscara en el texto tendría que borrar ese comentario,
      // que es la mitad del motivo.
      final fuente = File('lib/core/permisos.dart').readAsStringSync();
      final lista = fuente
          .substring(fuente.indexOf('permisosDePrimeraVez'))
          .split('PermisoApp(')
          .where((p) => p.contains('id:'))
          .toList();
      expect(lista, isNotEmpty, reason: 'la lista del registro está vacía');
      for (final entrada in lista) {
        expect(entrada.contains('CAMERA'), isFalse,
            reason: 'la cámara no debe estar en el registro de primera vez: '
                'la pide mobile_scanner al abrir el escáner, con contexto');
      }
    });
  });
}