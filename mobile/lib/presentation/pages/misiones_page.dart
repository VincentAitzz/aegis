/// Misiones: el historial y el seguimiento.
///
/// ## Qué es esta lista ahora
/// El historial de runs **del bridge** (`GET /runs`), no los ids que esta sesión
/// de la app recuerda.
///
/// ## Por qué cambió
/// Antes guardaba los `run_id` que la app había lanzado, y solo los llenaba el
/// camino de Hermes (`POST /tasks`), que ya no se usa. Se quedó una lista
/// vacía con una pantalla entera detrás: el historial de la app, que además
/// moría con la app.
///
/// El bridge escribe cada run a disco (`data/logs/runs/<id>.jsonl`) desde que el
/// autopilot dejó de perderlos, así que el historial **sobrevive a apagar el
/// portátil** y no depende de qué app se hubiera abierto. Un historial que
/// depende de la memoria de la sesión no es un historial.
///
/// ## Lo que aquí NO se abre
/// Un run viejo, en detalle. La traza se lee desde la terminal
/// (`docs/runbook.md` §1.1), donde está entera; aquí se dice qué pasó y
/// cuánto.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/aegis_palette.dart';
import '../../core/widgets/status_led.dart';
import '../../data/models/asistente_models.dart';
import '../providers/agent_providers.dart';

class MisionesPage extends ConsumerWidget {
  const MisionesPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final host = ref.watch(appConfigProvider);
    final runs = ref.watch(runsProvider);

    return runs.when(
      loading: () => const Text('buscando runs…',
          style: TextStyle(
              fontFamily: AegisPalette.mono, fontSize: 11, color: AegisPalette.fgFaint)),
      error: (e, _) => Text('no pude leer los runs: $e',
          style: const TextStyle(
              fontFamily: AegisPalette.mono, fontSize: 11, color: AegisPalette.danger)),
      data: (lista) {
        if (lista.isEmpty) return _Vacio(conectadoA: host.apiHost);
        return ListView(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 28),
          children: [
            Text('${lista.length} run(s) en el bridge. La traza entera, desde la '
                'terminal: tail -f bridge/data/logs/bridge.jsonl',
                style: const TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 10.5,
                    height: 1.5,
                    color: AegisPalette.fgFaint)),
            const SizedBox(height: 12),
            for (final r in lista.take(40)) _RunFila(run: r),
          ],
        );
      },
    );
  }
}

class _RunFila extends StatelessWidget {
  const _RunFila({required this.run});

  final RunHistorial run;

  static Color _color(String estado) {
    if (estado == 'completed') return AegisPalette.ok;
    if (estado == 'failed') return AegisPalette.danger;
    return AegisPalette.warn;
  }

  @override
  Widget build(BuildContext context) {
    final herramientas = run.herramientas.take(4).join(' · ');
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              StatusLed(color: _color(run.estado), size: 7),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  run.proyecto.isEmpty ? '(sin proyecto)' : run.proyecto,
                  style: TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 12,
                    color: _color(run.estado),
                  ),
                ),
              ),
              Text(
                '${run.pasos} paso(s)',
                style: const TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 10,
                    color: AegisPalette.fgFaint),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            '${run.runId} · ${run.estado}'
            '${herramientas.isEmpty ? '' : ' · $herramientas'}',
            style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 10,
                height: 1.4,
                color: AegisPalette.fgDim),
          ),
          if (run.error.isNotEmpty)
            Text(
              run.error,
              style: const TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 10,
                  color: AegisPalette.danger),
            ),
        ],
      ),
    );
  }
}

class _Vacio extends StatelessWidget {
  const _Vacio({required this.conectadoA});

  final String conectadoA;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.all(16),
        child: Text(
          'Todavía no hay ningún run. Encarga uno en Ahora.\n\n'
          'Cada run deja su traza en el bridge, así que esta lista sobrevive '
          'a que apagues el portátil (esto no se guarda en el móvil).',
          style: const TextStyle(
              fontFamily: AegisPalette.mono, fontSize: 11.5, height: 1.5, color: AegisPalette.fgDim),
        ),
      );
}
