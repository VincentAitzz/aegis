/// Página de seguimiento en vivo de la tarea activa (feed, aprobaciones, steer).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/agent_providers.dart';
import '../widgets/agent_badge.dart';
import '../widgets/approval_prompt.dart';
import '../widgets/event_tile.dart';

class TaskDetailPage extends ConsumerStatefulWidget {
  const TaskDetailPage({super.key});

  @override
  ConsumerState<TaskDetailPage> createState() => _TaskDetailPageState();
}

class _TaskDetailPageState extends ConsumerState<TaskDetailPage> {
  final _steer = TextEditingController();

  @override
  void dispose() {
    _steer.dispose();
    super.dispose();
  }

  void _sendSteer(String text) {
    if (text.trim().isEmpty) return;
    ref.read(taskSessionProvider.notifier).steerTo(text.trim());
    _steer.clear();
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(taskSessionProvider);

    if (session == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Tarea')),
        body: const Center(child: Text('No hay tarea activa. Lanza una desde el inicio.')),
      );
    }

    final terminal = const {'completed', 'failed', 'stopped'}.contains(session.status);
    final isLive = !terminal;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Seguimiento de tarea'),
        actions: [
          if (isLive)
            IconButton(
              tooltip: 'Detener tarea',
              onPressed: () => ref.read(taskSessionProvider.notifier).stopTask(),
              icon: const Icon(Icons.stop_circle_outlined, color: Colors.redAccent),
            ),
        ],
      ),
      body: Column(
        children: [
          _header(session),
          Expanded(
            child: Stack(
              children: [
                ListView(
                  padding: const EdgeInsets.only(bottom: 24),
                  children: [
                    if (session.finalText.isNotEmpty) _answerCard(session),
                    const SizedBox(height: 8),
                    _statusChip(session, context),
                    if (session.pendingApproval != null) ...[
                      const SizedBox(height: 8),
                      ApprovalPrompt(
                        event: session.pendingApproval!,
                        onDecide: (decision, {comment}) => ref
                            .read(taskSessionProvider.notifier)
                            .approve(decision, comment: comment),
                      ),
                    ],
                    const SizedBox(height: 8),
                    for (final ev in session.events.reversed) EventTile(event: ev),
                  ],
                ),
                if (isLive &&
                    (session.wsStatus == 'connecting' ||
                        session.wsStatus == 'reconnecting'))
                  Positioned(
                    top: 8,
                    right: 16,
                    child: Chip(
                      avatar: const SizedBox(
                        width: 12,
                        height: 12,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                      label:
                          Text(session.wsStatus, style: const TextStyle(fontSize: 11)),
                      visualDensity: VisualDensity.compact,
                    ),
                  ),
              ],
            ),
          ),
          if (isLive) _steerBar(session),
        ],
      ),
    );
  }

  Widget _header(AgentSession session) {
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
      decoration: BoxDecoration(
        color: Colors.grey.shade50,
        border: Border(bottom: BorderSide(color: Colors.grey.shade200)),
      ),
      child: Row(
        children: [
          AgentBadge(agent: session.task.agent),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              session.task.runId,
              style: const TextStyle(fontSize: 12, fontFamily: 'monospace'),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }

  Widget _answerCard(AgentSession session) {
    return Card(
      margin: const EdgeInsets.fromLTRB(16, 8, 16, 8),
      elevation: 0,
      color: Colors.teal.shade50,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(color: Colors.teal.shade200),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Text(
          session.finalText,
          style: const TextStyle(fontSize: 14.5, height: 1.4),
        ),
      ),
    );
  }

  Widget _statusChip(AgentSession session, BuildContext context) {
    final (bg, fg, label) = switch (session.status) {
      'running' => (Colors.blue.shade100, Colors.blue.shade900, 'ejecutando'),
      'completed' => (Colors.green.shade100, Colors.green.shade900, 'completada'),
      'failed' => (Colors.red.shade100, Colors.red.shade900, 'fallada'),
      'stopped' => (Colors.orange.shade100, Colors.orange.shade900, 'detenida'),
      _ => (Colors.grey.shade200, Colors.grey.shade800, 'iniciando'),
    };
    return Align(
      alignment: Alignment.centerLeft,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Chip(
          backgroundColor: bg,
          label: Text(label,
              style: TextStyle(
                  color: fg, fontSize: 12, fontWeight: FontWeight.w600)),
          visualDensity: VisualDensity.compact,
        ),
      ),
    );
  }

  Widget _steerBar(AgentSession session) {
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 6, 12, 10),
        child: Row(
          children: [
            Expanded(
              child: TextField(
                controller: _steer,
                decoration: const InputDecoration(
                  isDense: true,
                  hintText: 'Redirigir al agente…',
                  border: OutlineInputBorder(),
                  contentPadding:
                      EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                ),
                onSubmitted: _sendSteer,
              ),
            ),
            const SizedBox(width: 8),
            IconButton.filledTonal(
              onPressed: () => _sendSteer(_steer.text),
              icon: const Icon(Icons.send),
            ),
          ],
        ),
      ),
    );
  }
}