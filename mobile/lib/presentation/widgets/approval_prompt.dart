/// Tarjeta de aprobación pendiente con acción para confirmar/rechazar + comentario.
library;

import 'package:flutter/material.dart';

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

    return Card(
      margin: const EdgeInsets.fromLTRB(16, 8, 16, 12),
      elevation: 0,
      color: Theme.of(context).colorScheme.errorContainer.withValues(alpha: .18),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(color: Colors.orange.shade300.withValues(alpha: .6)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.gavel, color: Colors.orange.shade800, size: 20),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Aprobación requerida',
                    style: TextStyle(fontWeight: FontWeight.w700, color: Colors.orange.shade900),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text('Herramienta: $tool', style: const TextStyle(fontSize: 13)),
            if (reason is String && reason.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(reason, style: TextStyle(fontSize: 12.5, color: Colors.grey.shade700)),
            ],
            const SizedBox(height: 10),
            TextField(
              controller: _comment,
              minLines: 1,
              maxLines: 2,
              onChanged: (v) => setState(() => _commentText = v),
              decoration: const InputDecoration(
                isDense: true,
                hintText: 'Comentario (opcional)',
                border: OutlineInputBorder(),
                contentPadding: EdgeInsets.symmetric(horizontal: 10, vertical: 8),
              ),
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () =>
                        widget.onDecide('deny', comment: _commentText),
                    icon: const Icon(Icons.close, size: 16),
                    label: const Text('Rechazar'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: FilledButton.icon(
                    onPressed: () =>
                        widget.onDecide('approve', comment: _commentText),
                    icon: const Icon(Icons.check, size: 16),
                    label: const Text('Aprobar'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}