// El contorno del arte, y por qué se calcula.
//
// ## Por qué esto necesita un test
// El contorno **no** está escrito en ningún sitio: sale de contar vecinos. Eso
// significa que puede salir mal de dos maneras que a simple vista son
// indistinguibles:
//
// - **Todo es contorno.** El glifo se ve como un bloque macizo del color de
//   estado, y parece que funciona: cambia de color y brilla.
// - **Nada es contorno.** El color de estado no aparece por ningún lado, y el
//   dibujo se ve gris. Esto sí se nota.
//
// El primero es el peligroso, y por eso el test vigila la **banda** en la que
// cae la fracción de contorno, no un valor exacto: el arte puede cambiar y el
// umbral debe seguir teniendo sentido.
import 'package:flutter_test/flutter_test.dart';

import 'package:aegis_console/core/theme/aegis_palette.dart';
import 'package:aegis_console/core/widgets/aegis_mark.dart';
import 'package:aegis_console/core/widgets/dibujo_texto.dart';
import 'package:aegis_console/core/widgets/glifos/calavera_jazz.dart';

void main() {
  group('el contorno del arte', () {
    // Un dibujo de 5 líneas donde la respuesta se sabe a ojo: una tira llena
    // en el centro, y un borde ralo arriba y abajo.
    //
    // La fila 2 tiene un hueco en el medio a propósito, para que se vea que el
    // hueco no lo tapa ninguna de las dos capas.
    const pequeno = <String>[
      '  ##############',
      ' ############## ',
      ' ##  ####    ## ',
      ' ############## ',
      '  ##############',
    ];

    test('el interior denso no es contorno', () {
      final d = DibujoTexto(pequeno);
      // (2,6): tiene los 8 vecinos —arriba, abajo, izquierda y derecha— porque
      // las filas 1 y 3 son llenas. Es la definición de interior.
      expect(d.textoContorno[2][6], ' ',
          reason: 'una celda con los 8 vecinos es interior');
      expect(d.textoInterior[2][6], '#');
    });

    test('los restos ralos de los extremos sí son contorno', () {
      final d = DibujoTexto(pequeno);
      // La fila de arriba no tiene nada encima: le faltan tres vecinos.
      expect(d.textoContorno[0].contains('#'), isTrue,
          reason: 'la fila de arriba es borde entero');
      expect(d.textoInterior[0].trim(), isEmpty);
    });

    test('las dos capas se reparten sin pisarse', () {
      final d = DibujoTexto(pequeno);
      for (var f = 0; f < d.alto; f++) {
        for (var c = 0; c < d.ancho; c++) {
          if (pequeno[f][c] == ' ') continue;
          final enInterior = d.textoInterior[f][c] != ' ';
          final enContorno = d.textoContorno[f][c] != ' ';
          expect(enInterior && enContorno, isFalse,
              reason: 'la celda ($f,$c) no puede estar en las dos capas');
          expect(enInterior || enContorno, isTrue,
              reason: 'la celda ($f,$c) tiene que estar en alguna de las dos');
        }
      }
    });

    test('el hueco se respeta en las dos capas', () {
      final d = DibujoTexto(pequeno);
      // El hueco de la fila 2, de las columnas 9 a 12: ninguna capa lo tapa.
      for (var c = 9; c <= 12; c++) {
        expect(d.textoInterior[2][c], ' ', reason: 'interior en la columna $c');
        expect(d.textoContorno[2][c], ' ', reason: 'contorno en la columna $c');
      }
    });
  });

  group('la banda del contorno', () {
    // El arte real. Estas dos cifras son la razón de que el test exista.
    final real = DibujoTexto(calaveraJazz);

    test('el contorno es una fracción, no un borrón ni un detalle', () {
      final f = real.fraccionContorno;
      // La banda es **estrecha a propósito**. El arte es un bloque macizo: casi
      // todas las celdas tienen los 8 vecinos, así que el contorno es una franja
      // de dos letras en cada borde de línea. Una banda más ancha dejaría pasar un
      // contorno que no se ve; una banda de 0 a 1 dejaría pasar un glifo entero
      // pintado del color de estado. Las dos cosas parecen funcionar.
      expect(f, greaterThan(0.03),
          reason: 'si el contorno es minúsculo, el estado no se ve: $f');
      expect(f, lessThan(0.15),
          reason: 'si casi todo es contorno, el glifo es un bloque del color '
              'de estado y no una calavera: $f');
    });

    test('la silueta se reconoce: el ancho crece y luego mengua', () {
      // La frente se abre y los dientes cierran. Es lo que distingue una
      // calavera de un rectángulo, y sale de los datos, no de mirarla.
      final anchos = [
        for (var f = 0; f < real.alto; f++)
          real.textoInterior[f].split('').where((c) => c != ' ').length
      ];
      final mitad = real.alto ~/ 2;
      final anchoInicial = anchos.sublist(0, 4).reduce((a, b) => a > b ? a : b);
      final anchoMedio = anchos.sublist(mitad - 2, mitad + 2)
          .reduce((a, b) => a > b ? a : b);
      final anchoFinal = anchos.sublist(real.alto - 3).reduce((a, b) => a > b ? a : b);

      expect(anchoMedio, greaterThan(anchoInicial),
          reason: 'la calavera tiene que abrirse: $anchoInicial -> $anchoMedio');
      expect(anchoMedio, greaterThan(anchoFinal),
          reason: 'y cerrarse en la mandíbula: $anchoMedio -> $anchoFinal');
    });
  });

  group('el color de cada estado', () {
    // Un color, una función. Este test es el que impide que un día el glifo sea
    // celeste en reposo y alguien lo pinte de verde en otro sitio.
    test('reposo es celeste', () {
      expect(colorDeEstado(EstadoAegis.reposo), AegisPalette.brand);
    });

    test('hablando es magenta rojizo', () {
      expect(colorDeEstado(EstadoAegis.hablando), AegisPalette.voz);
    });

    test('sin puente es gris, no rojo', () {
      // No es un error: es una ausencia. Ponerlo en `danger` haría que una
      // laptop apagada pareciera una avería.
      expect(colorDeEstado(EstadoAegis.sinPuente), AegisPalette.apagado);
      expect(colorDeEstado(EstadoAegis.sinPuente), isNot(AegisPalette.danger));
    });

    test('los tres estados son colores distintos', () {
      final colores = EstadoAegis.values.map(colorDeEstado).toSet();
      expect(colores.length, EstadoAegis.values.length,
          reason: 'si dos estados comparten color, el glifo no puede decir en '
              'qué estado está');
    });
  });
}
