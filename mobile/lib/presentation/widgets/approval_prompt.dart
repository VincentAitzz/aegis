/// Panel de autorización requerida estilo alerta DedSec.
library;

import 'package:flutter/material.dart';

import '../../core/theme/dedsec_colors.dart';
import '../../data/models/agent_models.dart';

class ApprovalPrompt extends StatefulWidget {
  const ApprovalPrompt({super.key, required this.event, required this.onDecide});

  final AgentEvent event;
  final void Function(String decision, {String? comment}) onDecide;

  @override
  State<ApprovalPrompt> createState() => _ApprovalPromptState();
}

class _ApprovalPromptState extends State<ApprovalPrompt> {
  final _comment = TextEditingController();
  String _commentText = '';

  @override
  void dispose() {
    _comment.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final data = widget.event.payload['data'];
    final map = data is Map ? data : const <String, dynamic>{};
    final tool = map['tool'] ?? widget.event.payload['event'] ?? 'herramienta';
    final reason = map['reason'] ?? map['context'] ?? '';

    return Container(
      margin: const EdgeInsets.fromLTRB(16, 8, 16, 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: DedsecColors.warn.withValues(alpha: .06),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: DedsecColors.warn.withValues(alpha: .55)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Text(
                '▲',
                style: TextStyle(fontFamily: DedsecColors.mono, fontSize: 14, color: DedsecColors.warn),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'AUTORIZACIÓN REQUERIDA',
                  style: TextStyle(
                    fontFamily: DedsecColors.mono,
                    fontSize: 12,
                    letterSpacing: 2,
                    fontWeight: FontWeight.w700,
                    color: DedsecColors.warn,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            '> accion: $tool',
            style: const TextStyle(fontFamily: DedsecColors.mono, fontSize: 12, color: DedsecColors.fg),
          ),
          if (reason is String && reason.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              reason,
              style: const TextStyle(fontFamily: DedsecColors.mono, fontSize: 11.5, color: DedsecColors.fgDim),
            ),
          ],
          const SizedBox(height: 10),
          TextField(
            controller: _comment,
            minLines: 1,
            maxLines: 2,
            onChanged: (v) => setState(() => _commentText = v),
            decoration: const InputDecoration(
              isDense: true,
              hintText: '\$ comentario ▸ (opcional)',
              contentPadding: EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            ),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: () => widget.onDecide('deny', comment: _commentText),
                  icon: const Icon(Icons.close, size: 15),
                  label: const Text('RECHAZAR'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: DedsecColors.danger,
                    side: BorderSide(color: DedsecColors.danger.withValues(alpha: .6)),
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: FilledButton.icon(
                  onPressed: () => widget.onDecide('approve', comment: _commentText),
                  icon: const Icon(Icons.check, size: 15),
                  label: const Text('AUTORIZAR'),
                  style: FilledButton.styleFrom(
                    backgroundColor: DedsecColors.ok,
                    foregroundColor: const Color(0xFF031207),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}