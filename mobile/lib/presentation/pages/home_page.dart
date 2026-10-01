/// Centro de control: lanzar misiones, elegir motor y ver el histórico.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/dedsec_colors.dart';
import '../../core/widgets/aegis_logo.dart';
import '../../core/widgets/aegis_scaffold.dart';
import '../../core/widgets/hud_panel.dart';
import '../../core/widgets/status_led.dart';
import '../../data/models/agent_models.dart';
import '../providers/agent_providers.dart';
import 'connectivity_page.dart';
import 'task_detail_page.dart';

/// Aegis tiene un solo agente. Antes había un selector worker/orchestrator, pero
/// los dos acababan en el mismo modelo: era una elección que no elegía nada.
const String kAegisAgent = 'worker';

class HomePage extends ConsumerStatefulWidget {
  const HomePage({super.key});

  @override
  ConsumerState<HomePage> createState() => _HomePageState();
}

class _HomePageState extends ConsumerState<HomePage> {
  final _prompt = TextEditingController();
  bool _busy = false;
  bool _useAutopilot = false;
  String? _error;

  /// Último run de autopilot en curso, para no perder la traza al rotar.
  AutopilotRun? _autopilotRun;
  Timer? _poll;

  @override
  void dispose() {
    _prompt.dispose();
    _poll?.cancel();
    super.dispose();
  }

  void _stopPolling() {
    _poll?.cancel();
    _poll = null;
  }

  /// Autopilot no tiene WS: se consulta hasta que el run termina.
  ///
  /// Cada tool aparece en la traza en cuanto se ejecutó, así que el usuario ve
  /// qué está pasando en vez de mirar un spinner dos minutos.
  Future<void> _pollAutopilot(String runId) async {
    final repo = ref.read(agentRepositoryProvider);
    try {
      final run = await repo.autopilotStatus(runId);
      if (!mounted) return;
      setState(() => _autopilotRun = run);
      if (run.finished) {
        _stopPolling();
        return;
      }
      _poll = Timer(const Duration(seconds: 3), () => _pollAutopilot(runId));
    } catch (e) {
      if (!mounted) return;
      _stopPolling();
      setState(() => _error = 'Se perdió el seguimiento del run: $e');
    }
  }

  Future<void> _launchAutopilot(String prompt) async {
    final repo = ref.read(agentRepositoryProvider);
    final proyecto = ref.read(selectedProjectProvider);
    final runId = await repo.startAutopilot(
      prompt: prompt,
      project: proyecto.isEmpty ? null : proyecto,
      maxSteps: 6,
      verify: false,
    );
    if (!mounted) return;
    setState(() => _autopilotRun = null);
    _stopPolling();
    await _pollAutopilot(runId);
  }

