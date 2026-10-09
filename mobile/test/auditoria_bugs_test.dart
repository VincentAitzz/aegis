// Los seis fallos que la auditoría encontró, fijados uno a uno.
//
// ## Por qué este archivo existe
// Los seis estaban en código que compilaba, pasaba `flutter analyze` y estaba
// cubierto por tests — y ninguno lo detectó. La razón es la misma en todos: cada
// uno era un **estado que nadie miraba**. Un `try` que no cubre la excepción
// real, un flag que se pone antes de decidir, un `30` escrito a fuego.
//
// Un test que fija el síntoma no sirve si no fija el **motivo**. Por eso cada
// bloque dice qué se rompió y por qué el fallo era invisible.
import 'dart:convert';
import 'dart:io';

import 'package:aegis_console/core/auth/boveda.dart';
import 'package:aegis_console/core/auth/copia.dart';
import 'package:aegis_console/core/auth/fichero_copia.dart';
import 'package:aegis_console/core/auth/otpauth.dart';
import 'package:aegis_console/core/auth/totp.dart';
import 'package:aegis_console/presentation/pages/escaner_qr.dart';
import 'package:aegis_console/presentation/providers/boveda_providers.dart';
import 'package:aegis_console/presentation/widgets/anillo_cuenta.dart';
import 'package:fake_async/fake_async.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

/// Un `FlutterSecureStorage` que falla como falla el de verdad.
///
/// El de verdad lanza [PlatformException] —lo documenta el propio paquete— cuando
/// la clave se invalida: restauración del dispositivo, desinstalación, Keystore
/// bloqueado. El doble devuelve `null` como si nada, y por eso el `try` que
/// cubría el `jsonDecode` parecía suficiente.
class StorageQueFalla implements FlutterSecureStorage {
  StorageQueFalla(this.error);
  final Object error;

  @override
  dynamic noSuchMethod(Invocation invocation) {
    if (invocation.memberName == Symbol('read')) throw error;
    return super.noSuchMethod(invocation);
  }
}

