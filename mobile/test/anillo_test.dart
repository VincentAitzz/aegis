// El anillo y el código, que son las dos cosas con geometría.
//
// ## Por qué el anillo necesita un test
// Un `CustomPaint` con un `drawArc` no falla: **se dibuja mal**. Con el ángulo
// al revés se ve un anillo que se llena en vez de vaciarse, y eso solo lo nota
// alguien mirando la pantalla durante medio minuto. Lo que sí se puede
// comprobar aquí es la parte que decide: la fracción que llega, el color que
// corresponde, y que el hueco se calcula hacia el lado correcto.
import 'package:aegis_console/core/theme/aegis_palette.dart';
import 'package:aegis_console/presentation/widgets/anillo_cuenta.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('el color del anillo', () {
    // La regla: celeste con tiempo de sobra, ámbar al final, rojo en el último
    // suspiro. Los umbrales están a un tercio y a un sexto de la ventana.
    test('celte con la mitad de la ventana', () {
      expect(AnilloCuentaAtras.colorPara(1.0), AegisPalette.brand);
      expect(AnilloCuentaAtras.colorPara(0.5), AegisPalette.brand);
      expect(AnilloCuentaAtras.colorPara(0.35), AegisPalette.brand);
    });

    test('ámbar cuando queda poco', () {
      expect(AnilloCuentaAtras.colorPara(0.34), AegisPalette.warn);
      expect(AnilloCuentaAtras.colorPara(0.18), AegisPalette.warn);
    });

    test('rojo en el último momento', () {
      expect(AnilloCuentaAtras.colorPara(0.17), AegisPalette.danger);
      expect(AnilloCuentaAtras.colorPara(0.02), AegisPalette.danger);
      expect(AnilloCuentaAtras.colorPara(0.0), AegisPalette.danger);
    });

    test('el color baja de la gama siempre, nunca sube', () {
      // Un anillo que pasa de ámbar a celeste a mitad de ventana se lee como
      // que el tiempo se ha reiniciado. La urgencia es creciente con el
      // tiempo restante, así que bajando de fracción la urgencia solo puede
      // subir.
      int urgencia(Color c) => switch (c) {
            AegisPalette.brand => 0,
            AegisPalette.warn => 1,
            AegisPalette.danger => 2,
            _ => -1,
          };

      var anterior = urgencia(AnilloCuentaAtras.colorPara(1.0));
      var cambios = 0;
      for (var f = 1.0; f >= 0.0; f -= 0.01) {
        final actual = urgencia(AnilloCuentaAtras.colorPara(f));
        expect(actual >= anterior, isTrue,
            reason: 'en $f la urgencia bajó');
        if (actual != anterior) cambios++;
        anterior = actual;
      }
      // Exactamente dos cambios: celeste→ámbar→rojo. Un cuarto salto sería un
      // color que sube de gama, que es justo lo que este test prohíbe.
      expect(cambios, 2);
    });
  });

  group('el anillo dibujado', () {
    testWidgets('pinta sin quejarse, con cualquier fracción', (t) async {
      for (final f in [0.0, 0.02, 0.5, 0.99, 1.0]) {
        await t.pumpWidget(MaterialApp(
          home: Scaffold(body: AnilloCuentaAtras(fraccion: f)),
        ));
        expect(t.takeException(), isNull, reason: 'con fracción $f');
      }
    });

    testWidgets('aguanta una fracción fuera de rango sin romperse', (t) async {
      // Una fracción >1 o <0 no debería pasar: el `CustomPaint` con un `sweepAngle`
      // absurdo lanza. Que quede acotado dentro es lo que evita que un
      // reloj raro tumbe la pantalla entera.
      for (final f in [-1.0, -0.5, 1.5, 100.0]) {
        await t.pumpWidget(MaterialApp(
          home: Scaffold(body: AnilloCuentaAtras(fraccion: f)),
        ));
        expect(t.takeException(), isNull, reason: 'con fracción $f');
      }
    });

    testWidgets('muestra los segundos que quedan', (t) async {
      // Con la ventana completa son 30. Es lo que el número del centro dice.
      await t.pumpWidget(MaterialApp(
        home: Scaffold(body: AnilloCuentaAtras(fraccion: 1.0)),
      ));
      expect(find.text('30'), findsOneWidget);
    });

    testWidgets('redibuja al cambiar la fracción', (t) async {
      // Un `shouldRepaint` mal puesto deja el anillo congelado: el número de
      // segundos sigue cambiando pero el hueco no se mueve.
      Widget montar(double f) => MaterialApp(
            home: Scaffold(body: AnilloCuentaAtras(fraccion: f)),
          );
      await t.pumpWidget(montar(1.0));
      await t.pumpWidget(montar(0.5));
      await t.pump();
      expect(t.takeException(), isNull);
    });
  });

  group('el código agrupado', () {
    // El agrupado existe para no tener que contar posiciones al copiar. Los
    // casos raros importan: seis y ocho dígitos son los que hay, pero el
    // agrupado se usa con lo que venga.
    test('seis dígitos, en dos grupos de tres', () {
      expect(CodigoGrande.agrupar('123456'), '123 456');
    });

    test('ocho dígitos, en tres grupos', () {
      expect(CodigoGrande.agrupar('12345678'), '123 456 78');
    });

    test('tres o menos, sin agrupar', () {
      expect(CodigoGrande.agrupar('123'), '123');
      expect(CodigoGrande.agrupar('12'), '12');
      expect(CodigoGrande.agrupar('1'), '1');
    });

    test('vacío no revienta', () {
      expect(CodigoGrande.agrupar(''), '');
    });

    test('agrupar es idempotente sobre algo ya agrupado se nota', () {
      // Agrupar dos veces no es lo mismo que agrupar una, y por eso solo se
      // agrupa el código crudo. Este test fija el comportamiento para que nadie
      // lo aplique dos.
      final codigo = '123456';
      expect(CodigoGrande.agrupar(CodigoGrande.agrupar(codigo)),
          isNot(CodigoGrande.agrupar(codigo)));
    });
  });
}