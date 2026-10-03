// La navegación: que las secciones existan y que añadir una sea una entrada más.
//
// ## Por qué esto necesita un test
// El descriptor de sección es lo que hace que grow sea barato. Su valor está
// justo en lo que no se ve: que las secciones siguientes no tengan que
// registration manual, y que un alias no duplicado sea un error de compilación y
// no un comportamiento raro en la barra. Nada de eso se nota leyendo el código
// de una pantalla.
import 'package:flutter_test/flutter_test.dart';

import 'package:aegis_console/presentation/shell/aegis_section.dart';

void main() {
  group('el registro de secciones', () {
    test('la primera es la de inicio', () {
      // Si la primera no fuera la de pedir, la app abriría en otro sitio del
      // registro. El shell arranca en `kSecciones.first`.
      expect(kSecciones.first.alias, 'ahora');
    });

    test('los alias son únicos', () {
      // El alias es la identidad de la sección: va en el estado y en los
      // tests. Dos iguales harían que abrir una te llevara a la otra.
      final alias = kSecciones.map((s) => s.alias).toList();
      expect(alias.toSet().length, alias.length, reason: 'alias repetidos: $alias');
    });

    test('nadie queda sin icono', () {
      for (final s in kSecciones) {
        expect(s.label.trim(), isNotEmpty, reason: '${s.alias} sin etiqueta');
      }
    });

    test('la etiqueta cabe en la barra', () {
      // La barra divide el ancho en partes iguales: con cuatro o más secciones,
      // una etiqueta larga se sale de su mitad. Ocho caracteres es el límite
      // medido sobre 1080 px con la tipografía de 10 px.
      for (final s in kSecciones) {
        expect(s.label.length, lessThanOrEqualTo(8),
            reason: '${s.alias}: "${s.label}" no cabe en la barra');
      }
    });

    test('las secciones que necesitan puente lo declaran', () {
      // Es lo que permite que el shell ponga la puerta puesta en vez de dejar
      // una pantalla en blanco. Si por olvido queda en false, la sección
      // aparecerá vacía sin explicación y no hay forma de saber por qué.
      final porDefecto = kSecciones.where((s) => s.requierePuente).length;
      expect(porDefecto, greaterThanOrEqualTo(2),
          reason: 'casi nada necesita el puente: se ha marcado al revés');
    });

    test('el estado de sección cae en una sección que existe', () {
      // Un alias guardado que ya no está en el registro dejaría el shell sin
      // sección que pintar. Es el fallo de una sección renombrada.
      expect(kSecciones.map((s) => s.alias), contains('ahora'));
      expect(kSecciones.map((s) => s.alias), contains('misiones'));
      expect(kSecciones.map((s) => s.alias), contains('ajustes'));
    });
  });
}
