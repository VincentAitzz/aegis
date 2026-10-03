/// Memoria: lo que Aegis recuerda, y lo que quieres que olvide.
///
/// ## Por qué esto muestra tan poco
/// Aegis guarda el prompt que le escribiste y su respuesta. Aquí **no se
/// enseñan**: se ve qué hizo, cuándo, con cuántas herramientas y si se resolvió.
/// El texto se queda en el almacén del bridge.
///
/// ## Por qué es una decisión y no una comodidad
/// Todo lo que le cuentas a Aegis queda a un `GET` de distancia de cualquier otra
/// cosa en tu red privada. Mostrar el texto aquí no añade información útil —para
/// saber qué hizo, el metadato ya lo dice— y sí añade exposición. Por eso el
/// botón de borrar está en la misma pantalla que la lista: un historial que se
/// puede limpiar desde donde se mira es la condición para que exista.
///
/// ## Por qué solo `success`
/// El endpoint ya filtra los episodios que no se resolvieron. Se debe a A-016:
/// un fallo presentado bajo "resueltos antes" es instrucción contraria, y el
/// modelo la copia. Está medido —con tres episodios falsos, el tool calling bajó
/// de 7/8 a 0/8— así que el filtro va en el puente y no en la pantalla.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/aegis_palette.dart';
import '../../core/widgets/aegis_mark.dart';
import '../../core/widgets/hud_panel.dart';
import '../../data/models/asistente_models.dart';
import '../providers/agent_providers.dart';

class MemoriaPage extends ConsumerWidget {
  const MemoriaPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final memoria = ref.watch(memoriaProvider);
    final runs = ref.watch(runsProvider);

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 28),
      children: [
        memoria.when(
          loading: () => const Padding(
            padding: EdgeInsets.symmetric(vertical: 40),
            child: Center(
              child: Text('revisando qué recuerdo…',
                  style: TextStyle(
                      fontFamily: AegisPalette.mono,
                      fontSize: 12,
                      color: AegisPalette.fgFaint)),
            ),
          ),
          error: (e, _) => HudPanel(
            title: 'MEMORIA',
            accent: AegisPalette.danger,
            child: Text('no pude leerla: $e',
                style: const TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 12,
                    color: AegisPalette.danger,
                    height: 1.5)),
          ),
          data: (m) => m.episodios.isEmpty
              ? const _Vacia()
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    HudPanel(
                      title: 'LO QUE RECUERDO',
                      child: Text(
                        'Solo lo que se resolvió de verdad. Lo que salió mal no '
                        'se guarda como si hubiera funcionado, porque una '
                        'solución que no funcionó enseñada como solución es una '
                        'instrucción contraria.',
                        style: const TextStyle(
                          fontFamily: AegisPalette.mono,
                          fontSize: 10.5,
                          height: 1.55,
                          color: AegisPalette.fgFaint,
                        ),
                      ),
                    ),
                    if (m.nota.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      Text(
                        m.nota,
                        style: const TextStyle(
                          fontFamily: AegisPalette.mono,
                          fontSize: 10,
                          height: 1.5,
                          color: AegisPalette.fgFaint,
                        ),
                      ),
                    ],
                    const SizedBox(height: 12),
                    for (final e in m.episodios) _EpisodioFila(episodio: e),
                  ],
                ),
        ),
        const SizedBox(height: 20),
        const Divider(),
        const SizedBox(height: 14),
        Text(
          'Todo lo que ha hecho',
          style: const TextStyle(
            fontFamily: AegisPalette.mono,
            fontSize: 10.5,
            letterSpacing: 1,
            color: AegisPalette.fgFaint,
          ),
        ),
        const SizedBox(height: 10),
        runs.when(
          loading: () => const Text('…',
              style: TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 12,
                  color: AegisPalette.fgFaint)),
          error: (e, _) => Text('$e',
              style: const TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 11,
                  color: AegisPalette.danger)),
          data: (lista) => lista.isEmpty
              ? const Text('No hay runs registrados todavía.',
                  style: TextStyle(
                      fontFamily: AegisPalette.mono,
                      fontSize: 11.5,
                      color: AegisPalette.fgFaint))
              : Column(
                  children: [
                    for (final r in lista.take(25)) _RunFila(run: r),
                  ],
                ),
        ),
      ],
    );
  }
}

class _EpisodioFila extends StatelessWidget {
  const _EpisodioFila({required this.episodio});

  final Episodio episodio;

  @override
  Widget build(BuildContext context) {
    final tools = episodio.herramientas;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(
          color: AegisPalette.bg1,
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: AegisPalette.line),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.check_circle_outline, size: 13, color: AegisPalette.ok),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    tools.isEmpty ? 'sin herramientas' : tools.join(', '),
                    style: const TextStyle(
                      fontFamily: AegisPalette.mono,
                      fontSize: 11.5,
                      color: AegisPalette.fg,
                    ),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                Text(
                  '${episodio.pasos} paso${episodio.pasos == 1 ? '' : 's'}',
                  style: const TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 10,
                    color: AegisPalette.fgFaint,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 3),
            Text(
              episodio.proyecto.isEmpty
                  ? episodio.runId
                  : '${episodio.proyecto} · ${episodio.runId}',
              style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 10,
                color: AegisPalette.fgFaint,
              ),
              overflow: TextOverflow.ellipsis,
            ),
          ],
        ),
      ),
    );
  }
}

class _RunFila extends StatelessWidget {
  const _RunFila({required this.run});

  final RunHistorial run;

  @override
  Widget build(BuildContext context) {
    final fallo = run.fallo;
    final color = fallo ? AegisPalette.danger : AegisPalette.ok;
    final tools = run.herramientas;
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
        decoration: BoxDecoration(
          color: AegisPalette.bg1,
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: AegisPalette.line),
        ),
        child: Row(
          children: [
            Icon(
              fallo ? Icons.error_outline : Icons.check_circle_outline,
              size: 13,
              color: color,
            ),
            const SizedBox(width: 9),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    run.proyecto.isEmpty
                        ? tools.isEmpty
                            ? 'sin herramientas'
                            : tools.take(3).join(', ')
                        : run.proyecto,
                    style: const TextStyle(
                      fontFamily: AegisPalette.mono,
                      fontSize: 12,
                      color: AegisPalette.fg,
                    ),
                    overflow: TextOverflow.ellipsis,
                  ),
                  const SizedBox(height: 2),
                  Text(
                    run.runId,
                    style: const TextStyle(
                      fontFamily: AegisPalette.mono,
                      fontSize: 9.5,
                      color: AegisPalette.fgFaint,
                    ),
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
            const SizedBox(width: 8),
            Text(
              '${run.pasos}',
              style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 11,
                color: AegisPalette.fgDim,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Vacia extends StatelessWidget {
  const _Vacia();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 40),
      child: Column(
        children: [
          AegisMark(size: 44, color: AegisPalette.fgFaint),
          const SizedBox(height: 16),
          const Text(
            'Todavía no recuerdo nada',
            style: TextStyle(
              fontFamily: AegisPalette.display,
              fontSize: 16,
              fontWeight: FontWeight.w600,
              letterSpacing: 2,
              color: AegisPalette.fg,
            ),
          ),
          const SizedBox(height: 10),
          const Text(
            'Empiezo a recordar cuando una misión\ntermine saliendo bien.',
            textAlign: TextAlign.center,
            style: TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 11.5,
              height: 1.6,
              color: AegisPalette.fgFaint,
            ),
          ),
        ],
      ),
    );
  }
}