  Future<void> _launch() async {
    final prompt = _prompt.text.trim();
    if (prompt.isEmpty) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      if (_useAutopilot) {
        await _launchAutopilot(prompt);
        return;
      }
      final session = ref.read(taskSessionProvider.notifier);
      final proyecto = ref.read(selectedProjectProvider);
      await session.createTask(
        agent: kAegisAgent,
        prompt: prompt,
        project: proyecto.isEmpty ? null : proyecto,
      );
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
                const SizedBox(height: 14),
                _ProjectSelector(
                  seleccionado: ref.watch(selectedProjectProvider),
                  onChanged: (alias) =>
                      ref.read(selectedProjectProvider.notifier).select(alias),
                ),
                const SizedBox(height: 14),
                SegmentedButton<String>(
                  segments: const [
                    ButtonSegment(value: 'hermes', label: Text('HERMES')),
                    ButtonSegment(value: 'autopilot', label: Text('AUTOPILOT')),
                  ],
                  selected: {_useAutopilot ? 'autopilot' : 'hermes'},
                  onSelectionChanged: (set) => setState(
                      () => _useAutopilot = set.first == 'autopilot'),
                ),
                const SizedBox(height: 6),
                Text(
                  _useAutopilot
                      ? 'Ejecuta tools de verdad con lista blanca. La traza va apareciendo paso a paso.'
                      : 'Razona y conversa. Para trabajar sobre archivos, usa AUTOPILOT.',
                  style: const TextStyle(fontSize: 10, color: DedsecColors.fgDim),
                ),
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
          if (_autopilotRun != null) ...[
            const SizedBox(height: 16),
            _AutopilotTrace(run: _autopilotRun!),
          ],
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
/// Traza de un run de autopilot.
///
/// Muestra lo que el bridge EJECUTÓ, no lo que el agente cuenta que hizo. Un run
/// sin ninguna tool en la traza se dice explícitamente: es la diferencia entre
/// "terminó" y "hizo algo".
class _AutopilotTrace extends StatelessWidget {
  const _AutopilotTrace({required this.run});

  final AutopilotRun run;

  @override
  Widget build(BuildContext context) {
    final color = run.status == 'failed' ? DedsecColors.danger : DedsecColors.ok;
    return HudPanel(
      title: 'AUTOPILOT · ${run.status.toUpperCase()}',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            run.executedAnything
                ? '${run.tools.length} tool(s) ejecutada(s) · ${run.steps} paso(s)'
                    '${run.fin != null ? ' · fin: ${run.fin}' : ''}'
                : 'SIN HERRAMIENTAS EJECUTADAS: el agente respondió sin tocar nada.',
            style: TextStyle(
              fontFamily: DedsecColors.mono,
              fontSize: 11,
              color: run.executedAnything ? DedsecColors.fgDim : DedsecColors.warn,
            ),
          ),
          if (run.error != null) ...[
            const SizedBox(height: 6),
            Text('! ${run.error}',
                style: const TextStyle(
                    fontFamily: DedsecColors.mono,
                    fontSize: 11,
                    color: DedsecColors.danger)),
          ],
          const SizedBox(height: 8),
          for (final step in run.trace) ...[
            Text('paso ${step.step}: ${step.summary}',
                style: TextStyle(
                    fontFamily: DedsecColors.mono,
                    fontSize: 11,
                    color: step.failed ? DedsecColors.danger : DedsecColors.ok)),
            if (step.result != null)
              Padding(
                padding: const EdgeInsets.only(left: 10, top: 2),
                child: Text(
                  step.result!.replaceAll('\n', '  ').substring(
                      0, step.result!.length < 160 ? step.result!.length : 160),
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                      fontFamily: DedsecColors.mono,
                      fontSize: 10,
                      color: DedsecColors.fgFaint),
                ),
              ),
          ],
          if (run.answer != null && run.answer!.isNotEmpty) ...[
            const SizedBox(height: 10),
            const Text('—',
                style: TextStyle(
                    fontFamily: DedsecColors.mono,
                    fontSize: 11,
                    color: DedsecColors.fgFaint)),
            Text(run.answer!,
                style: const TextStyle(
                    fontFamily: DedsecColors.mono,
                    fontSize: 11,
                    color: DedsecColors.fgDim)),
          ],
          const SizedBox(height: 6),
          Row(
            children: [
              Icon(Icons.circle, size: 8, color: color),
              const SizedBox(width: 6),
              Text(
                run.running ? 'ejecutando…' : 'run ${run.runId}',
                style: const TextStyle(
                    fontFamily: DedsecColors.mono,
                    fontSize: 10,
                    color: DedsecColors.fgFaint),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Selector de proyecto del workspace, coloreado por el estado de su ficha.
///
/// El color no es decoración: `sin_ficha` en rojo significa que **la puerta va
/// a negar cualquier escritura** en ese proyecto. Verlo aquí evita la sorpresa
/// de lanzar una misión y que Aegis se niegue tres pasos después.
class _ProjectSelector extends ConsumerWidget {
  const _ProjectSelector({required this.seleccionado, required this.onChanged});

  final String seleccionado;
  final ValueChanged<String> onChanged;

  static Color _color(ProjectInfo p) {
    if (p.completa) return DedsecColors.ok;
    if (p.parcial) return DedsecColors.warn;
    return DedsecColors.danger;
  }

  static String _globo(ProjectInfo p) {
    if (p.completa) return 'ficha completa · Aegis puede escribir';
    if (p.sinFicha) return 'SIN FICHA · Aegis no puede escribir aquí';
    return 'incompleta, faltan ${p.faltan.length} secciones';
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final proyectos = ref.watch(projectsProvider);
    return proyectos.when(
      loading: () => const Text('proyectos…',
          style: TextStyle(
              fontFamily: DedsecColors.mono, fontSize: 11, color: DedsecColors.fgFaint)),
      error: (e, _) => Text('no pude leer los proyectos: $e',
          style: const TextStyle(
              fontFamily: DedsecColors.mono, fontSize: 10, color: DedsecColors.danger)),
      data: (lista) {
        if (lista.isEmpty) {
          return const Text('sin proyectos',
              style: TextStyle(
                  fontFamily: DedsecColors.mono, fontSize: 11, color: DedsecColors.warn));
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final p in lista)
                  _pastilla(p, seleccionado == p.alias, () => onChanged(p.alias)),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              seleccionado.isEmpty
                  ? 'Sin proyecto: Aegis razona sin saber de qué se trata.'
                  : _globo(lista.firstWhere((p) => p.alias == seleccionado,
                      orElse: () => lista.first)),
              style: const TextStyle(
                  fontSize: 10, color: DedsecColors.fgFaint, height: 1.3),
            ),
          ],
        );
      },
    );
  }

  Widget _pastilla(ProjectInfo p, bool activo, void Function() tap) {
    final color = _color(p);
    return GestureDetector(
      onTap: tap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
        decoration: BoxDecoration(
          color: color.withValues(alpha: activo ? .22 : .08),
          borderRadius: BorderRadius.circular(3),
          border: Border.all(
              color: color.withValues(alpha: activo ? 1 : .5), width: activo ? 1.6 : 1),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(width: 6, height: 6,
                decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
            const SizedBox(width: 6),
            Text(p.alias,
                style: TextStyle(
                    fontFamily: DedsecColors.mono,
                    fontSize: 11,
                    fontWeight: activo ? FontWeight.w700 : FontWeight.w500,
                    color: color)),
          ],
        ),
      ),
    );
  }
}
