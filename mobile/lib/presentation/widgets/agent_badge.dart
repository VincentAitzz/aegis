/// Badge de agente estilo placa de circuito, color por rol.
library;

import 'package:flutter/material.dart';

import '../../core/theme/dedsec_colors.dart';

class AgentBadge extends StatelessWidget {
  const AgentBadge({super.key, required this.agent});

  final String agent;

  @override
  Widget build(BuildContext context) {
    final isWorker = agent == 'worker';
    final color = isWorker ? DedsecColors.ok : DedsecColors.brand;
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
            '▣',
            style: TextStyle(
              fontFamily: DedsecColors.mono,
              fontSize: 10,
              color: color,
            ),
          ),
          const SizedBox(width: 6),
          Text(
            agent.toUpperCase(),
            style: TextStyle(
              fontFamily: DedsecColors.mono,
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