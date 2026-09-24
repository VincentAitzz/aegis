/// Badge del agente (worker/orchestrator) con color por rol.
library;

import 'package:flutter/material.dart';

class AgentBadge extends StatelessWidget {
  const AgentBadge({super.key, required this.agent});

  final String agent;

  @override
  Widget build(BuildContext context) {
    final isWorker = agent == 'worker';
    final color = isWorker ? Colors.teal : Colors.indigo;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: .14),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withValues(alpha: .45)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.smart_toy, size: 14, color: color),
          const SizedBox(width: 6),
          Text(
            agent,
            style: TextStyle(
              color: color,
              fontWeight: FontWeight.w600,
              fontSize: 12,
              letterSpacing: .4,
            ),
          ),
        ],
      ),
    );
  }
}