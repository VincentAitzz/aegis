/// Implementación del repositorio: Dio (REST) + AgentSocket (WebSocket).
library;

import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';

import '../../core/config/app_config.dart';
import '../../core/network/agent_socket.dart';
import '../../domain/repositories/agent_repository.dart';
import '../models/agent_models.dart';

/// De dónde viene esta app: `emulador` o `telefono`.
///
/// No es metadato: el emulador y el teléfono llegan al bridge los dos por
/// `adb reverse`, así que los dos se ven como `127.0.0.1` y son indistinguibles.
/// Esta cabecera es lo que permite al bridge decir "esto vino del emulador", que
/// es la prueba de que el humo es real, y responder a la pregunta de fondo:
/// ¿cuándo tocó Aegis mi teléfono?
const String _origen = String.fromEnvironment('AEGIS_ORIGIN', defaultValue: 'telefono');

class AgentRepositoryImpl implements AgentRepository {
  AgentRepositoryImpl({required this.config}) : _dio = Dio(BaseOptions(
        connectTimeout: const Duration(seconds: 10),
        receiveTimeout: const Duration(seconds: 10),
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json',
          'X-Aegis-Origen': _origen,
        },
      ));

  final AppConfig config;
  final Dio _dio;
  final Map<String, AgentSocket> _sockets = {};
  final Map<String, StreamController<AgentEvent>> _streams = {};

  @override
  Future<BridgeHealth> health() async {
    final r = await _dio.get<Map<String, dynamic>>('${config.httpBase}/health');
    return BridgeHealth.fromJson(r.data!);
  }

  @override
  Future<List<String>> models() async {
    final r = await _dio.get<Map<String, dynamic>>('${config.httpBase}/models');
    final models = r.data?['available'] as List? ?? const [];
    return models.cast<String>();
  }

  @override
  Future<AgentTask> createTask({
    required String agent,
    required String prompt,
    String? instructions,
    String? project,
  }) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '${config.httpBase}/tasks',
      data: jsonEncode({
        'agent': agent,
        'prompt': prompt,
        if (instructions != null && instructions.isNotEmpty) 'instructions': instructions,
        if (project != null && project.isNotEmpty) 'project': project,
      }),
    );
    return AgentTask.fromJson(r.data!);
  }

  @override
  Future<List<ProjectInfo>> projects() async {
    final r = await _dio.get<Map<String, dynamic>>('${config.httpBase}/proyectos');
    final lista = (r.data!['proyectos'] as List?) ?? const [];
    return lista.whereType<Map<String, dynamic>>().map(ProjectInfo.fromJson).toList();
  }

  @override
  Future<ProjectInfo> writeFicha({
    required String alias,
    required String contenido,
  }) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '${config.httpBase}/fichas/$alias',
      data: jsonEncode({'contenido': contenido}),
    );
    final d = r.data!;
    // El bridge devuelve el estado ya calculado: la app no lo adivina, lo lee.
    return ProjectInfo(
      alias: (d['alias'] ?? alias) as String,
      kind: (d['kind'] ?? '') as String,
      estado: d['estado'] == 'completa' ? 'completa' : 'parcial',
      faltan: ((d['faltan'] as List?) ?? const []).cast<String>(),
    );
  }

  @override
  Future<DeployState> deployState() async {
    final r = await _dio.get<Map<String, dynamic>>('${config.httpBase}/deploys');
    return DeployState.fromJson(r.data!);
  }

  @override
  Future<void> decideDeploy(String id, {required bool aprobar}) async {
    await _dio.post<Map<String, dynamic>>(
      '${config.httpBase}/deploys/$id',
      data: jsonEncode({'decision': aprobar ? 'aprobar' : 'denegar'}),
    );
  }

  @override
  Future<String> startAutopilot({
    required String prompt,
    String? project,
    String? instructions,
    int maxSteps = 6,
    bool remember = true,
    bool verify = false,
  }) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '${config.httpBase}/autopilot/start',
      data: jsonEncode({
        'prompt': prompt,
        'max_steps': maxSteps,
        'remember': remember,
        'verificar': verify,
        if (project != null && project.isNotEmpty) 'project': project,
        if (instructions != null && instructions.isNotEmpty) 'instructions': instructions,
      }),
    );
    return r.data!['run_id'] as String;
  }

  @override
  Future<AutopilotRun> autopilotStatus(String runId) async {
    final r = await _dio.get<Map<String, dynamic>>(
      '${config.httpBase}/autopilot/$runId',
    );
    return AutopilotRun.fromJson(r.data!);
  }

  @override
  Stream<AgentEvent> streamTask(String runId) {
    final existing = _streams[runId];
    if (existing != null) return existing.stream;

    late final StreamController<AgentEvent> controller;
    controller = StreamController<AgentEvent>.broadcast(
      onListen: () => _attachSocket(runId, controller),
    );
    _streams[runId] = controller;
    return controller.stream;
  }

  void _attachSocket(String runId, StreamController<AgentEvent> controller) {
    AgentSocket? socket = _sockets[runId];
    if (socket == null) {
      socket = AgentSocket(
        wsUrl: config.wsBase,
        onEvent: (ev) {
          final event = AgentEvent.fromJson(ev);
          controller.add(event);
          if (const {'task.done', 'task.failed', 'task.stopped'}.contains(event.type)) {
            // desconecta al terminar (el canal puede quedar para otros runs)
            controller.close();
            _streams.remove(runId);
            socket?.close();
          }
        },
        onStatus: (status) => controller.add(AgentEvent(
              type: 'ws.status',
              taskId: runId,
              agent: '',
              when: '',
              payload: {'status': status},
            )),
      );
      _sockets[runId] = socket;
    }
    final active = socket;
    unawaited(active.connect().then((_) => active.subscribe(runId)));
  }

  @override
  Future<void> approve(String runId, String decision, {String? comment}) async {
    await _dio.post('${config.httpBase}/tasks/$runId/approval', data: {'decision': decision, 'comment': comment});
  }

  @override
  Future<void> steer(String runId, String text) async {
    await _dio.post('${config.httpBase}/tasks/$runId/steer', data: {'text': text});
  }

  @override
  Future<void> stop(String runId) async {
    await _dio.post('${config.httpBase}/tasks/$runId/stop');
  }
}
