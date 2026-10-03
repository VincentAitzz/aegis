// Lo que el móvil tiene que hacer bien, y que antes no hacía.
//
// Estos tests existen por un hueco concreto: el contrato de `createTask` no
// declaraba `project`, así que la ficha del proyecto nunca llegaba al prompt.
// El agente razonaba sin saber de qué se trataba, que es justo lo que el
// método de `bridge/metodo.md` prohíbe.
import 'package:flutter_test/flutter_test.dart';

import 'package:aegis_console/data/models/agent_models.dart';

void main() {
  group('ProjectInfo', () {
    ProjectInfo de(Map<String, dynamic> j) => ProjectInfo.fromJson(j);

    test('sin ficha: no se puede escribir', () {
      final p = de({'alias': 'compra-unida', 'estado': 'sin_ficha'});
      expect(p.sinFicha, isTrue);
      expect(p.escribible, isFalse,
          reason: 'la puerta va a negar cualquier escritura: la app debe decirlo antes');
    });

    test('parcial: cuenta las secciones que faltan', () {
      final p = de({
        'alias': 'data-sending',
        'estado': 'parcial',
        'faltan': ['Invariantes', 'Qué no toca'],
      });
      expect(p.faltan, hasLength(2));
      expect(p.escribible, isFalse);
    });

    test('completa: sí se puede escribir', () {
      final p = de({'alias': 'aegis', 'estado': 'completa'});
      expect(p.completa, isTrue);
      expect(p.escribible, isTrue);
    });

    test('un estado desconocido no se trata como completa', () {
      // Fail-safe: si el bridge manda algo raro, la app no debe abrir la puerta.
      final p = de({'alias': 'raro', 'estado': 'no_se'});
      expect(p.escribible, isFalse);
      expect(p.completa, isFalse);
    });

    test('sin tipo declarado no inventa uno', () {
      final p = de({'alias': 'portafolio', 'estado': 'sin_ficha', 'kind': ''});
      expect(p.kind, isEmpty);
    });

    test('tolera campos ausentes', () {
      final p = de({'alias': 'x'});
      expect(p.faltan, isEmpty);
      expect(p.verify, isEmpty);
      expect(p.existe, isTrue);
    });
  });
}
