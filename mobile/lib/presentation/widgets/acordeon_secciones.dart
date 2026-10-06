/// El acordeón de secciones: una abierta a la vez, y es la que falta.
///
/// ## Por qué una sección y no un cuestionario de pasos
/// Un cuestionario de pasos obliga a recorrer 8 pantallas y, si te saltas la
/// tercera, no sabes que exists hasta volver. El acordeón se ve entero: sabes
/// cuántas faltan y cuáles son. Y como solo hay una abierta, y se abre la que
/// falta, se lee como un cuestionario sin perder el dónde-estoy.
///
/// ## Por qué avanza solo al guardar
/// Guardar una sección abre la siguiente que falte. Es lo que hace que el
/// recorrido sea cómodo sin quitar la posibilidad de saltar: si te has saltado
/// una, la verás cerrada con su marca, y un toque la abre.
///
/// ## Y por qué no es `ExpansionTile`
/// `ExpansionTile` no permite «solo una abierta» sin llevar el estado a mano, y
/// `acordion:` es experimental en Flutter 3.47. Aquí son veinte líneas, y el
/// comportamiento raro —avance automático— está explícito.
library;

import 'package:flutter/material.dart';

import '../../core/theme/aegis_palette.dart';

/// Una sección del acordeón, con su estado.
class SeccionAcordeon {
  const SeccionAcordeon({
    required this.titulo,
    required this.abierta,
    required this.escrita,
    this.ayuda = '',
    this.requerida = true,
  });

  final String titulo;

  /// Si es la sección abierta ahora. Solo una en toda la lista.
  final bool abierta;

  /// Si tiene contenido. Es lo que decide el `✓`.
  final bool escrita;

  /// Texto de ayuda, que va **encima** del campo de la abierta.
  final String ayuda;

  /// Las secciones de la ficha privada no son obligatorias a propósito. Sin esta
  /// marca, una lista de doce marcaría «11 sin escribir» como si fuera un
  /// problema, cuando la plantilla es un recordatorio y no un formulario.
  final bool requerida;
}

/// El acordeón. Recibe la lista ya ordenada y decide cuál abrir.
///
/// ## Por qué es controlado y no lleva el campo dentro
/// El campo de texto de cada sección lo pone [campoDe], porque el texto vive en
/// un `TextEditingController` que **no puede recrearse en cada `build`**: si lo
/// hiciera, al reescribir el markdown los campos perderían el cursor y el texto
/// a medio escribir. Y el estado de qué secciones están escritas lo conoce quien
/// regenerationa el documento, no este widget. Si el acordeón guardara su propio
/// estado, tendría dos verdades y se desincronizarían.
class AcordeonSecciones extends StatelessWidget {
  const AcordeonSecciones({
    super.key,
    required this.secciones,
    required this.onAlternar,
    required this.onGuardar,
    required this.campoDe,
    this.guardando = false,
  });

  final List<SeccionAcordeon> secciones;

  /// Abre una sección. Se le pasa el título y devuelve si queda abierta.
  final void Function(String titulo, bool abierta) onAlternar;

  /// Se llama al guardar la que está abierta. Devuelve si el guardado tuvo éxito,
  /// porque quien llama es el que sabe qué abrir después.
  final Future<bool> Function() onGuardar;

  /// El campo de la sección [titulo]. Solo se llama para la que está abierta.
  final Widget Function(String titulo) campoDe;

  final bool guardando;

  /// La primera sin escribir, que es la que se abre por defecto.
  ///
  /// Si ya están todas escritas, no se abre ninguna: un acordeón con todo
  /// cerrado dice «está completa», y abrir una invita a cambiar algo que ya no
  /// necesita cambios.
  static String? primeraPendiente(List<SeccionAcordeon> secciones) {
    for (final s in secciones) {
      if (!s.escrita) {
        return s.titulo;
      }
    }
    return null;
  }

  /// El progreso, como «3 de 8». Sin esto no se sabe si falta una sección o veinte.
  static (int, int) progreso(List<SeccionAcordeon> secciones) {
    final obligatorias = secciones.where((s) => s.requerida).toList();
    final escritas = obligatorias.where((s) => s.escrita).length;
    return (escritas, obligatorias.length);
  }

