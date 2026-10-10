// La pantalla de claves, de punta a punta.
//
// ## Por qué una prueba de la pantalla y no solo de la lógica
// Porque hay cosas que solo existen en la unión de las dos, y son las que
// fallan de verdad: si el provider no se recarga tras un alta, la lista se
// queda vacía; si el diálogo de códigos no devuelve nada, el alta se pierde por
// el camino. Ninguna de las dos se ve leyendo `boveda.dart`.
import 'package:aegis_console/core/auth/boveda.dart';
import 'package:aegis_console/core/auth/otpauth.dart';
import 'package:aegis_console/presentation/pages/claves_page.dart';
import 'package:aegis_console/presentation/providers/boveda_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

/// Deja la pantalla quieta.
///
/// No se usa `pumpAndSettle` en ninguna pantalla con `AegisScaffold`: el
/// `HudOverlay` que hay por encima lleva un `AnimationController..repeat()`, y
/// eso significa que **nunca** hay un frame en el que no quede nada animado.
/// `pumpAndSettle` se queda esperando para siempre y el test muere por tiempo,
/// no por un fallo suyo. Se avanza el reloj un rato fijo, que es lo que
/// importa: que la pantalla haya pintado y las transiciones terminado.
Future<void> asentar(WidgetTester t) async {
  for (var i = 0; i < 8; i++) {
    await t.pump(const Duration(milliseconds: 120));
  }
}

/// Almacén en memoria con el Keystore sustituido.
class AlmacenEnMemoria implements AlmacenBoveda {
  Boveda boveda = Boveda();

  @override
  Future<Boveda> leer() async => boveda;
  @override
  Future<void> escribir(Boveda b) async => boveda = b;
  @override
  Future<List<String>> anadir(CuentaQr qr) async {
    final c = boveda.anadir(qr, DateTime.utc(2026), id: boveda.nuevoId());
    await escribir(boveda);
    return c;
  }
  @override
  Future<String?> canjear(String codigo) async {
    final id = boveda.canjear(codigo, DateTime.utc(2026));
    if (id != null) await escribir(boveda);
    return id;
  }
  @override
  Future<bool> borrar(String id) async {
    final r = boveda.borrar(id);
    if (r) await escribir(boveda);
    return r;
  }
  @override
  Future<List<Cuenta>> todas() async => boveda.cuentas;
}

