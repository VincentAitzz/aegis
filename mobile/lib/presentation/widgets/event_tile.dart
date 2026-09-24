/// Tile de un evento del feed (tool, delta, aprobación, terminal, ws.state).
library;

import 'package:flutter/material.dart';

import '../../data/models/agent_models.dart';

class EventTile extends StatelessWidget {
  const EventTile({super.key, required this.event});

  final AgentEvent event;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 5),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _icon(context),
          const SizedBox(width: 10),
          const SizedBox(width: 4, height: 18, child: VerticalDivider()),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  event.summary,
                  maxLines: 6,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 13.5, height: 1.35, color: _isMuted ? Colors.grey.shade500 : null),
                ),
                const SizedBox(height: 2),
                Text(
                  event.when,
                  style: TextStyle(fontSize: 10, color: Colors.grey.shade600),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  bool get _isMuted => const {'ws.status', 'raw.progress'}.contains(event.type);

  Widget _icon(BuildContext context) {
    final (icon, color) = switch (event.type) {
      'task.created' => (Icons.play_circle_outline, Colors.blueGrey),
      'text.delta' => (Icons.forum_outlined, Colors.teal),
      'reasoning' => (Icons.psychology_outlined, Colors.deepPurple),
      'tool.started' => (Icons.build_outlined, Colors.amber.shade800),
      'tool.completed' => (Icons.check_circle_outline, Colors.green),
      'approval.request' => (Icons.warning_amber_rounded, Colors.orange),
      'approval.resolved' => (Icons.thumbs_up_down_outlined, Colors.orange),
      'task.done' => (Icons.verified_outlined, Colors.green),
      'task.failed' => (Icons.error_outline, Colors.red),
      'task.stopped' => (Icons.stop_circle_outlined, Colors.red),
      'ws.status' => (Icons.wifi_outlined, Colors.blueGrey),
      _ => (Icons.circle, Colors.grey),
    };
    return Padding(
      padding: const EdgeInsets.only(top: 2),
      child: Icon(icon, size: 16, color: color),
    );
  }
}