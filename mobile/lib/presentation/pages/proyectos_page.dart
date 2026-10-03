/// Proyectos: los que Aegis puede tocar, y lo que le falta a cada uno.
///
/// ## Por qué esta pantalla es la puerta
/// Un proyecto sin marcar es de **solo lectura** para Aegis. No es un matiz de
/// la interfaz: es la línea que separa "puede trabajar solo aquí" de "no". Y la
/// razón está detrás: sin verificador declarado no hay contra qué comprobar que
/// el trabajo quedó bien, así que dar permiso de escritura sobre eso sería
/// autonomía sin criterio.
///
/// ## Por qué el interruptor no está donde uno lo pondría
/// Está en cada fila, no arriba. La pregunta que te haces mirando la pantalla
/// es "¿qué puede tocar?", y la respuesta está junto a la fila que te
/// interesa. Un interruptor global al principio obliga a recordar qué alias
/// habías marcado antes.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/aegis_palette.dart';
import '../../core/widgets/hud_panel.dart';
import '../../core/widgets/status_led.dart';
import '../../data/models/agent_models.dart';
import '../../data/models/asistente_models.dart';
import '../providers/agent_providers.dart';

class ProyectosPage extends ConsumerWidget {
  const ProyectosPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final proyectos = ref.watch(projectsProvider);
    final autonomia = ref.watch(autonomiaProvider);

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 28),
      children: [
        autonomia.when(
          loading: () => const HudPanel(
            title: 'AUTONOMÍA',
            child: Text('preguntando…',
                style: TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 12,
                    color: AegisPalette.fgDim)),
          ),
          error: (e, _) => HudPanel(
            title: 'AUTONOMÍA',
            accent: AegisPalette.danger,
            child: Text('no pude preguntar: $e',
                style: const TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 12,
                    color: AegisPalette.danger)),
          ),
          data: (a) => _Modo(modo: a),
        ),
        const SizedBox(height: 16),
        Text(
          'Lo que Aegis puede tocar sin preguntarte',
          style: const TextStyle(
            fontFamily: AegisPalette.mono,
            fontSize: 10.5,
            letterSpacing: 1,
            color: AegisPalette.fgFaint,
          ),
        ),
        const SizedBox(height: 10),
        proyectos.when(
          loading: () => const Text('buscando proyectos…',
              style: TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 12,
                  color: AegisPalette.fgFaint)),
          error: (e, _) => Text('$e',
              style: const TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 12,
                  color: AegisPalette.danger)),
          data: (lista) => Column(
            children: [
              for (final p in lista)
                _FilaProyecto(
                  proyecto: p,
                  marcado: autonomia.maybeWhen(
                    data: (a) => a.escribible(p.alias),
                    orElse: () => false,
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: 18),
        const _Explicacion(),
      ],
    );
  }
}

/// El interruptor de modo, con lo que significa en una frase.
///
/// El nombre solo (`solo`, `permiso`, `pleno`) no lo explica nadie, y un
/// selector de tres palabras sin explicación es un selector que se cambia por
/// casualidad.
class _Modo extends ConsumerStatefulWidget {
  const _Modo({required this.modo});

  final Autonomia modo;

  @override
  ConsumerState<_Modo> createState() => _ModoState();
}

class _ModoState extends ConsumerState<_Modo> {
  bool _ocupado = false;

  Future<void> _cambiar(String modo) async {
    setState(() => _ocupado = true);
    try {
      await ref.read(agentRepositoryProvider).modoAutonomia(modo);
      refrescarAsistente(ref);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('No pude cambiar el modo: $e')),
      );
    } finally {
      if (mounted) setState(() => _ocupado = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    // Etiquetas cortas a propósito: con seis secciones el botón sale de 360 px
    // y "Proyectos marcados" se partía en tres líneas, que se lee como roto.
    // La explicación larga va debajo, que sí tiene sitio.
    const etiquetas = {'solo': 'Mirar', 'permiso': 'Marcados', 'pleno': 'Fuera'};
    return HudPanel(
      title: 'AUTONOMÍA',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SegmentedButton<String>(
            // Sin el tick de seleccionado: se lleva el ancho del segmento
            // activo —que es justo el que tiene la etiqueta más larga— y lo
            // parte en dos líneas. El color ya dice cuál está elegido.
            showSelectedIcon: false,
            segments: [
              for (final m in widget.modo.modos)
                ButtonSegment(value: m, label: Text(etiquetas[m] ?? m)),
            ],
            selected: {widget.modo.modo},
            onSelectionChanged: _ocupado
                ? null
                : (s) => s.first == widget.modo.modo ? null : _cambiar(s.first),
          ),
          const SizedBox(height: 10),
          Text(
            widget.modo.explicacion,
            style: const TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 11,
              height: 1.5,
              color: AegisPalette.fgDim,
            ),
          ),
        ],
      ),
    );
  }
}

