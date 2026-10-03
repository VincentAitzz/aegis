/// Implementación del repositorio: Dio (REST) + AgentSocket (WebSocket).
library;

import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';

import '../../core/config/app_config.dart';
import '../../core/network/agent_socket.dart';
import '../../domain/repositories/agent_repository.dart';
import '../models/agent_models.dart';
import '../models/asistente_models.dart';

/// De dónde viene esta app: `emulador` o `telefono`.
///
/// No es metadato: el emulador y el teléfono llegan al bridge los dos por
/// `adb reverse`, así que los dos se ven como `127.0.0.1` y son indistinguibles.
/// Esta cabecera es lo que permite al bridge decir "esto vino del emulador", que
/// es la prueba de que el humo es real, y responder a la pregunta de fondo:
/// ¿cuándo tocó Aegis mi teléfono?
const String _origen = String.fromEnvironment('AEGIS_ORIGIN', defaultValue: 'telefono');

/// Token de la API de operación, va en `X-Aegis-Token`.
///
/// ## Por qué va con `--dart-define` y no hardcodeado
/// Es una credencial, y una credencial en el código es una credencial en git.
/// Como `--dart-define` se compila dentro del APK, tampoco es un secreto que
/// valga para siempre: cualquiera con el APK puede extraerlo. Para una app de
/// una persona en su red privada es aceptable, y es mejor que no tener puerta
/// ninguna; para algo compartido, no.
///
/// ## Por qué vacío funciona
/// Vacío = el bridge no exige token (`AEGIS_API_KEY` sin valor). Así la app
/// arranca el primer día sin tener que generar un secreto, y el día que actives
/// la clave el token ya viaja en la cabecera. Los dos lados van juntos: si
/// pones la clave en el bridge sin recompilar la app, lo nuevo devuelve 401.
const String _token = String.fromEnvironment('AEGIS_TOKEN', defaultValue: '');

