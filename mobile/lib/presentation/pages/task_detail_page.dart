/// Misión en vivo: respuesta en streaming, feed, aprobaciones, steer y stop.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/aegis_palette.dart';
import '../../core/widgets/aegis_mark.dart';
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
  bool _escribiendo = false;
  String? _avisoEscritura;

  @override
  void dispose() {
    _steer.dispose();
    super.dispose();
  }

  /// Guarda la ficha con lo que el agente propuso.
  ///
  /// Va directo al bridge, **sin pasar por el modelo**: se comprobó que un 7B
  /// copiando un texto literal se come los `---` del frontmatter y deja la
  /// ficha sin tipo. La persona ya revisó el texto; aquí solo se guarda.
  Future<void> _aceptarPropuesta(String proyecto) async {
    final session = ref.read(taskSessionProvider);
    final contenido = (session?.finalText ?? '').trim();
    if (contenido.isEmpty || _escribiendo) return;
    setState(() {
      _escribiendo = true;
      _avisoEscritura = null;
    });
    try {
      final resultado = await ref.read(agentRepositoryProvider).writeFicha(
            alias: proyecto,
            contenido: contenido,
          );
      if (!mounted) return;
      setState(() {
        _escribiendo = false;
        _avisoEscritura = resultado.completa
            ? 'Ficha de $proyecto guardada. La puerta se abre.'
            : 'Guardada, pero sigue incompleta: faltan '
                '${resultado.faltan.join(', ')}';
      });
      ref.invalidate(projectsProvider);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _escribiendo = false;
        _avisoEscritura = 'No se pudo escribir: $e';
      });
    }
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
        appBar: AppBar(title: const Text('MISIÓN')),
        // Sin superposición: es la pantalla donde más texto técnico hay y donde
        // la textura más estorba.
        superposicion: false,
        body: const Center(
          child: Padding(
            padding: EdgeInsets.all(28),
            child: Text(
              'No hay ninguna misión en marcha.\nLánzala desde Ahora.',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 12,
                height: 1.6,
                color: AegisPalette.fgFaint,
              ),
            ),
          ),
        ),
      );
    }

    final terminal = const {'completed', 'failed', 'stopped'}.contains(session.status);
    final isLive = !terminal;

    return AegisScaffold(
      appBar: AppBar(
        title: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            AegisMark(size: 18, vivo: isLive),
            const SizedBox(width: 8),
            Text(isLive ? 'EN MARCHA' : 'MISIÓN'),
          ],
        ),
        actions: [
          if (isLive)
            IconButton(
              tooltip: 'Detener tarea',
              onPressed: () => ref.read(taskSessionProvider.notifier).stopTask(),
              icon: const Icon(Icons.stop_circle_outlined, color: AegisPalette.danger),
            ),
        ],
      ),
      superposicion: false,
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
                    _botonAceptar(session, isLive),
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
                        color: AegisPalette.bg2,
                        borderRadius: BorderRadius.circular(4),
                        border: Border.all(color: AegisPalette.line),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const StatusLed(color: AegisPalette.warn, size: 8, pulse: true),
                          const SizedBox(width: 6),
                          Text(
                            'ws: ${session.wsStatus}',
                            style: const TextStyle(fontFamily: AegisPalette.mono, fontSize: 10, color: AegisPalette.warn),
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
        color: AegisPalette.bg1,
        border: Border(bottom: BorderSide(color: AegisPalette.line)),
      ),
      child: Row(
        children: [
          AgentBadge(agent: session.task.agent),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              session.task.runId,
              style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 11.5,
                color: AegisPalette.fgDim,
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
      'running' => ('RUNNING', AegisPalette.voz),
      'completed' => ('COMPLETED', AegisPalette.ok),
      'failed' => ('FAILED', AegisPalette.danger),
      'stopped' => ('STOPPED', AegisPalette.warn),
      _ => ('QUEUED', AegisPalette.fgDim),
    };
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        StatusLed(color: color, size: 8, pulse: isLive),
        const SizedBox(width: 6),
        Text(
          label,
          style: TextStyle(
            fontFamily: AegisPalette.mono,
            fontSize: 10.5,
            letterSpacing: 1.5,
            color: color,
          ),
        ),
      ],
    );
  }

  /// "Escribir con autopilot": solo aparece con proyecto elegido, respuesta del
  /// agente no vacía y run terminado. Es el momento en que el humano ha leído
  /// lo que Aegis propone y decide si lo acepta.
  Widget _botonAceptar(AgentSession session, bool isLive) {
    final proyecto = ref.watch(selectedProjectProvider);
    if (proyecto.isEmpty || isLive || session.finalText.trim().isEmpty) {
      return const SizedBox.shrink();
    }
    final info = ref.watch(projectsProvider).asData?.value;
    final yaEscribible = info != null &&
        info.any((p) => p.alias == proyecto && p.escribible);
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_avisoEscritura != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(_avisoEscritura!,
                  style: TextStyle(
                      fontFamily: AegisPalette.mono,
                      fontSize: 10,
                      color: _avisoEscritura!.startsWith('No') 
                          ? AegisPalette.danger
                          : AegisPalette.ok)),
            ),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: _escribiendo
                  ? null
                  : () => _aceptarPropuesta(proyecto),
              icon: _escribiendo
                  ? const SizedBox(
                      width: 12, height: 12,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.edit_note_rounded, size: 18),
              label: Text(_escribiendo
                  ? 'ESCRIBIENDO…'
                  : yaEscribible
                      ? 'ESCRIBIR LA FICHA DE $proyecto'
                      : 'ESCRIBIR LA FICHA DE $proyecto CON AUTOPILOT'),
              style: OutlinedButton.styleFrom(
                foregroundColor: yaEscribible ? AegisPalette.ok : AegisPalette.brand,
                side: BorderSide(
                    color: yaEscribible ? AegisPalette.ok : AegisPalette.brand,
                    width: 1.2),
              ),
            ),
          ),
          const SizedBox(height: 4),
          Text(
            'Se guarda exactamente este texto, sin que ningún modelo lo toque. '
            'Revísalo antes: esto es lo que queda escrito.',
            style: const TextStyle(
                fontSize: 9, color: AegisPalette.fgFaint, height: 1.3),
          ),
        ],
      ),
    );
  }

  Widget _responsePanel(String finalText, bool isLive) {
    return HudPanel(
      title: 'SALIDA ▾',
      trailing: isLive ? const BlinkCursor(size: 12) : null,
      child: SelectableText(
        finalText,
        style: const TextStyle(
          fontFamily: AegisPalette.mono,
          fontSize: 13.5,
          height: 1.55,
          color: AegisPalette.fg,
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
        style: TextStyle(fontFamily: AegisPalette.mono, fontSize: 12, color: AegisPalette.fgFaint),
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
                foregroundColor: AegisPalette.brand,
                side: const BorderSide(color: AegisPalette.line),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(4)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
