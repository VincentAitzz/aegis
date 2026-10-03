/// Badge del agente. Aegis tiene uno solo, así que no hay color por rol.
library;

import 'package:flutter/material.dart';

import '../../core/theme/aegis_palette.dart';

class AgentBadge extends StatelessWidget {
  const AgentBadge({super.key, required this.agent});

  final String agent;

  @override
  Widget build(BuildContext context) {
    // `autopilot` es un motor, no un agente: se distingue por claridad, no por rol.
    final esAutopilot = agent == 'autopilot';
    final color = esAutopilot ? AegisPalette.voz : AegisPalette.ok;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: .10),
        borderRadius: BorderRadius.circular(3),
        border: Border.all(color: color.withValues(alpha: .55)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            esAutopilot ? '▤' : '▣',
            style: TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 10,
              color: color,
            ),
          ),
          const SizedBox(width: 6),
          Text(
            esAutopilot ? 'AUTOPILOT' : agent.toUpperCase(),
            style: TextStyle(
              fontFamily: AegisPalette.mono,
              color: color,
              fontWeight: FontWeight.w600,
              fontSize: 11,
              letterSpacing: 1.2,
            ),
          ),
        ],
      ),
    );
  }
}
