// El generador de markdown de las fichas.
//
// Lo que se prueba aquí es que **nunca pierde nada**. Tres cosas concretas:
//
// - los `---` del frontmatter están siempre (A-016: sin ellos la puerta rechaza
//   la ficha y no dice por qué);
// - guardar dos veces produce el mismo texto, para que nadie pierda contenido
//   por pulsar «Guardar» de más;
// - una sección que el formulario no conoce sobrevive al guardado. Eso es lo
//   que hace segura la caja de markdown: si el generador la borrara, la
//   siguiente vez que se guardase desde el formulario desaparecería.
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:aegis_console/core/fichas/generador.dart';

/// Las secciones de un encargo, tal como las manda el bridge.
const encargo = [
  'Qué problema resuelve',
  'Para qué se usa',
  'Quién lo usa',
  'Criterio de aceptación',
  'Alcance dentro',
  'Alcance fuera',
  'Alternativas consideradas',
  'Cómo se verifica',
];

void main() {
  group('fichaPublica', () {
    test('el frontmatter lleva el kind', () {
      final md = fichaPublica(kind: 'encargo', secciones: encargo, valores: const {});
      expect(md, startsWith('---\nkind: encargo\n'));
    });

    test('los --- no se pueden perder', () {
      // El fallo medido: un modelo copiando texto se come el frontmatter, la
      // ficha queda sin tipo y la puerta la rechaza sin explicar por qué.
      final md = fichaPublica(kind: 'encargo', secciones: encargo, valores: const {});
      expect('---'.allMatches(md).length, 2, reason: 'apertura y cierre del frontmatter');
    });

    test('solo escribe las secciones con contenido', () {
      final md = fichaPublica(
        kind: 'encargo',
        secciones: encargo,
        valores: const {'Qué problema resuelve': 'Cobrar a mano.'},
      );
      expect(md, contains('## Qué problema resuelve'));
      expect(md, isNot(contains('## Para qué se usa')),
          reason: 'una sección vacía cuenta como no escrita: dejar el hueco es '
              'lo que hace que el formulario siga preguntando');
    });

    test('un valor con espacios alrededor se limpia', () {
      final md = fichaPublica(
        kind: 'encargo',
        secciones: encargo,
        valores: const {'Alcance dentro': '   \n  una cosa  \n '},
      );
      expect(md, contains('una cosa'));
      expect(md, isNot(contains('  una cosa')));
    });

    test('es idempotente: dos guardados dan el mismo texto', () {
      final a = fichaPublica(
        kind: 'encargo',
        secciones: encargo,
        valores: const {'Qué problema resuelve': 'x', 'Alcance dentro': 'y'},
      );
      final b = fichaPublica(
        kind: 'encargo',
        secciones: encargo,
        valores: const {'Qué problema resuelve': 'x', 'Alcance dentro': 'y'},
      );
      expect(a, b);
    });

    test('no deja lineas en blanco al final', () {
      final md = fichaPublica(
        kind: 'encargo',
        secciones: encargo,
        valores: const {'Qué problema resuelve': 'x'},
      );
      expect(md.endsWith('\n'), isTrue);
      expect(md.endsWith('\n\n'), isFalse);
    });

    test('conserva una seccion que el formulario no conoce', () {
      // El mecanismo de la caja de markdown. Sin esto, guardar desde el
      // formulario borraría lo que alguien escribió a mano.
      final md = fichaPublica(
        kind: 'encargo',
        secciones: encargo,
        valores: const {'Qué problema resuelve': 'x'},
        extra: const {'Un apartado raro': 'esto estaba escrito a mano'},
      );
      expect(md, contains('## Un apartado raro'));
      expect(md, contains('esto estaba escrito a mano'));
    });

    test('conserva una seccion vacia que el formulario no conoce', () {
      // Aunque no tenga contenido, se conserva el encabezado: borrarlo sería
      // decidir por la persona qué secciones existen.
      final md = fichaPublica(
        kind: 'encargo',
        secciones: encargo,
        valores: const {},
        extra: const {'Apartado vacio': ''},
      );
      expect(md, isNot(contains('## Apartado vacio')),
          reason: 'una sección sin texto no aporta nada al prompt');
    });

    test('las secciones del formulario van en su orden', () {
      final md = fichaPublica(
        kind: 'encargo',
        secciones: encargo,
        valores: const {
          'Alcance dentro': 'b',
          'Qué problema resuelve': 'a',
        },
      );
      expect(md.indexOf('## Qué problema resuelve'),
          lessThan(md.indexOf('## Alcance dentro')),
          reason: 'el orden lo decide el bridge y es el orden en que se rellena');
    });

    test('un titulo con comillas no rompe el frontmatter', () {
      // Sin comillas, un título con `:` o `"` produce un frontmatter que no
      // parsea y la ficha queda sin tipo.
      final md = fichaPublica(
        kind: 'encargo',
        secciones: encargo,
        valores: const {},
        titulo: 'Encargo del "cliente": versión 2',
      );
      final fm = md.split('---')[1];
      expect(fm, contains(r'titulo: "'));
    });

    test('sin titulo, el encabezado usa el tipo', () {
      final md = fichaPublica(kind: 'encargo', secciones: encargo, valores: const {});
      expect(md, contains('# Ficha · encargo'));
    });
  });

  group('fichaPrivada', () {
    test('lleva su frontmatter, sin kind', () {
      final md = fichaPrivada(secciones: const ['Cliente y contacto'], valores: const {});
      expect(md, startsWith('---\ntipo: privada\n'));
      expect(md, isNot(contains('kind:')),
          reason: 'la privada no tiene tipo: lo decide la pública y aquí no '
              'habría nadie que lo leyera');
    });

    test('es idempotente', () {
      final a = fichaPrivada(
        secciones: const ['Cliente y contacto', 'Modelo de cobro'],
        valores: const {'Modelo de cobro': 'precio cerrado'},
      );
      final b = fichaPrivada(
        secciones: const ['Cliente y contacto', 'Modelo de cobro'],
        valores: const {'Modelo de cobro': 'precio cerrado'},
      );
      expect(a, b);
    });

    test('no escribe secciones vacias', () {
      final md = fichaPrivada(
        secciones: const ['Cliente y contacto', 'Presupuesto y pagos'],
        valores: const {'Cliente y contacto': 'Ana'},
      );
      expect(md, contains('## Cliente y contacto'));
      expect(md, isNot(contains('## Presupuesto y pagos')));
    });
  });

  group('seccionesAConservar', () {
    test('devuelve lo que el formulario no conoce', () {
      final fuera = seccionesAConservar(
        conocidas: const ['A', 'B'],
        existentes: const {'A': 'lleno', 'B': 'lleno', 'C': 'raro'},
      );
      expect(fuera.keys, ['C']);
    });

    test('no devuelve nada si todo es conocido', () {
      final fuera = seccionesAConservar(
        conocidas: const ['A', 'B'],
        existentes: const {'A': 'lleno', 'B': 'lleno'},
      );
      expect(fuera, isEmpty);
    });
  });

  group('Coherencia con el bridge', () {
    test('las secciones del encargo son las que declara el bridge', () {
      // Si este test falla, el generador se está guiando por una lista propia y
      // esa lista ya no es la que la puerta exige.
      final ruta = '../bridge/app/fichas.py';
      final fuente = File(ruta).readAsStringSync();
      final bloque = fuente.split('"encargo": [').last.split(']').first;
      final delBridge = RegExp(r'"([^"]+)"')
          .allMatches(bloque)
          .map((m) => m.group(1)!)
          .toList();
      expect(delBridge, encargo,
          reason: 'SECCIONES_POR_TIPO cambió en el bridge: copia la lista en el '
              'test, y melhor aún, no la dupliques en la app');
    });

    test('la plantilla privada cubre las secciones que el bridge ofrece', () {
      final plantilla =
          File('../bridge/fichas/_plantilla-privada.md').readAsStringSync();
      final delFichero = RegExp(r'^## (.+)$', multiLine: true)
          .allMatches(plantilla)
          .map((m) => m.group(1)!)
          .toList();
      expect(delFichero, contains('Cliente y contacto'));
      expect(delFichero, contains('Modelo de cobro'));
      // Y la app tiene que poder generarlas todas: si el generador no aceptara
      // una sección, se perdería al guardar.
      final generada = fichaPrivada(
        secciones: delFichero,
        valores: {for (final s in delFichero) s: 'escrito'},
      );
      for (final s in delFichero) {
        expect(generada, contains('## $s'), reason: '«$s» se perdió al generar');
      }
    });
  });
}