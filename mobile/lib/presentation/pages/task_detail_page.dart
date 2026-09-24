/// Misión en vivo: respuesta en streaming, feed, aprobaciones, steer y stop.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/dedsec_colors.dart';
import '../../core/widgets/aegis_logo.dart';
import '../../core/widgets/aegis_scaffold.dart';
import '../../core/widgets/blink_cursor.dart';
import '../../core/widgets/hud_panel.dart';
import '../../core/widgets/status_led.dart';
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
      return AegisScaffold(
        appBar: AppBar(title: const Text('AEGIS')),
        body: const Center(
          child: Text(
            '// no hay misión activa — lanza una desde el control',
            style: TextStyle(fontFamily: DedsecColors.mono, fontSize: 12, color: DedsecColors.fgFaint),
          ),
        ),
      );
    }

    final terminal = const {'completed', 'failed', 'stopped'}.contains(session.status);
    final isLive = !terminal;

    return AegisScaffold(
      appBar: AppBar(
        title: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            AegisLogo(size: 18),
            SizedBox(width: 8),
            Text('MISIÓN EN VIVO'),
          ],
        ),
        actions: [
          if (isLive)
            IconButton(
              tooltip: 'Detener tarea',
              onPressed: () => ref.read(taskSessionProvider.notifier).stopTask(),
              icon: const Icon(Icons.stop_circle_outlined, color: DedsecColors.danger),
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
                    if (session.finalText.isNotEmpty)
                      _responsePanel(session.finalText, isLive)
                    else
                      _responsePlaceholder(),
                    const SizedBox(height: 8),
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
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                      decoration: BoxDecoration(
                        color: DedsecColors.bg2,
                        borderRadius: BorderRadius.circular(4),
                        border: Border.all(color: DedsecColors.line),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const StatusLed(color: DedsecColors.warn, size: 8, pulse: true),
                          const SizedBox(width: 6),
                          Text(
                            'ws: ${session.wsStatus}',
                            style: const TextStyle(fontFamily: DedsecColors.mono, fontSize: 10, color: DedsecColors.warn),
                          ),
                        ],
                      ),
                    ),
                  ),
              ],
            ),
          ),
          if (isLive) _steerBar(),
        ],
      ),
    );
  }

  Widget _header(AgentSession session) {
    final status = session.status;
    final isLive = !const {'completed', 'failed', 'stopped'}.contains(status);
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
      decoration: const BoxDecoration(
        color: DedsecColors.bg1,
        border: Border(bottom: BorderSide(color: DedsecColors.line)),
      ),
      child: Row(
        children: [
          AgentBadge(agent: session.task.agent),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              session.task.runId,
              style: const TextStyle(
                fontFamily: DedsecColors.mono,
                fontSize: 11.5,
                color: DedsecColors.fgDim,
              ),
              overflow: TextOverflow.ellipsis,
            ),
          ),
          const SizedBox(width: 8),
          _statusChip(status, isLive),
        ],
      ),
    );
  }

  Widget _statusChip(String status, bool isLive) {
    final (label, color) = switch (status) {
      'running' => ('RUNNING', DedsecColors.brand),
      'completed' => ('COMPLETED', DedsecColors.ok),
      'failed' => ('FAILED', DedsecColors.danger),
      'stopped' => ('STOPPED', DedsecColors.warn),
      _ => ('QUEUED', DedsecColors.fgDim),
    };
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        StatusLed(color: color, size: 8, pulse: isLive),
        const SizedBox(width: 6),
        Text(
          label,
          style: TextStyle(
            fontFamily: DedsecColors.mono,
            fontSize: 10.5,
            letterSpacing: 1.5,
            color: color,
          ),
        ),
      ],
    );
  }

  Widget _responsePanel(String finalText, bool isLive) {
    return HudPanel(
      title: 'SALIDA ▾',
      trailing: isLive ? const BlinkCursor(size: 12) : null,
      child: SelectableText(
        finalText,
        style: const TextStyle(
          fontFamily: DedsecColors.mono,
          fontSize: 13.5,
          height: 1.55,
          color: DedsecColors.fg,
        ),
      ),
    );
  }

  Widget _responsePlaceholder() {
    return HudPanel(
      title: 'SALIDA ▾',
      trailing: const BlinkCursor(size: 12),
      child: const Text(
        '// esperando datos del agente…',
        style: TextStyle(fontFamily: DedsecColors.mono, fontSize: 12, color: DedsecColors.fgFaint),
      ),
    );
  }

  Widget _steerBar() {
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
                  hintText: '\$ redirigir ▸',
                  contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                ),
                onSubmitted: _sendSteer,
              ),
            ),
            const SizedBox(width: 8),
            IconButton(
              onPressed: () => _sendSteer(_steer.text),
              icon: const Icon(Icons.send, size: 18),
              style: IconButton.styleFrom(
                foregroundColor: DedsecColors.brand,
                side: const BorderSide(color: DedsecColors.line),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(4)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}