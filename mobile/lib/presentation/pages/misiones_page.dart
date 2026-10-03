/// Misiones: el historial y el seguimiento.
///
/// ## Por qué el historial vive en el móvil y no en el bridge
/// Porque el bridge tiene una vida corta y esta lista no. La sesión de la app
/// guarda los `run_id` que has lanzado, y por eso sobrevive a que apagues el
/// portátil: cuando vuelvas, los ids siguen ahí.
///
/// Lo que **no** se guarda es el texto de la misión, ni el resultado, ni el
/// proyecto. Eso vive en el bridge y en el log de cada run; copiarlo al móvil
/// haría una segunda fuente de verdad para lo mismo, y la que se desincroniza
/// sin que nadie lo note.
///
/// ## Por qué no se puede abrir un run viejo
/// Abrir un id que no es la sesión activa haría entrar a `TaskDetailPage` sin
/// eventos: abriría una pantalla con el LED parpadeando y cero información. Es
/// el peor resultado posible —parece que está cargando— así que el móvil lo dice
/// en vez de fingir.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/aegis_palette.dart';
import '../../core/widgets/aegis_mark.dart';
import '../providers/agent_providers.dart';
import 'connectivity_page.dart';
import 'task_detail_page.dart';

class MisionesPage extends ConsumerWidget {
  const MisionesPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final recientes = ref.watch(recentTasksProvider);
    final activa = ref.watch(taskSessionProvider);
    final host = ref.watch(appConfigProvider);

    if (recientes.isEmpty) {
      return _Vacio(conectadoA: host.apiHost);
    }

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 28),
      children: [
        Row(
          children: [
            const Text(
              'Lanzadas desde este móvil',
              style: TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 10.5,
                letterSpacing: 1,
                color: AegisPalette.fgFaint,
              ),
            ),
            const Spacer(),
            if (activa != null)
              const Text(
                'una en marcha',
                style: TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 10,
                  color: AegisPalette.ok,
                ),
              ),
          ],
        ),
        const SizedBox(height: 12),
        for (final id in recientes)
          _MisionFila(
            runId: id,
            activa: activa?.task.runId == id,
            onTap: () {
              if (activa == null) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text(
                      'Esa misión no está en curso. Para verla en directo, '
                      'lanza una desde Ahora.',
                    ),
                  ),
                );
                return;
              }
              Navigator.of(context).push(
                MaterialPageRoute<void>(builder: (_) => const TaskDetailPage()),
              );
            },
          ),
        const SizedBox(height: 18),
        const Divider(),
        const SizedBox(height: 6),
        _EnlaceDiagnostico(host: host.apiHost),
      ],
    );
  }
}

class _MisionFila extends StatelessWidget {
  const _MisionFila({
    required this.runId,
    required this.activa,
    required this.onTap,
  });

  final String runId;
  final bool activa;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(6),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
          decoration: BoxDecoration(
            color: activa ? AegisPalette.bg2 : AegisPalette.bg1,
            borderRadius: BorderRadius.circular(6),
            border: Border.all(
              color: activa ? AegisPalette.brand.withValues(alpha: .5) : AegisPalette.line,
            ),
          ),
          child: Row(
            children: [
              Icon(
                activa ? Icons.play_circle_outline : Icons.circle_outlined,
                size: 15,
                color: activa ? AegisPalette.brand : AegisPalette.fgFaint,
              ),
              const SizedBox(width: 11),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      runId,
                      style: TextStyle(
                        fontFamily: AegisPalette.mono,
                        fontSize: 12,
                        color: activa ? AegisPalette.fg : AegisPalette.fgDim,
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: 2),
                    Text(
                      activa ? 'en marcha · toca para ver la traza' : 'terminada',
                      style: TextStyle(
                        fontFamily: AegisPalette.mono,
                        fontSize: 10,
                        color: activa ? AegisPalette.brand : AegisPalette.fgFaint,
                      ),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right, size: 16, color: AegisPalette.fgFaint),
            ],
          ),
        ),
      ),
    );
  }
}

/// Estado vacío. Un sitio vacío que no dice nada parece una app rota.
class _Vacio extends StatelessWidget {
  const _Vacio({required this.conectadoA});

  final String conectadoA;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            AegisMark(size: 46, color: AegisPalette.fgFaint),
            const SizedBox(height: 18),
            const Text(
              'Todavía no hemos hecho nada',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontFamily: AegisPalette.display,
                fontSize: 17,
                fontWeight: FontWeight.w600,
                letterSpacing: 2,
                color: AegisPalette.fg,
              ),
            ),
            const SizedBox(height: 10),
            const Text(
              'Las misiones que lances aparecerán aquí, con su traza.\n'
              'Por ahora estoy esperando.',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 12,
                height: 1.6,
                color: AegisPalette.fgDim,
              ),
            ),
            const SizedBox(height: 16),
            Text(
              'conectado a $conectadoA',
              style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 10,
                color: AegisPalette.fgFaint,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _EnlaceDiagnostico extends StatelessWidget {
  const _EnlaceDiagnostico({required this.host});

  final String host;

  @override
  Widget build(BuildContext context) {
    return TextButton.icon(
      onPressed: () => Navigator.of(context).push(
        MaterialPageRoute<void>(builder: (_) => const ConnectivityPage()),
      ),
      icon: const Icon(Icons.insights_outlined, size: 15, color: AegisPalette.fgDim),
      label: Text(
        'Ver el estado del puente ($host)',
        style: const TextStyle(
          fontFamily: AegisPalette.mono,
          fontSize: 11,
          color: AegisPalette.fgDim,
        ),
      ),
    );
  }
}
