/// Centro de control: lanzar misiones, elegir agente y ver el histórico.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/dedsec_colors.dart';
import '../../core/widgets/aegis_logo.dart';
import '../../core/widgets/aegis_scaffold.dart';
import '../../core/widgets/hud_panel.dart';
import '../../core/widgets/status_led.dart';
import '../providers/agent_providers.dart';
import 'connectivity_page.dart';
import 'task_detail_page.dart';

class HomePage extends ConsumerStatefulWidget {
  const HomePage({super.key});

  @override
  ConsumerState<HomePage> createState() => _HomePageState();
}

class _HomePageState extends ConsumerState<HomePage> {
  final _prompt = TextEditingController();
  bool _busy = false;
  String _agent = 'worker';
  String? _error;

  @override
  void dispose() {
    _prompt.dispose();
    super.dispose();
  }

  Future<void> _launch() async {
    final prompt = _prompt.text.trim();
    if (prompt.isEmpty) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final session = ref.read(taskSessionProvider.notifier);
      await session.createTask(agent: _agent, prompt: prompt);
      final task = ref.read(taskSessionProvider)?.task;
      if (task != null) {
        ref.read(recentTasksProvider.notifier).add(task.runId);
        if (mounted) {
          await Navigator.of(context).push(
            MaterialPageRoute<void>(builder: (_) => const TaskDetailPage()),
          );
        }
      }
    } catch (e) {
      setState(() => _error = 'No se pudo lanzar la tarea: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final health = ref.watch(healthProvider);
    final recent = ref.watch(recentTasksProvider);
    final host = ref.watch(appConfigProvider);

    return AegisScaffold(
      appBar: AppBar(
        title: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            AegisLogo(size: 20),
            SizedBox(width: 8),
            Text('AEGIS CONSOLE'),
          ],
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 10),
            child: IconButton(
              tooltip: 'Diagnóstico de malla',
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(builder: (_) => const ConnectivityPage()),
              ),
              icon: StatusLed(
                color: health.when(
                  data: (h) => h.ok ? DedsecColors.ok : DedsecColors.danger,
                  loading: () => DedsecColors.warn,
                  error: (_, _) => DedsecColors.danger,
                ),
                size: 11,
                pulse: health.isLoading,
              ),
            ),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          HudPanel(
            title: 'NUEVO ENCARGO',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SegmentedButton<String>(
                  segments: const [
                    ButtonSegment(value: 'worker', label: Text('WORKER')),
                    ButtonSegment(value: 'orchestrator', label: Text('ORQUESTADOR')),
                  ],
                  selected: {_agent},
                  onSelectionChanged: (set) =>
                      setState(() => _agent = set.first),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _prompt,
                  maxLines: 4,
                  minLines: 2,
                  decoration: const InputDecoration(
                    hintText: '// describe la misión para el agente…',
                  ),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 10),
                  Text(
                    '! $_error',
                    style: const TextStyle(
                      fontFamily: DedsecColors.mono,
                      fontSize: 12,
                      color: DedsecColors.danger,
                    ),
                  ),
                ],
                const SizedBox(height: 12),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                    onPressed: _busy ? null : _launch,
                    icon: _busy
                        ? const SizedBox(
                            width: 14,
                            height: 14,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.play_arrow_rounded, size: 18),
                    label: Text(_busy ? 'EJECUTANDO…' : 'EJECUTAR  ▶'),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              const Text(
                'aegis@mesh:~\$',
                style: TextStyle(fontFamily: DedsecColors.mono, fontSize: 11, color: DedsecColors.fgFaint),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  '${host.apiHost}:8000',
                  style: const TextStyle(fontFamily: DedsecColors.mono, fontSize: 11, color: DedsecColors.fgDim),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          HudPanel(
            title: 'MISIONES RECIENTES',
            child: recent.isEmpty
                ? const Padding(
                    padding: EdgeInsets.symmetric(vertical: 6),
                    child: Text(
                      '// sin misiones registradas',
                      style: TextStyle(fontFamily: DedsecColors.mono, fontSize: 12, color: DedsecColors.fgFaint),
                    ),
                  )
                : Column(
                    children: [
                      for (var i = 0; i < recent.length; i++) ...[
                        if (i > 0) const Divider(height: 1),
                        _RecentRow(
                          runId: recent[i],
                          onTap: () {
                            if (ref.read(taskSessionProvider) != null) {
                              Navigator.of(context).push(
                                MaterialPageRoute<void>(builder: (_) => const TaskDetailPage()),
                              );
                            } else {
                              ScaffoldMessenger.of(context).showSnackBar(
                                const SnackBar(content: Text('Lanza una nueva tarea para ver el seguimiento.')),
                              );
                            }
                          },
                        ),
                      ],
                    ],
                  ),
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}

class _RecentRow extends StatelessWidget {
  const _RecentRow({required this.runId, required this.onTap});

  final String runId;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 10),
        child: Row(
          children: [
            const Text(
              '▸',
              style: TextStyle(fontFamily: DedsecColors.mono, fontSize: 12, color: DedsecColors.brand),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                runId,
                style: const TextStyle(fontFamily: DedsecColors.mono, fontSize: 12.5, color: DedsecColors.fgDim),
                overflow: TextOverflow.ellipsis,
              ),
            ),
            const Text(
              '▸ open',
              style: TextStyle(fontFamily: DedsecColors.mono, fontSize: 10, color: DedsecColors.fgFaint),
            ),
          ],
        ),
      ),
    );
  }
}