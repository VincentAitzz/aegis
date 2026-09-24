/// Línea de log de un evento: `[hh:mm:ss] marcador breve descripción`.
library;

import 'package:flutter/material.dart';

import '../../core/theme/dedsec_colors.dart';
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
                fontFamily: DedsecColors.mono,
                fontSize: 10,
                color: DedsecColors.fgFaint,
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
                fontFamily: DedsecColors.mono,
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
                fontFamily: DedsecColors.mono,
                fontSize: 13,
                height: 1.45,
                color: isMuted ? DedsecColors.fgFaint : DedsecColors.fg,
              ),
            ),
          ),
        ],
      ),
    );
  }

  (String, Color) get _marker => switch (event.type) {
        'task.created' => ('●', DedsecColors.info),
        'text.delta' => ('▸', DedsecColors.fg),
        'reasoning' => ('◈', DedsecColors.info),
        'tool.started' => ('>', DedsecColors.info),
        'tool.completed' => ('✓', DedsecColors.ok),
        'approval.request' => ('▲', DedsecColors.warn),
        'approval.resolved' => ('◆', DedsecColors.warn),
        'task.done' => ('■', DedsecColors.ok),
        'task.failed' => ('■', DedsecColors.danger),
        'task.stopped' => ('◼', DedsecColors.danger),
        _ => ('·', DedsecColors.fgFaint),
      };

  static String _fmtTime(String iso) {
    final t = DateTime.tryParse(iso);
    if (t == null) return '';
    String p(int v) => v.toString().padLeft(2, '0');
    return '${p(t.hour)}:${p(t.minute)}:${p(t.second)}';
  }
}