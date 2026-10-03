/// Una línea del feed de eventos: hora, marcador y qué pasó.
///
/// ## Por qué los marcadores son glifos y no colores
/// El color dice si va bien o mal; el glifo dice **qué clase de evento** es. En
/// una traza larga, buscar "¿qué paso aquí?" por color obliga a leer cada línea;
/// un glifo distinto por tipo se distingue a un vistazo. Los dos juntos dan el
/// estado y el tipo, que son dos preguntas distintas.
library;

import 'package:flutter/material.dart';

import '../../core/theme/aegis_palette.dart';
import '../../data/models/agent_models.dart';

class EventTile extends StatelessWidget {
  const EventTile({super.key, required this.event});

  final AgentEvent event;

  @override
  Widget build(BuildContext context) {
    final isMuted = const {'ws.status', 'raw.progress'}.contains(event.type);
    final (mark, color) = _marker;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 74,
            child: Text(
              _fmtTime(event.when),
              style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 10,
                color: AegisPalette.fgFaint,
                height: 1.5,
              ),
            ),
          ),
          const SizedBox(width: 6),
          SizedBox(
            width: 14,
            child: Text(
              mark,
              style: TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 12,
                height: 1.35,
                color: color,
              ),
            ),
          ),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              event.summary,
              maxLines: 6,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 13,
                height: 1.45,
                color: isMuted ? AegisPalette.fgFaint : AegisPalette.fg,
              ),
            ),
          ),
        ],
      ),
    );
  }

  (String, Color) get _marker => switch (event.type) {
        'task.created' => ('●', AegisPalette.info),
        'text.delta' => ('▸', AegisPalette.fg),
        'reasoning' => ('◈', AegisPalette.info),
        'tool.started' => ('>', AegisPalette.info),
        'tool.completed' => ('✓', AegisPalette.ok),
        'approval.request' => ('▲', AegisPalette.warn),
        'approval.resolved' => ('◆', AegisPalette.warn),
        'task.done' => ('■', AegisPalette.ok),
        'task.failed' => ('■', AegisPalette.danger),
        'task.stopped' => ('◼', AegisPalette.danger),
        _ => ('·', AegisPalette.fgFaint),
      };

  static String _fmtTime(String iso) {
    final t = DateTime.tryParse(iso);
    if (t == null) return '';
    String p(int v) => v.toString().padLeft(2, '0');
    return '${p(t.hour)}:${p(t.minute)}:${p(t.second)}';
  }
}