  @override
  Widget build(BuildContext context) {
    final (hechas, total) = progreso(secciones);
    final completa = total > 0 && hechas == total;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _Progreso(hechas: hechas, total: total, completa: completa),
        const SizedBox(height: 8),
        for (final s in secciones) ...[
          _Cabecera(
            seccion: s,
            onTap: () => onAlternar(s.titulo, !s.abierta),
          ),
          if (s.abierta)
            _Cuerpo(
              seccion: s,
              onGuardar: onGuardar,
              guardando: guardando,
              campo: campoDe(s.titulo),
            ),
        ],
      ],
    );
  }
}

class _Progreso extends StatelessWidget {
  const _Progreso({required this.hechas, required this.total, required this.completa});

  final int hechas;
  final int total;
  final bool completa;

  @override
  Widget build(BuildContext context) {
    final color = completa ? AegisPalette.ok : AegisPalette.fgFaint;
    return Row(
      children: [
        Expanded(
          child: ClipRRect(
            borderRadius: BorderRadius.circular(2),
            child: LinearProgressIndicator(
              value: total == 0 ? 0 : hechas / total,
              minHeight: 3,
              backgroundColor: AegisPalette.line,
              valueColor: AlwaysStoppedAnimation<Color>(color),
            ),
          ),
        ),
        const SizedBox(width: 10),
        Text(
          completa ? 'completa' : '$hechas de $total',
          style: TextStyle(
              fontFamily: AegisPalette.mono, fontSize: 10.5, color: color),
        ),
      ],
    );
  }
}

class _Cabecera extends StatelessWidget {
  const _Cabecera({required this.seccion, required this.onTap});

  final SeccionAcordeon seccion;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final s = seccion;
    final color = s.escrita
        ? AegisPalette.ok
        : s.abierta
            ? AegisPalette.brand
            : AegisPalette.fgFaint;
    return InkWell(
      onTap: onTap,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(vertical: 9, horizontal: 8),
        decoration: BoxDecoration(
          color: s.abierta ? AegisPalette.bg2 : Colors.transparent,
          border: Border(
            bottom: BorderSide(
                color: s.abierta ? AegisPalette.brand.withValues(alpha: .4) : AegisPalette.line),
          ),
        ),
        child: Row(
          children: [
            // La marca de estado es el `✓`/`—`, no solo el color: en esta paleta
            // el color solo no basta para quien tiene menos contraste, y ya se
            //lostó una vez con la pestaña activa.
            SizedBox(
              width: 16,
              child: Text(
                s.escrita ? '✓' : '—',
                style: TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 12,
                    color: color,
                    fontWeight: FontWeight.bold),
              ),
            ),
            Expanded(
              child: Text(
                s.titulo,
                style: TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 12,
                  color: s.abierta ? AegisPalette.fg : AegisPalette.fgFaint,
                ),
              ),
            ),
            if (!s.requerida)
              Padding(
                padding: const EdgeInsets.only(left: 6),
                child: Text('opcional',
                    style: TextStyle(
                        fontFamily: AegisPalette.mono,
                        fontSize: 9,
                        color: AegisPalette.fgFaint)),
              ),
            SizedBox(
              width: 18,
              child: Text(
                s.abierta ? '▾' : '▸',
                style: TextStyle(
                    fontFamily: AegisPalette.mono, fontSize: 12, color: AegisPalette.fgFaint),
                textAlign: TextAlign.center,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Cuerpo extends StatelessWidget {
  const _Cuerpo({
    required this.seccion,
    required this.onGuardar,
    required this.guardando,
    required this.campo,
  });

  final SeccionAcordeon seccion;
  final Future<bool> Function() onGuardar;
  final bool guardando;

  /// El campo de esta sección. Viene de fuera porque su controlador no puede
  /// vivir en un widget que se reconstruye: ver la nota del acordeón.
  final Widget campo;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(8, 10, 8, 12),
      color: AegisPalette.bg1,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (seccion.ayuda.isNotEmpty) ...[
            Text(
              seccion.ayuda,
              style: TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 10.5,
                  height: 1.5,
                  color: AegisPalette.fgFaint),
            ),
            const SizedBox(height: 8),
          ],
          // El campo lo pone quien abre el acordeón, para no perder el cursor al
          // reescribir el documento.
          campo,
          const SizedBox(height: 10),
          FilledButton(
            onPressed: guardando ? null : onGuardar,
            style: FilledButton.styleFrom(
              backgroundColor: AegisPalette.bg2,
              foregroundColor: AegisPalette.fg,
            ),
            child: Text(guardando ? 'Guardando…' : 'Guardar esta sección'),
          ),
        ],
      ),
    );
  }
}