class _FilaProyecto extends ConsumerStatefulWidget {
  const _FilaProyecto({required this.proyecto, required this.marcado});

  final ProjectInfo proyecto;
  final bool marcado;

  @override
  ConsumerState<_FilaProyecto> createState() => _FilaProyectoState();
}

class _FilaProyectoState extends ConsumerState<_FilaProyecto> {
  bool _ocupado = false;

  Future<void> _alternar() async {
    setState(() => _ocupado = true);
    try {
      await ref
          .read(agentRepositoryProvider)
          .marcarProyecto(widget.proyecto.alias, escribir: !widget.marcado);
      refrescarAsistente(ref);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('No pude cambiar el permiso: $e')),
      );
    } finally {
      if (mounted) setState(() => _ocupado = false);
    }
  }

  /// Por qué este interruptor está deshabilitado, o '' si puede tocarse.
  String get _bloqueo {
    if (widget.proyecto.verify.isEmpty) {
      return 'no tiene verificador declarado: no hay contra qué comprobar '
          'que el trabajo quedó bien. Decláralo en app/projects.py primero.';
    }
    if (widget.proyecto.sinFicha) {
      return 'no tiene ficha. Sin ficha no puede escribir: no sabe qué toca.';
    }
    return '';
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.proyecto;
    final bloqueo = _bloqueo;
    final colorFicha = p.completa
        ? AegisPalette.ok
        : p.parcial
            ? AegisPalette.warn
            : AegisPalette.danger;

    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 10, 6, 10),
        decoration: BoxDecoration(
          color: widget.marcado ? AegisPalette.bg2 : AegisPalette.bg1,
          borderRadius: BorderRadius.circular(6),
          border: Border.all(
            color: widget.marcado
                ? AegisPalette.brand.withValues(alpha: .45)
                : AegisPalette.line,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                StatusLed(color: colorFicha, size: 7),
                const SizedBox(width: 9),
                Expanded(
                  child: Text(
                    p.alias,
                    style: const TextStyle(
                      fontFamily: AegisPalette.mono,
                      fontSize: 14,
                      color: AegisPalette.fg,
                    ),
                  ),
                ),
                if (_ocupado)
                  const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2))
                else
                  Switch(
                    value: widget.marcado,
                    onChanged: bloqueo.isEmpty && !_ocupado ? (_) => _alternar() : null,
                  ),
              ],
            ),
            const SizedBox(height: 4),
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: Text(
                bloqueo.isNotEmpty
                    ? bloqueo
                    : widget.marcado
                        ? 'Puede escribir aquí sin preguntarte.'
                        : 'Solo lectura. ${
                            p.faltan.isEmpty ? '' : 'Faltan ${p.faltan.length} secciones de su ficha.'}',
                style: TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 10.5,
                  height: 1.45,
                  color: bloqueo.isNotEmpty
                      ? AegisPalette.warn
                      : AegisPalette.fgFaint,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Explicacion extends StatelessWidget {
  const _Explicacion();

  @override
  Widget build(BuildContext context) {
    return HudPanel(
      title: 'QUÉ HAY DETRÁS',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Aegis lee y comprueba lo que quiera, sin avisarte. Para escribir '
            'necesita que marques el proyecto. Y lo que sale de tu disco —migrar '
            'una base, instalar en el teléfono— te lo pregunta siempre, con el '
            'motivo escrito.',
            style: TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 11,
              height: 1.6,
              color: AegisPalette.fgDim,
            ),
          ),
          const SizedBox(height: 10),
          const Text(
            'Si le dices que no y por qué, lo recuerda. No es que aprenda a '
            'tener cuidado: es que se lo dijiste una vez y lo tiene en cuenta.',
            style: TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 10.5,
              height: 1.55,
              color: AegisPalette.fgFaint,
            ),
          ),
        ],
      ),
    );
  }
}