void main() {
  group('B1 — el error del Keystore no puede dejar la pantalla en carga', () {
    // El fallo: `leer()` solo capturaba `FormatException`, y el futuro de
    // `build()` se rechazaba. Medido en Riverpod 3: eso deja la pantalla en
    // `loading` para siempre —ni error ni fallo— y un JSON malformado no pasa
    // nunca mientras que un Keystore que falla, sí.
    for (final (nombre, error) in <(String, Object)>[
      ('PlatformException', PlatformException(code: 'StorageError')),
      ('MissingPluginException', MissingPluginException('sin plugin')),
    ]) {
      test('$nombre devuelve una bóveda dañada, no revienta', () async {
        final almacen = BovedaKeystore(storage: StorageQueFalla(error));
        final b = await almacen.leer();
        expect(b.corrupta, isTrue,
            reason: 'con $nombre la bóveda no debe parecer vacía: '
                '«no tengo nada» y «no lo pude leer» son cosas distintas');
        expect(b.cuentas, isEmpty);
      });

      test('$nombre impide que se escriba encima', () async {
        // El otro mitad de lo mismo: si se declara dañada pero se deja
        // escribir, un «añadir cuenta» destruiría lo que quedara.
        final b = await BovedaKeystore(storage: StorageQueFalla(error)).leer();
        await expectLater(
          b.escribirEn(BovedaKeystore(storage: StorageQueFalla(error))),
          throwsA(isA<BovedaCorrupta>()),
        );
      });
    }

    test('un sobre ilegible sigue siendo dañado, no vacío', () async {
      final almacen = BovedaKeystore(
        storage: _StorageConTexto('esto no es json'),
      );
      expect((await almacen.leer()).corrupta, isTrue);
    });

    test('sin nada escrito, no está dañada', () async {
      // La otra mitad: si «no hay nada» fuera «dañado», la app diría que el
      // Keystore está roto en cada arranque limpio.
      final almacen = BovedaKeystore(storage: _StorageConTexto(null));
      final b = await almacen.leer();
      expect(b.corrupta, isFalse);
      expect(b.cuentas, isEmpty);
    });
  });

  group('B2 — un QR ajeno no puede dejar el escáner sordo', () {
    // El fallo: `_resuelto = true` se ponía ANTES de comprobar si el QR era de
    // autenticación. Con un QR de producto, el flag quedaba puesto, el
    // `continue` salía del bucle, y el `if (_resuelto) return` de la entrada
    // descartaba todos los detections siguientes. Un solo QR ajeno y había que
    // cerrar y reabrir la pantalla.
    test('un QR que no es de autenticación no se acepta', () {
      expect(valorDeQr('https://ejemplo.com/menu'), isNull);
      expect(valorDeQr('WIFI:S:miRed;T:WPA;P:clave;;'), isNull);
      expect(valorDeQr('BEGIN:VCARD\nFN:Ana\nEND:VCARD'), isNull);
      expect(valorDeQr('otpauthx://totp/X?secret=A'), isNull,
          reason: 'casi parece: un esquema parecido no es el nuestro');
    });

    test('nulo, vacío y espacios no son un QR', () {
      expect(valorDeQr(null), isNull);
      expect(valorDeQr(''), isNull);
      expect(valorDeQr('   '), isNull);
      expect(valorDeQr('\n\t '), isNull);
    });

    test('un otpauth:// de verdad se acepta, sin mirar más allá', () {
      // La función es un **filtro de candidatos**, no un validador: decide si el
      // texto se pasa al parser. Si validara, un `otpauth://` raro —que el
      // parser explica con un motivo— no se vería nunca.
      expect(valorDeQr('otpauth://totp/X?secret=JBSWY3DPEHPK3PXP'),
          'otpauth://totp/X?secret=JBSWY3DPEHPK3PXP');
      expect(valorDeQr('  otpauth://totp/X?secret=A  '),
          'otpauth://totp/X?secret=A',
          reason: 'el sobrante no es un enlace: lo devuelve limpio');
      expect(valorDeQr('OTPAUTH://totp/X?secret=A'), 'OTPAUTH://totp/X?secret=A',
          reason: 'el esquema no distingue mayúsculas y el parser lo acepta');
      // Uno con la semilla más rota del mundo: **pasa**. El parser dirá por qué.
      expect(valorDeQr('otpauth://totp/X?secret=!!!'), 'otpauth://totp/X?secret=!!!');
    });

    test('el filtro es el mismo para el escáner y para el portapapeles', () {
      // Se comprobaba dos veces por separado. Duplicar una decisión es como
      // acabar discrepando: una acepta algo que la otra rechaza y el usuario no
      // entiende por qué pegar funciona y escanear no.
      expect(valorDeQr('https://ejemplo.com'), isNull);
    });
  });

  group('B4 — el anillo dice los segundos de esa cuenta', () {
    // El fallo: `'(f * 30).ceil()'` con el 30 escrito a fuego. Una cuenta de 60
    // segundos (Outlook) ponía «30» siempre y se vaciaba a la mitad de lo que le
    // tocaba. El número era mentira y no había forma de notarlo, porque un
    // número fijo parece un contador.
    //
    // El primer intento de este test **calculaba los segundos en el test**, en
    // vez de mirar el widget. Pasaba con el bug puesto, porque no tocaba el
    // código. Un test que reimplementa la fórmula no la está probando.
    testWidgets('con periodo 60, la ventana entera enseña 60 y no 30',
        (t) async {
      await t.pumpWidget(const MaterialApp(
        home: Scaffold(body: AnilloCuentaAtras(fraccion: 1.0, periodo: 60)),
      ));
      expect(find.text('60'), findsOneWidget);
      expect(find.text('30'), findsNothing);
    });

    testWidgets('con periodo 30, enseña 30', (t) async {
      await t.pumpWidget(const MaterialApp(
        home: Scaffold(body: AnilloCuentaAtras(fraccion: 1.0, periodo: 30)),
      ));
      expect(find.text('30'), findsOneWidget);
    });

    testWidgets('a media ventana de 60 segundos, enseña 30; de 45, enseña 23',
        (t) async {
      await t.pumpWidget(const MaterialApp(
        home: Scaffold(body: AnilloCuentaAtras(fraccion: 0.5, periodo: 60)),
      ));
      expect(find.text('30'), findsOneWidget);

      await t.pumpWidget(const MaterialApp(
        home: Scaffold(body: AnilloCuentaAtras(fraccion: 0.5, periodo: 45)),
      ));
      expect(find.text('23'), findsOneWidget);
    });

    testWidgets('el valor por defecto es 30, que es lo que casi todas usan',
        (t) async {
      await t.pumpWidget(const MaterialApp(
        home: Scaffold(body: AnilloCuentaAtras(fraccion: 1.0)),
      ));
      expect(find.text('30'), findsOneWidget);
    });

    test('la cuenta le pasa su periodo al anillo', () {
      // El widget no puede saberlo: la cuenta es quien lo tiene. Y si la ficha
      // no se lo pasa, el anillo vuelve a 30 aunque el widget lo soporte.
      final cuenta = Cuenta(
        id: 'a1',
        emisor: 'Outlook',
        etiqueta: 'ana',
        semilla: base32Decodificar('JBSWY3DPEHPK3PXP'),
        algoritmo: AlgoritmoTotp.sha1,
        digitos: 6,
        periodo: 60,
        anadidaEn: DateTime.utc(2026),
      );
      final t = DateTime.utc(2026, 10, 5, 12, 0, 0);
      expect(cuenta.segundosRestantes(t), 60);

      final fuente = File('lib/presentation/pages/claves_page.dart')
          .readAsStringSync();
      expect(fuente.contains('periodo: cuenta.periodo'), isTrue,
          reason: 'la ficha tiene que pasar el periodo al anillo');
    });
  });

  group('el reloj no se multiplica al reconstruir (esto NO era un bug)', () {
    // Esto se dio por bueno como B5, «fuga de temporizadores», y **no lo era**.
    //
    // Se dio por bueno razonando: «`build()` no cancela el anterior y
    // `ref.onDispose` solo corre al descartar». La segunda mitad es falsa —
    // Riverpod 3 llama a `onDispose` también al invalidar.
    //
    // Lo que enseña este bloque, entonces, es lo que **realmente** importa, que
    // es un comportamiento que no conviene perder sin querer: reconstruir el
    // reloj no puede dejar dos scandals escribiendo a la vez.
    //
    // Y deja escrito el número, porque volver a comprobarlo es más barato que
    // volver a razonarlo: 3 reconstrucciones y 10 s dan **10** llamadas.
    test('tres reconstrucciones dejan un solo temporizador', () {
      var llamadas = 0;
      DateTime reloj() {
        llamadas++;
        return DateTime.utc(2026);
      }

      fakeAsync((async) {
        final cont = ProviderContainer(
          overrides: [relojProvider.overrideWithValue(reloj)],
        );
        final sub = cont.listen(relojUIProvider, (_, _) {});

        // El `read` después de cada `invalidate` **no es opcional**: invalidar
        // solo marca, y la reconstrucción ocurre en la siguiente lectura. Sin
        // forzar aquí, la última cuenta como un tick más dentro de la ventana
        // medida y el test da 11 en vez de 10 — que no es que el bug vuelva,
        // es que el test mide la reconstrucción como si fuera un temporizador.
        for (var i = 0; i < 3; i++) {
          cont.invalidate(relojUIProvider);
          cont.read(relojUIProvider);
        }

        final trasConstruir = llamadas;
        async.elapse(const Duration(seconds: 10));
        expect(llamadas - trasConstruir, 10,
            reason: '10 s con dos o más temporizadores vivos daría 20 o más');

        sub.close();
        cont.dispose();
        async.elapse(const Duration(seconds: 10));
      });
    });

    test('el reloj se para al soltar el contenedor', () {
      // El otro lado: un temporizador vivo después de cerrar la pantalla sigue
      // despertando el reloj del sistema sin que nadie lo mire.
      //
      // No se comprueba que `flushTimers` lance —eso depende de detalles de
      // implementación y no dice nada del comportamiento— sino que **el reloj
      // deja de avanzar**, que es lo que se quiere.
      var llamadas = 0;
      fakeAsync((async) {
        final cont = ProviderContainer(
          overrides: [
            relojProvider.overrideWithValue(() {
              llamadas++;
              return DateTime.utc(2026);
            }),
          ],
        );
        cont.listen(relojUIProvider, (_, _) {});
        cont.dispose();

        final alSoltar = llamadas;
        async.elapse(const Duration(seconds: 30));
        expect(llamadas, alSoltar,
            reason: 'el reloj siguió corriendo después de soltar el contenedor');
      });
    });
  });

  group('B6 — el comentario del portapapeles', () {
    test('el código comprueba antes de limpiar', () {
      // El comentario decía «getData y no un setData('')» dos líneas antes de
      // hacer un setData(''). Un comentario que miente sobre su propia función
      // hace que la línea de abajo parezca justificada cuando no lo está.
      final fuente = File('lib/presentation/pages/claves_page.dart')
          .readAsStringSync();
      final i = _limpieza.indexOf('getData');
      final j = _limpieza.indexOf("setData");
      expect(i, greaterThan(-1));
      expect(j, greaterThan(-1));
      // El `getData` va **antes** del `setData`: se compara y luego se borra.
      // Sin mirar, un timer disparado tras otra copia borraría lo recién copiado.
      expect(i, lessThan(j), reason: 'se borra antes de comprobar');
      expect(fuente.contains('porqueporque'), isFalse,
          reason: 'quedó una palabra duplicada de una edición');
    });
  });

  group('B3 — la copia se guarda donde se puede recuperar', () {
    test('el nombre del fichero es el mismo al guardar y al leer', () {
      // Si cada lado decide el nombre, un cambio deja al otro leyendo un
      // fichero que ya no existe, y el error es «no hay copia» — el mismo
      // mensaje que «no has exportado nunca».
      expect(nombreCopia, 'aegis-claves.json');
    });

    test('la autoridad del proveedor es la del manifest', () {
      // Si `file_paths.xml` y este nombre no coinciden, Android lanza
      // `IllegalArgumentException` al abrir, y el mensaje no habla de rutas:
      // habla de permisos, que es el peor sitio para buscar un error de config.
      final manifest = File(
        'android/app/src/main/AndroidManifest.xml',
      ).readAsStringSync();
      expect(manifest.contains('android:authorities="\${applicationId}.ficheros"'),
          isTrue);
      expect(proveedorCopias, 'com.aegis.aegis_console.ficheros');
    });

    test('las rutas de copia están declaradas en file_paths.xml', () {
      final xml =
          File('android/app/src/main/res/xml/file_paths.xml').readAsStringSync();
      expect(xml.contains('name="copias"'), isTrue,
          reason: 'sin esta entrada, el fichero exportado no se puede abrir '
              'desde fuera de la app: la copia sería inalcanzable otra vez');
      expect(xml.contains('path="copias/"'), isTrue);
    });

    test('el fichero es cifrado y no texto plano', () async {
      final b = Boveda();
      b.anadir(
        CuentaQr(
          emisor: 'GitHub',
          etiqueta: 'demo',
          semilla: base32Decodificar('JBSWY3DPEHPK3PXP'),
          algoritmo: AlgoritmoTotp.sha1,
          digitos: 6,
          periodo: 30,
        ),
        DateTime.utc(2026),
        id: 'a1',
      );
      final sobre = await cifrarBoveda(b, 'la contraseña');
      expect(sobre.contains('GitHub'), isFalse);
      expect(sobre.contains('demo'), isFalse);
      expect(sobre.contains(base64Encode(b.cuentas.first.semilla)), isFalse);
      // Y que se puede volver a abrir con esa contraseña.
      expect((await abrirCopia(sobre, 'la contraseña')).cuentas.length, 1);
    });
  });

  group('Fase 0 — el diálogo no promete lo que Aegis no cumple', () {
    // El texto decía «son lo único que queda si pierdes este móvil». No es que
    // Aegis no cumpliera todavía: es que **canjear no puede** cumplirlo, porque
    // marcar un hash como gastado no devuelve el acceso a nada.
    //
    // La trampa de este fallo es que el texto era plausible y el botón estaba
    // ahí. Alguien que pierde el móvil lo lee, lo toma por la red de seguridad,
    // **no guarda los códigos del propio servicio** —que son los que sí
    // devuelven el acceso— y descubre el problema cuando ya no hay nada que
    // hacer.
    test('el texto dice que no devuelven el acceso', () {
      // Se mira solo el **texto de la app**, no el fichero entero: la frase
      // prohibida aparece en el comentario que explica por qué se quitó, y un
      // test que la busca en todo el fichero tendría que borrar ese comentario,
      // que explica el fallo. Y no se borra.
      final fuente = File('lib/presentation/pages/claves_page.dart')
          .readAsStringSync();
      final soloTexto = fuente
          .split('\n')
          .where((l) => !l.trimLeft().startsWith('//'))
          .join('\n');
      expect(soloTexto.contains('son lo único que queda si pierdes este'),
          isFalse,
          reason: 'no devuelven el acceso al servicio: no se puede prometer');
      expect(soloTexto.contains('no** devuelven el acceso'), isTrue,
          reason: 'tiene que decir que no devuelven el acceso');
      expect(soloTexto.contains('códigos de recuperación que te dio **él**'),
          isTrue,
          reason: 'tiene que decir dónde está la red de verdad');
    });

    test('el canje solo marca el hash como gastado, y nada más', () {
      // El motivo por el que el texto anterior era falso, comprobado contra el
      // código y no de memoria: no hay ningún otro uso del id que devuelve.
      final fuente = File('lib/presentation/pages/claves_page.dart')
          .readAsStringSync();
      final i = fuente.indexOf('Future<void> _canjear()');
      final cuerpo = fuente.substring(i, i + 1200);
      expect(cuerpo.contains('showSnackBar'), isTrue);
      expect(cuerpo.contains('escribirEn'), isFalse);
      expect(cuerpo.contains('cifrarBoveda'), isFalse);
      expect(cuerpo.contains('abrirCopia'), isFalse);
    });
  });
}

/// El bloque de limpieza del portapapeles, tal cual está en el fichero.
final String _limpieza = () {
  final fuente = File('lib/presentation/pages/claves_page.dart')
      .readAsStringSync();
  final i = fuente.indexOf('final actual = await Clipboard.getData');
  final j = fuente.indexOf("setData(const ClipboardData(text: ''))");
  return i >= 0 && j >= 0 ? fuente.substring(i, j + 50) : '';
}();

/// Un almacenamiento que devuelve siempre el mismo texto.
class _StorageConTexto implements FlutterSecureStorage {
  _StorageConTexto(this.texto);
  final String? texto;

  @override
  Future<String?> read({
    required String key,
    AppleOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    AppleOptions? mOptions,
    WindowsOptions? wOptions,
  }) async =>
      texto;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}