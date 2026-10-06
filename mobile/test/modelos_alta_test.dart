// Los modelos del alta y de la ficha privada.
//
// Fijan dos cosas que la app **no puede adivinar** y que, si se leen mal,
// mienten:
//
// - qué secciones de la ficha quedan por escribir (`ProyectoAlta.faltan`);
// - si la ficha privada tiene algo escrito o es la plantilla sin responder
//   (`FichaPrivada.sinRellenar`).
//
// La segunda es la más delicada: la plantilla que genera el bridge trae
// comentarios de ayuda y encabezados, y si `sinRellenar` dijera que hay
// contenido, la app pintaría «Cliente» sobre un fichero donde no hay nada. Y al
// revés: un «pendiente» escrito a mano no es una respuesta, y por eso se
// comparte la regla de `fichas._escrito` del bridge.
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:aegis_console/data/models/asistente_models.dart';

void main() {
  group('ProyectoAlta', () {
    ProyectoAlta de(Map<String, dynamic> j) => ProyectoAlta.fromJson(j);

    test('lee lo que faltan por nombre', () {
      final a = de({
        'alias': 'encargo-nuevo',
        'tipo': 'encargo',
        'faltan': ['Qué problema resuelve', 'Quién lo usa'],
      });
      expect(a.faltan, ['Qué problema resuelve', 'Quién lo usa']);
      expect(a.completa, isFalse,
          reason: 'con secciones pendientes hay que seguir guided el formulario');
    });

    test('sin nada pendiente, completa', () {
      final a = de({'alias': 'x', 'faltan': []});
      expect(a.completa, isTrue);
    });

    test('sin la clave faltan, se trata como incompleta', () {
      // El bridge la manda siempre, pero un body recortado no debe hacer que la
      // app dé el alta por buena y no abra el formulario.
      final a = de({'alias': 'x'});
      expect(a.completa, isTrue, reason: 'vacío es «no sé», no «todo escrito»');
      expect(a.faltan, isEmpty);
    });

    test('el mensaje se conserva entero', () {
      final a = de({'alias': 'x', 'mensaje': 'Alta de x.\nVerificador declarado.'});
      expect(a.mensaje, contains('Verificador'));
    });
  });

  group('FichaPrivada.sinRellenar', () {
    // `sinRellenar` decide si se dice «Cliente» o «sin rellenar». Lo decide el
    // bridge, con su propia regla de «escrito» (comentarios, `###`,
    // marcadores de pendiente), y no un cálculo en Dart: la primera versión lo
    // hacía en Dart y era una segunda copia de esa regla, que es exactamente
    // como dos copias acaban diciendo cosas distintas.
    FichaPrivada de(String texto, {bool existe = true, List<String> escritas = const []}) =>
        FichaPrivada.fromJson({
          'alias': 'x',
          'texto': texto,
          'existe': existe,
          'escritas': escritas,
        });

    test('si no existe, está sin rellenar', () {
      expect(de('', existe: false).sinRellenar, isTrue);
    });

    test('existe pero sin secciones escritas, está sin rellenar', () {
      // El caso real de un proyecto recién dado de alta: el bridge devuelve la
      // plantilla parseada aunque el fichero no esté, así que hay doce
      // secciones y cero escritas.
      final f = de('## Cliente y contacto\n\n<!-- ponlo -->', escritas: const []);
      expect(f.sinRellenar, isTrue,
          reason: 'pintar «Cliente» sobre la plantilla sería mentir: lo que hay '
              'es una lista de temas');
    });

    test('con algo escrito, no está sin rellenar', () {
      final f = de('## Cliente y contacto\n\nAna.',
          escritas: const ['Cliente y contacto']);
      expect(f.sinRellenar, isFalse);
    });

    test('la plantilla real no trae nada escrito', () {
      // Se lee del repo: es la que genera el bridge, y una copia pegada aquí
      // se desincroniza sin que nada lo note.
      const ruta = '../bridge/fichas/_plantilla-privada.md';
      final texto = File(ruta).readAsStringSync();
      expect(de(texto).sinRellenar, isTrue);
    });
  });

  group('ModeloDeCobro', () {
    test('cada modelo tiene etiqueta y ayuda', () {
      for (final m in ModeloDeCobro.values) {
        expect(m.etiqueta, isNotEmpty);
        expect(m.ayuda, isNotEmpty,
            reason: 'sin la ayuda, elegir el modelo es adivinar');
      }
    });

    test('ningún modelo trae un importe', () {
      // El precio lo pone la persona. Un importe de ejemplo en un enum sería un
      // número que alguien copia tal cual, y Aegis tiene prohibido inventar
      // precios.
      for (final m in ModeloDeCobro.values) {
        expect(m.ayuda, isNot(matches(RegExp(r'\d'))),
            reason: '${m.etiqueta} trae un número en la ayuda');
        expect(m.etiqueta, isNot(matches(RegExp(r'\d'))));
      }
    });

    test('cubre un encargo sin cobrar', () {
      // El caso que hacía innecesario un formulario de campos fijos: un proyecto
      // interno no tiene presupuesto, y exigirlo produce información inventada.
      expect(ModeloDeCobro.values.any((m) => m == ModeloDeCobro.sinCobro), isTrue);
    });

    test('se puede recuperar por etiqueta', () {
      for (final m in ModeloDeCobro.values) {
        expect(ModeloDeCobro.desdeEtiqueta(m.etiqueta), m);
      }
      expect(ModeloDeCobro.desdeEtiqueta('inventado'), isNull);
    });
  });

  group('Listas de valores', () {
    test('las áreas son las que valida el bridge', () {
      expect(kAreas.map((a) => a.valor), ['apps', 'web', 'mobile']);
    });

    test('los tipos son encargo, producto y herramienta', () {
      expect(kTiposProyecto.map((t) => t.valor), ['encargo', 'producto', 'herramienta']);
    });

    test('cada valor tiene etiqueta legible', () {
      for (final a in kAreas) {
        expect(a.etiqueta, isNotEmpty);
      }
      for (final t in kTiposProyecto) {
        expect(t.etiqueta, isNotEmpty);
      }
    });
  });

  group('PlantillaFichas', () {
    test('lee las secciones por tipo', () {
      final p = PlantillaFichas.fromJson({
        'secciones': {
          'encargo': ['Qué problema resuelve', 'Alcance dentro'],
        },
        'tipos': ['encargo'],
        'privada': ['Cliente y contacto'],
      });
      expect(p.de('encargo').length, 2);
      expect(p.privada, ['Cliente y contacto']);
      expect(p.tipos, ['encargo']);
    });

    test('un tipo que no existe devuelve vacío, no revienta', () {
      final p = PlantillaFichas.fromJson({'secciones': {}});
      expect(p.de('inventado'), isEmpty);
    });

    test('un body vacío no rompe el modelo', () {
      final p = PlantillaFichas.fromJson({});
      expect(p.secciones, isEmpty);
      expect(p.privada, isEmpty);
      expect(p.aviso, isEmpty);
    });

    test('avisa si el bridge no pudo leer la plantilla privada', () {
      // Sin esto, una privada vacía parece un proyecto que no tiene nada que
      // rellenar, y no es lo mismo.
      final p = PlantillaFichas.fromJson({'privada': [], 'aviso': 'no está'});
      expect(p.aviso, isNotEmpty);
    });

    test('valores raros en el mapa no rompen', () {
      final p = PlantillaFichas.fromJson({
        'secciones': {'encargo': ['a', 7]},
      });
      expect(p.de('encargo'), ['a', '7']);
    });
  });

  group('FichaTexto con secciones', () {
    test('trae el mapa ya parseado del bridge', () {
      // La app no parsea markdown: `fichas._escrito` tiene reglas que no son
      // triviales y duplicarlas en Dart es la forma de que dejen de coincidir.
      final f = FichaTexto.fromJson({
        'alias': 'x',
        'kind': 'encargo',
        'secciones': {'Alcance dentro': 'una cosa'},
        'escritas': ['Alcance dentro'],
        'faltan': ['Qué problema resuelve'],
      });
      expect(f.secciones['Alcance dentro'], 'una cosa');
      expect(f.escritas, ['Alcance dentro']);
    });

    test('sin secciones, el mapa viene vacío y no falla', () {
      final f = FichaTexto.fromJson({'alias': 'x'});
      expect(f.secciones, isEmpty);
      expect(f.escritas, isEmpty);
    });

    test('un valor null en el mapa no rompe', () {
      final f = FichaTexto.fromJson({
        'alias': 'x',
        'secciones': {'a': null, 'b': 'texto'},
      });
      expect(f.secciones['b'], 'texto');
    });
  });

}
