/// Página de aterrizaje: lanzar una tarea, elegir agente y ver el histórico.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

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

    return Scaffold(
      appBar: AppBar(
        title: const Text('Aegis Console'),
        actions: [
          IconButton(
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(builder: (_) => const ConnectivityPage()),
            ),
            icon: Icon(
              Icons.radar,
              color: health.when(
                data: (h) => h.ok ? Colors.green : Colors.redAccent,
                loading: () => Colors.amber,
                error: (_, _) => Colors.redAccent,
              ),
            ),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Formulario de lanzamiento
          Card(
            elevation: 0,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(16),
              side: BorderSide(color: Colors.grey.shade300),
            ),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Nueva tarea',
                      style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 12),
                  SegmentedButton<String>(
                    segments: const [
                      ButtonSegment(value: 'worker', label: Text('Worker')),
                      ButtonSegment(value: 'orchestrator', label: Text('Orquestador')),
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
                      hintText: 'Describe la tarea que debe ejecutar el agente…',
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 12),
                  if (_error != null)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: Text(_error!,
                          style: TextStyle(color: Theme.of(context).colorScheme.error)),
                    ),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                      onPressed: _busy ? null : _launch,
                      icon: _busy
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.rocket_launch),
                      label: Text(_busy ? 'Lanzando…' : 'Lanzar tarea'),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 18),
          // Salud del puente
          Row(
            children: [
              Icon(Icons.hub_outlined,
                  size: 16, color: Colors.grey.shade600),
              const SizedBox(width: 6),
              Text('Bridge: ${host.apiHost}:8000',
                  style: TextStyle(color: Colors.grey.shade600, fontSize: 12)),
            ],
          ),
          const SizedBox(height: 12),
          // Histórico
          Text('Recientes', style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 8),
          if (recent.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Text('Sin tareas todavía',
                  style: TextStyle(color: Colors.grey.shade500)),
            )
          else
            ...recent.map((runId) => ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.access_time),
                  title: Text(runId, style: const TextStyle(fontSize: 13, fontFamily: 'monospace')),
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
                )),
        ],
      ),
    );
  }
}