void main() {
  late AlmacenEnMemoria almacen;

  setUp(() => almacen = AlmacenEnMemoria());

  Future<void> montar(WidgetTester t, {DateTime? ahora}) async {
    final reloj = ahora ?? DateTime.utc(2026, 10, 5, 12, 0, 0);
    await t.pumpWidget(ProviderScope(
      overrides: [
        almacenBovedaProvider.overrideWithValue(almacen),
        relojProvider.overrideWithValue(() => reloj),
        relojUIProvider.overrideWith(() => RelojUIFijo(reloj)),
      ],
      child: const MaterialApp(home: ClavesPage()),
    ));
    await asentar(t);
  }

  group('sin cuentas', () {
    testWidgets('lo dice y ofrece las dos formas de empezar', (t) async {
      await montar(t);
      expect(find.text('No hay cuentas todavía.'), findsOneWidget);
      expect(find.text('Escanear'), findsOneWidget);
      expect(find.text('Teclear'), findsOneWidget);
    });

    testWidgets('no enseña ningún código', (t) async {
      await montar(t);
      expect(find.textContaining(RegExp(r'\d{3} \d{3}')), findsNothing);
    });
  });

  group('los botones hacen algo cuando los tocas', () {
    // ## Por qué este grupo existe, y no el anterior
    //
    // Los botones de esta pantalla **no hacían nada** y toda la puerta estaba
    // en verde: 0 issues de analyze y todos los tests en verde. La causa era
    // `alEscanear: () => _escanear`, que devuelve una *referencia* al método en
    // vez de llamarlo, y Dart lo acepta sin quejarse porque el tipo de retorno
    // `void` descarta cualquier valor.
    //
    // Los tests anteriores solo comprobaban `find.text('Escanear')`: que el
    // botón **existe**. Este grupo comprueba que **responde**, que es lo que un
    // usuario nota y lo que ningún test estaba mirando.
    testWidgets('tocar Escanear abre el escáner', (t) async {
      await montar(t);
      expect(find.text('Escanear'), findsOneWidget);
      await t.tap(find.text('Escanear'));
      await asentar(t);
      // Se comprueba algo **único** de la pantalla del escáner, no su título:
      // el título también es «Escanear», así que buscarlo después daría verdad
      // con la pantalla nueva y también sin haber cambiado de sitio.
      expect(find.text('Pegar el enlace'), findsOneWidget,
          reason: 'el escáner no se abrió: el botón no hizo nada');
      // Y la de claves ya no está.
      expect(find.text('Teclear'), findsNothing);
    });

    testWidgets('tocar Teclear abre el diálogo de teclear a mano', (t) async {
      await montar(t);
      await t.tap(find.text('Teclear'));
      await asentar(t);
      // El diálogo dice lo que hay que hacer, que es lo que se abre.
      expect(find.text('Añadir a mano'), findsOneWidget,
          reason: 'el diálogo no se abrió: el botón no hizo nada');
    });
  });

  group('con una cuenta', () {
    setUp(() async {
      await almacen.anadir(leerOtpauth(
        'otpauth://totp/GitHub:demo?secret=JBSWY3DPEHPK3PXP&issuer=GitHub',
      ));
    });

    testWidgets('enseña emisor, etiqueta y código', (t) async {
      await montar(t);
      expect(find.text('GitHub'), findsOneWidget);
      expect(find.text('demo'), findsOneWidget);
      // El código agrupado en dos grupos de tres.
      expect(find.textContaining(RegExp(r'\d{3} \d{3}')), findsOneWidget);
    });

    testWidgets('enseña el anillo con la cuenta atrás', (t) async {
      await montar(t);
      // El número del centro del anillo: 30 segundos en la ventana entera.
      expect(find.text('30'), findsOneWidget);
    });

    testWidgets('no avisa de recuperación si están todos', (t) async {
      // Con los diez intactos, la línea de aviso **no aparece**: una fila
      // permanente de «todo bien» es ruido que nadie lee.
      await montar(t);
      expect(find.textContaining('códigos de recuperación'), findsNothing);
    });

    testWidgets('copiar al portapapeles pone el código sin espacios', (t) async {
      final copiados = <String>[];
      t.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        (call) async {
          if (call.method == 'Clipboard.setData') {
            copiados.add((call.arguments as Map)['text'] as String);
          }
          return null;
        },
      );
      addTearDown(() => t.binding.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, null));

      await montar(t);
      await t.tap(find.textContaining(RegExp(r'\d{3} \d{3}')));
      await asentar(t);

      expect(copiados, isNotEmpty, reason: 'no se copió nada');
      // Sin espacios: el portapapeles lo van a pegar en un campo de login, y un
      // espacio en medio del código hace que falle.
      expect(copiados.last, matches(RegExp(r'^\d{6}$')));
      expect(find.textContaining('copiado'), findsWidgets);
    });
  });

  group('aviso de recuperación', () {
    testWidgets('avisa cuando quedan pocos', (t) async {
      final codigos = await almacen.anadir(leerOtpauth(
        'otpauth://totp/GitHub:demo?secret=JBSWY3DPEHPK3PXP&issuer=GitHub',
      ));
      // Gasta ocho de los diez.
      for (final c in codigos.take(8)) {
        almacen.boveda.canjear(c, DateTime.utc(2026));
      }
      await almacen.escribir(almacen.boveda);

      await montar(t);
      expect(find.textContaining('Te quedan 2 códigos'), findsOneWidget);
    });

    testWidgets('avisa distinto cuando no queda ninguno', (t) async {
      final codigos = await almacen.anadir(leerOtpauth(
        'otpauth://totp/GitHub:demo?secret=JBSWY3DPEHPK3PXP&issuer=GitHub',
      ));
      for (final c in codigos) {
        almacen.boveda.canjear(c, DateTime.utc(2026));
      }
      await almacen.escribir(almacen.boveda);

      await montar(t);
      expect(find.textContaining('No te queda ningún código'), findsOneWidget);
    });
  });

  group('borrar', () {
    testWidgets('pide confirmación y dice qué se pierde', (t) async {
      await almacen.anadir(
          leerOtpauth('otpauth://totp/GitHub:demo?secret=JBSWY3DPEHPK3PXP'));
      await montar(t);

      await t.tap(find.byIcon(Icons.delete_outline));
      await asentar(t);

      // El diálogo tiene que explicar la consecuencia: un «¿Seguro?» a secas
      // deja sin saber si se van también los códigos de recuperación.
      expect(find.text('¿Borrar la cuenta?'), findsOneWidget);
      expect(find.textContaining('códigos de recuperación'), findsOneWidget);
      expect(almacen.boveda.cuentas.length, 1, reason: 'se borró antes de confirmar');

      await t.tap(find.text('Borrar'));
      await asentar(t);
      expect(almacen.boveda.cuentas.length, 0);
      expect(find.text('No hay cuentas todavía.'), findsOneWidget);
    });

    testWidgets('cancelar no borra', (t) async {
      await almacen.anadir(
          leerOtpauth('otpauth://totp/GitHub:demo?secret=JBSWY3DPEHPK3PXP'));
      await montar(t);
      await t.tap(find.byIcon(Icons.delete_outline));
      await asentar(t);
      await t.tap(find.text('Cancelar'));
      await asentar(t);
      expect(almacen.boveda.cuentas.length, 1);
    });
  });

  group('bóveda dañada', () {
    testWidgets('lo dice y no se va', (t) async {
      // Una pantalla en vez de un snackbar: si la bóveda está corrupta, tocar
      // cualquier cosa puede sobrescribir lo que quede, y eso hay que decirlo
      // sin que el mensaje desaparezca a los tres segundos.
      await t.pumpWidget(ProviderScope(
        overrides: [
          almacenBovedaProvider.overrideWithValue(AlmacenRoto()),
          relojProvider.overrideWithValue(() => DateTime.utc(2026)),
          relojUIProvider.overrideWith(() => RelojUIFijo(DateTime.utc(2026))),
        ],
        child: const MaterialApp(home: ClavesPage()),
      ));
      await asentar(t);

      expect(find.text('La bóveda no se puede leer.'), findsOneWidget);
      expect(find.text('Reintentar'), findsOneWidget);
    });
  });
}

/// Un reloj que no se mueve: sin esto los timers de `pumpAndSettle` no
/// terminan nunca, porque el `RelojController` programa un tick cada segundo.
class RelojUIFijo extends RelojController {
  RelojUIFijo(this.t);
  final DateTime t;
  @override
  DateTime build() => t;
}

/// Un almacén que siempre falla, como el Keystore cuando el sobre no cuadra.
class AlmacenRoto implements AlmacenBoveda {
  // La corrupción es un **valor**, no una excepción. Un almacén que «no puede
  // leer» lo que hace es devolver la bóveda marcada, y eso es lo que traduce el
  // estado de la pantalla.
  @override
  Future<Boveda> leer() async => Boveda(corrupta: true);
  @override
  Future<void> escribir(Boveda b) async => b.escribirEn(this);
  @override
  Future<List<String>> anadir(CuentaQr qr) async =>
      throw StateError('no debería llegar aquí');
  @override
  Future<String?> canjear(String codigo) async =>
      throw StateError('no debería llegar aquí');
  @override
  Future<bool> borrar(String id) async =>
      throw StateError('no debería llegar aquí');
  @override
  Future<List<Cuenta>> todas() async => <Cuenta>[];
}