class AgentRepositoryImpl implements AgentRepository {
  AgentRepositoryImpl({required this.config}) : _dio = Dio(BaseOptions(
        connectTimeout: const Duration(seconds: 10),
        receiveTimeout: const Duration(seconds: 10),
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json',
          'X-Aegis-Origen': _origen,
          // Se manda siempre, incluso vacía: una cabecera vacía y una
          // ausente se comportan igual en el bridge, y mandarla hace que el
          // problema sea "el token no viaja" y no "falta la cabecera".
          'X-Aegis-Token': _token,
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
  Future<List<String>> fases() async {
    final r = await _dio.get<Map<String, dynamic>>('${config.httpBase}/fases');
    return ((r.data?['fases'] as List?) ?? const []).cast<String>();
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
  Future<Actividad> actividad() async {
    final r = await _dio.get<Map<String, dynamic>>('${config.httpBase}/actividad');
    return Actividad.fromJson(r.data!);
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
    String? token,
    String? fase,
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
        if (token != null && token.isNotEmpty) 'token': token,
        if (fase != null && fase.isNotEmpty) 'fase': fase,
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

  // -- Lo que Aegis sabe ---------------------------------------------------

  @override
  Future<Memoria> memoria({String consulta = '', int limite = 20}) async {
    final r = await _dio.get<Map<String, dynamic>>(
      '${config.httpBase}/memoria',
      queryParameters: {
        'limite': limite,
        if (consulta.isNotEmpty) 'consulta': consulta,
      },
    );
    return Memoria.fromJson(r.data!);
  }

  @override
  Future<List<RunHistorial>> runs({int limite = 20, String proyecto = ''}) async {
    final r = await _dio.get<Map<String, dynamic>>(
      '${config.httpBase}/runs',
      queryParameters: {
        'limite': limite,
        if (proyecto.isNotEmpty) 'proyecto': proyecto,
      },
    );
    return ((r.data?['runs'] as List?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(RunHistorial.fromJson)
        .toList();
  }

  @override
  Future<Autonomia> autonomia() async {
    final r = await _dio.get<Map<String, dynamic>>('${config.httpBase}/autonomy');
    return Autonomia.fromJson(r.data!);
  }

  @override
  Future<String> modoAutonomia(String modo) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '${config.httpBase}/autonomy/modo',
      data: jsonEncode({'modo': modo}),
    );
    return (r.data?['modo'] ?? modo) as String;
  }

  @override
  Future<List<String>> marcarProyecto(String alias, {required bool escribir}) async {
    if (!escribir) {
      await _dio.delete<Map<String, dynamic>>('${config.httpBase}/autonomy/$alias');
    } else {
      await _dio.post<Map<String, dynamic>>(
        '${config.httpBase}/autonomy/$alias',
        data: jsonEncode({'permiso': 'escribir'}),
      );
    }
    final r = await _dio.get<Map<String, dynamic>>('${config.httpBase}/autonomy');
    return ((r.data?['escritura'] as Map?) ?? const {}).keys.cast<String>().toList();
  }

  @override
  Future<List<Aprobacion>> aprobaciones() async {
    final r = await _dio.get<Map<String, dynamic>>('${config.httpBase}/aprobaciones');
    final lista = <Aprobacion>[];
    for (final clave in const ['aprobadas', 'pendientes']) {
      lista.addAll(((r.data?[clave] as List?) ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(Aprobacion.fromJson));
    }
    return lista;
  }

  @override
  Future<String?> resolverAprobacion(String id, {required bool aprobar}) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '${config.httpBase}/aprobaciones/$id',
      data: jsonEncode({'decision': aprobar ? 'aprobar' : 'denegar'}),
    );
    return r.data?['token'] as String?;
  }

  @override
  Future<EjecucionAprobada> ejecutarAprobacion(String id) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '${config.httpBase}/aprobaciones/$id/ejecutar',
    );
    return EjecucionAprobada.fromJson(r.data ?? const {});
  }

  @override
  Future<void> denegarConMotivo(String id, String motivo) async {
    await _dio.post<Map<String, dynamic>>(
      '${config.httpBase}/aprobaciones/$id/motivo',
      data: jsonEncode({'contenido': motivo}),
    );
  }

  // -- Tus cosas -----------------------------------------------------------

  @override
  Future<List<Nota>> notas({String proyecto = ''}) async {
    final r = await _dio.get<Map<String, dynamic>>(
      '${config.httpBase}/notas',
      queryParameters: {if (proyecto.isNotEmpty) 'proyecto': proyecto},
    );
    return ((r.data?['notas'] as List?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(Nota.fromJson)
        .toList();
  }

  @override
  Future<Nota> crearNota({String titulo = '', String cuerpo = '', String proyecto = ''}) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '${config.httpBase}/notas',
      data: jsonEncode({'titulo': titulo, 'cuerpo': cuerpo, 'proyecto': proyecto}),
    );
    return Nota.fromJson(r.data!);
  }

  @override
  Future<void> borrarNota(String id) async {
    await _dio.delete<Map<String, dynamic>>('${config.httpBase}/notas/$id');
  }

  @override
  Future<List<Tarea>> tareas({String estado = '', String proyecto = ''}) async {
    final r = await _dio.get<Map<String, dynamic>>(
      '${config.httpBase}/tareas',
      queryParameters: {
        if (estado.isNotEmpty) 'estado': estado,
        if (proyecto.isNotEmpty) 'proyecto': proyecto,
      },
    );
    return ((r.data?['tareas'] as List?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(Tarea.fromJson)
        .toList();
  }

  @override
  Future<Tarea> crearTarea({
    required String titulo,
    String notas = '',
    String proyecto = '',
    String para = '',
  }) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '${config.httpBase}/tareas',
      data: jsonEncode({'titulo': titulo, 'notas': notas, 'proyecto': proyecto, 'para': para}),
    );
    return Tarea.fromJson(r.data!);
  }

  @override
  Future<Tarea> actualizarTarea(
    String id, {
    String? titulo,
    String? notas,
    String? para,
    String? estado,
  }) async {
    // Los campos que no cambian no se mandan: `PATCH` con un `null` explícito
    // vaciaría el campo, y "no tocar" y "vaciar" son cosas distintas.
    final cambios = <String, String>{};
    if (titulo != null) cambios['titulo'] = titulo;
    if (notas != null) cambios['notas'] = notas;
    if (para != null) cambios['para'] = para;
    if (estado != null) cambios['estado'] = estado;
    final r = await _dio.patch<Map<String, dynamic>>(
      '${config.httpBase}/tareas/$id',
      data: jsonEncode(cambios),
    );
    return Tarea.fromJson(r.data!);
  }

  @override
  Future<void> borrarTarea(String id) async {
    await _dio.delete<Map<String, dynamic>>('${config.httpBase}/tareas/$id');
  }
}
