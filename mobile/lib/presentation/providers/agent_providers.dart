/// Providers Riverpod de la capa presentación (DI + estado reactivo).
library;

import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/config/app_config.dart';
import '../../data/models/agent_models.dart';
import '../../data/repositories/agent_repository_impl.dart';
import '../../domain/repositories/agent_repository.dart';

// -- DI ---------------------------------------------------------------------
final appConfigProvider = Provider<AppConfig>((ref) => AppConfig.fromEnvironment());

final agentRepositoryProvider = Provider<AgentRepository>((ref) {
  return AgentRepositoryImpl(config: ref.watch(appConfigProvider));
});

final healthProvider = FutureProvider<BridgeHealth>((ref) {
  return ref.watch(agentRepositoryProvider).health();
});

final modelsProvider = FutureProvider<List<String>>((ref) {
  return ref.watch(agentRepositoryProvider).models();
});

/// Proyectos del workspace con el estado de su ficha. Es lo que pinta el
/// selector: un proyecto sin ficha sale en rojo porque Aegis no puede escribir
/// en él todavía, y eso conviene verlo **antes** de pedirle una misión, no
/// después de que se niegue.
final projectsProvider = FutureProvider<List<ProjectInfo>>((ref) {
  return ref.watch(agentRepositoryProvider).projects();
});

/// Proyecto elegido en la pantalla de control. Vive aquí para que la pantalla
/// de control y la de misión hablen del mismo.
final selectedProjectProvider =
    NotifierProvider<SelectedProjectController, String>(SelectedProjectController.new);

class SelectedProjectController extends Notifier<String> {
  @override
  String build() => '';

  void select(String alias) => state = alias;
}

// -- Sesión de tarea activa ---------------------------------------------------
class AgentSession {
  const AgentSession({
    required this.task,
    this.events = const [],
    this.status = 'starting',
    this.wsStatus = 'connecting',
    this.finalText = '',
    this.pendingApproval,
    this.error,
  });

  final AgentTask task;
  final List<AgentEvent> events;
  final String status;
  final String wsStatus;
  final String finalText;
  final AgentEvent? pendingApproval;
  final String? error;

  AgentSession copyWith({
    List<AgentEvent>? events,
    String? status,
    String? wsStatus,
    String? finalText,
    AgentEvent? pendingApproval,
    bool clearApproval = false,
    String? error,
  }) =>
      AgentSession(
        task: task,
        events: events ?? this.events,
        status: status ?? this.status,
        wsStatus: wsStatus ?? this.wsStatus,
        finalText: finalText ?? this.finalText,
        pendingApproval: clearApproval ? null : (pendingApproval ?? this.pendingApproval),
        error: error ?? this.error,
      );
}

class TaskSessionController extends Notifier<AgentSession?> {
  StreamSubscription<AgentEvent>? _sub;

  @override
  AgentSession? build() {
    ref.onDispose(() => _sub?.cancel());
    return null;
  }

  Future<void> createTask({
    required String agent,
    required String prompt,
    String? project,
  }) async {
    final repo = ref.read(agentRepositoryProvider);
    final task = await repo.createTask(agent: agent, prompt: prompt, project: project);
    final session = AgentSession(task: task, status: task.status);
    state = session;
    _sub?.cancel();
    _sub = repo.streamTask(task.runId).listen((event) => _onEvent(task.runId, session, event));
  }

  void _onEvent(String runId, AgentSession session, AgentEvent event) {
    final current = state;
    if (current == null || current.task.runId != runId) return;

    // La reconexión puede re-emitir eventos ya vistos: se descartan.
    if (current.events.any((e) => e.dedupeKey == event.dedupeKey)) return;

    var finalText = current.finalText;
    if (event.type == 'text.delta') {
      finalText += event.deltaText;
    }

    AgentEvent? pendingApproval = current.pendingApproval;
    if (event.type == 'approval.request') {
      pendingApproval = event;
    } else if (event.type == 'approval.resolved') {
      pendingApproval = null;
    }

    final terminal = const {'task.done', 'task.failed', 'task.stopped'}.contains(event.type);
    state = current.copyWith(
      events: [...current.events, event],
      status: terminal
          ? switch (event.type) {
              'task.done' => 'completed',
              'task.failed' => 'failed',
              _ => 'stopped',
            }
          : event.type == 'ws.status'
              ? current.status
              : 'running',
      wsStatus: event.type == 'ws.status' ? (event.payload['status']?.toString() ?? '') : current.wsStatus,
      finalText: finalText,
      pendingApproval: pendingApproval,
      clearApproval: true,
      error: event.type == 'ws.status' && event.payload['status'] == 'error' ? 'Sin conexión con el bridge' : null,
    );
  }

  Future<void> approve(String decision, {String? comment}) async {
    final current = state;
    if (current == null) return;
    await ref.read(agentRepositoryProvider).approve(current.task.runId, decision, comment: comment);
    state = current.copyWith(clearApproval: true);
  }

  Future<void> steerTo(String text) async {
    final current = state;
    if (current == null) return;
    await ref.read(agentRepositoryProvider).steer(current.task.runId, text);
  }

  Future<void> stopTask() async {
    final current = state;
    if (current == null) return;
    await ref.read(agentRepositoryProvider).stop(current.task.runId);
  }

  void clear() {
    _sub?.cancel();
    state = null;
  }
}

final taskSessionProvider =
    NotifierProvider<TaskSessionController, AgentSession?>(TaskSessionController.new);

// Historial reciente de run_ids lanzados en esta sesión de la app.
final recentTasksProvider = NotifierProvider<RecentTasksController, List<String>>(RecentTasksController.new);

class RecentTasksController extends Notifier<List<String>> {
  @override
  List<String> build() => const [];

  void add(String runId) {
    final list = List<String>.from(state);
    list.remove(runId);
    list.insert(0, runId);
    state = list.take(12).toList();
  }
}