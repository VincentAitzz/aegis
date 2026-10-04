/// Modelos de datos de la capa data (DTOs del contrato REST/WS del bridge).
library;

import 'dart:convert';

/// Un proyecto del workspace y el estado de su ficha.
///
/// El color del selector sale de aquí, no de que el agente lo diga: `sin_ficha`
/// significa que Aegis no puede escribir en él todavía.
class ProjectInfo {
  const ProjectInfo({
    required this.alias,
    required this.estado,
    this.kind = '',
    this.root = '',
    this.area = '',
    this.faltan = const [],
    this.verify = const [],
    this.db = '',
    this.origen = '',
    this.existe = true,
  });

  final String alias;
  final String kind; // encargo | producto | herramienta | '' si no la tiene
  final String root;
  final String area;
  final String estado; // sin_ficha | parcial | completa
  final List<String> faltan;
  final List<String> verify;
  final String db;
  final String origen; // registro | código
  final bool existe;

  factory ProjectInfo.fromJson(Map<String, dynamic> json) => ProjectInfo(
        alias: json['alias'] as String,
        kind: (json['kind'] ?? '') as String,
        root: (json['root'] ?? '') as String,
        area: (json['area'] ?? '') as String,
        estado: (json['estado'] ?? 'sin_ficha') as String,
        faltan: ((json['faltan'] as List?) ?? const []).cast<String>(),
        verify: ((json['verify'] as List?) ?? const []).cast<String>(),
        db: (json['db'] ?? '') as String,
        origen: (json['origen'] ?? '') as String,
        existe: json['existe'] != false,
      );

  bool get completa => estado == 'completa';
  bool get parcial => estado == 'parcial';
  bool get sinFicha => estado == 'sin_ficha';

  /// Se puede escribir en él solo con la ficha completa. Refleja la puerta, no
  /// una opinión: si esto dice `true` y la puerta niega, algo se rompió.
  bool get escribible => completa;
}

class AgentTask {
  const AgentTask({required this.runId, required this.agent, required this.status, this.sessionId});

  final String runId;
  final String agent; // Aegis tiene un solo agente: 'worker'
  final String status;
  final String? sessionId;

  factory AgentTask.fromJson(Map<String, dynamic> json) => AgentTask(
        runId: json['run_id'] as String,
        agent: json['agent'] as String,
        status: json['status'] as String,
        sessionId: json['session_id'] as String?,
      );
}

/// Un paso de autopilot: una tool que se ejecutó de verdad, con su resultado.
///
/// El `ok` y el `result` vienen de la traza, no de lo que el agente dice que
/// hizo. Es la diferencia entre "funcionó" y "el modelo cuenta que funcionó".
class AutopilotStep {
  const AutopilotStep({
    required this.step,
    this.tool,
    this.ok,
    this.result,
    this.action,
    this.text,
  });

  final int step;
  final String? tool;
  final bool? ok;
  final String? result;
  final String? action; // 'repair' cuando el modelo no pidió una tool
  final String? text;

  factory AutopilotStep.fromJson(Map<String, dynamic> json) => AutopilotStep(
        step: (json['step'] as num?)?.toInt() ?? 0,
        tool: json['tool'] as String?,
        ok: json['ok'] as bool?,
        result: json['result'] as String?,
        action: json['action'] as String?,
        text: json['text'] as String?,
      );

  bool get isTool => tool != null && tool!.isNotEmpty;
  bool get failed => ok == false;

  String get summary {
    if (!isTool) return action == 'repair' ? 'reintento' : 'paso $step';
    return failed ? '$tool FALLÓ' : '$tool OK';
  }
}

/// Progreso de un run de autopilot (el móvil lo consulta hasta que termina).
class AutopilotRun {
  const AutopilotRun({
    required this.runId,
    required this.status,
    required this.steps,
    required this.trace,
    this.answer,
    this.fin,
    this.error,
  });

  final String runId;
  final String status; // running | completed | failed
  final int steps;
  final List<AutopilotStep> trace;
  final String? answer;

  /// Por qué terminó: sin_tools | respuesta_vacia | max_steps | puerta.
  final String? fin;
  final String? error;

  factory AutopilotRun.fromJson(Map<String, dynamic> json) => AutopilotRun(
        runId: json['run_id'] as String,
        status: json['status'] as String,
        steps: (json['steps'] as num?)?.toInt() ?? 0,
        trace: ((json['trace'] as List?) ?? const [])
            .whereType<Map<String, dynamic>>()
            .map(AutopilotStep.fromJson)
            .toList(),
        answer: json['answer'] as String?,
        fin: json['fin'] as String?,
        error: json['error'] as String?,
      );

  bool get running => status == 'running';
  bool get finished => status == 'completed' || status == 'failed';

  /// Las tools que se ejecutaron de verdad. Si está vacía, el run no hizo nada
  /// por más que el agente diga que terminó.
  List<AutopilotStep> get tools =>
      trace.where((s) => s.isTool).toList(growable: false);

  bool get executedAnything => tools.isNotEmpty;
}

class AgentEvent {
  const AgentEvent({
    required this.type,
    required this.taskId,
    required this.agent,
    required this.when,
    required this.payload,
  });

  final String type; // task.created, text.delta, tool.completed, approval.request, task.done...
  final String taskId;
  final String agent;
  final String when;
  final Map<String, dynamic> payload;

  factory AgentEvent.fromJson(Map<String, dynamic> json) => AgentEvent(
        type: json['type'] as String,
        taskId: json['task_id'] as String,
        agent: json['agent'] as String,
        when: (json['at'] ?? '') as String,
        payload: (json['payload'] as Map<String, dynamic>?) ?? const {},
      );

  /// Clave de deduplicación (reconexión puede re-emitir el stream).
  String get dedupeKey => '$type|$_stablePayload';

  String get _stablePayload {
    final ev = payload['event'] ?? '';
    final data = payload['data'];
    final s = switch (data) {
      String x => x,
      _ => jsonEncode(data),
    };
    return '$ev|$s';
  }

  /// Texto legible para la UI según el tipo de evento.
  String get summary {
    final data = payload['data'];
    final raw = data is Map ? data : {};
    switch (type) {
      case 'task.created':
        return 'TAREA REGISTRADA';
      case 'text.delta':
        final txt = raw['text'] ?? raw['delta'] ?? '';
        return txt is String ? txt : '…';
      case 'tool.started':
        return '${raw['tool'] ?? 'herramienta'} INICIANDO';
      case 'tool.completed':
        final dur = raw['duration'];
        final d = dur != null ? ' (${_fmtDur(dur)})' : '';
        return '${raw['tool'] ?? 'herramienta'} OK$d';
      case 'approval.request':
        return 'AUTORIZACIÓN REQUERIDA: ${raw['tool'] ?? raw['reason'] ?? 'herramienta'}';
      case 'task.done':
        return 'TAREA COMPLETADA';
      case 'task.failed':
        return 'TAREA FALLÓ';
      case 'task.stopped':
        return 'TAREA DETENIDA';
      default:
        return (raw['event'] ?? payload['event'] ?? type).toString();
    }
  }

  static String _fmtDur(Object? v) {
    final n = num.tryParse(v.toString());
    if (n == null) return v.toString();
    return n >= 60 ? '${(n / 60).toStringAsFixed(1)} min' : '${n.toStringAsFixed(1)} s';
  }

  /// Concatenación de texto parcial acumulado (para el cuadro de la respuesta).
  String get deltaText {
    if (type != 'text.delta') return '';
    final data = payload['data'];
    if (data is! Map) return '';
    return (data['text'] ?? data['delta'] ?? '').toString();
  }
}

class BridgeHealth {
  const BridgeHealth({
    required this.ok,
    required this.host,
    required this.hermesOk,
    required this.ollamaOk,
    required this.models,
    required this.agents,
  });

  final bool ok;
  final String host;
  final bool hermesOk;
  final bool ollamaOk;
  final List<String> models;
  final List<String> agents;

  factory BridgeHealth.fromJson(Map<String, dynamic> json) => BridgeHealth(
        ok: json['status'] == 'ok',
        host: (json['bridge']?['host'] ?? '') as String,
        hermesOk: (json['hermes']?['status'] ?? '') == 'ok',
        ollamaOk: json['ollama']?['ok'] == true,
        models: (json['ollama']?['models'] as List?)?.cast<String>() ?? const [],
        agents: (json['agents'] as List?)?.cast<String>() ?? const [],
      );
}
/// Una petición de despliegue esperando aprobación.
/// Un enfoque de trabajo, de lo que el bridge tiene en `bridge/enfoques/`.
class Enfoque {
  const Enfoque({
    required this.nombre,
    required this.titulo,
    required this.resumen,
    this.cuando = const [],
    this.restringe = const [],
    this.bloqueChars = 0,
  });

  final String nombre;
  final String titulo;

  /// Por qué sirve, en una frase. Lo que se lee **antes** de decidir fijarlo.
  final String resumen;

  /// Las señales del encargo que lo sugieren. No las usa la app: están para que
  /// un humano entienda cuándo aplica.
  final List<String> cuando;

  /// Las tools que este enfoque cierra mientras dure el encargo.
  final List<String> restringe;

  /// Cuánto prompt cuesta, para poder decir si merece la pena fijarlo a mano.
  final int bloqueChars;

  factory Enfoque.fromJson(Map<String, dynamic> j) => Enfoque(
        nombre: (j['nombre'] ?? '') as String,
        titulo: (j['titulo'] ?? '') as String,
        resumen: (j['resumen'] ?? '') as String,
        cuando:
            ((j['cuando'] as List?) ?? const []).map((e) => '$e').toList(),
        restringe:
            ((j['restringe'] as List?) ?? const []).map((e) => '$e').toList(),
        bloqueChars: (j['bloque_chars'] as num?)?.toInt() ?? 0,
      );

  /// Si este enfoque cierra algo, y qué.
  ///
  /// Se pinta porque es la parte que **cuesta**: fijar un enfoque puede dejarte
  /// sin poder escribir. Decirlo antes de fijarlo es mejor que descubrirlo
  /// cuando Aegis dice «no puedo escribir» y no se sabe por qué.
  String? get cierra =>
      restringe.isEmpty ? null : 'Cierra: ${restringe.join(', ')}';
}

class DeployRequest {
  const DeployRequest({
    required this.id,
    required this.estado,
    this.razon = '',
    this.lanzar = false,
  });

  final String id;
  final String estado; // pendiente | aprobada | denegada
  final String razon;
  final bool lanzar;

  factory DeployRequest.fromJson(Map<String, dynamic> json) => DeployRequest(
        id: (json['id'] ?? '') as String,
        estado: (json['estado'] ?? 'pendiente') as String,
        razon: (json['razon'] ?? '') as String,
        lanzar: json['lanzar'] == true,
      );

  /// Qué va a pasar exactamente al aprobar. Se dice entero porque aprobar sin
  /// saber si la app se abre encima es justo lo que hay que evitar.
  String get quePasa => lanzar
      ? 'Se instalará y SE ABRIRÁ la app en tu teléfono.'
      : 'Se instalará la app. NO se abrirá.';
}

/// Estado de la puerta de despliegue.
class DeployState {
  const DeployState({
    required this.emulador,
    required this.telefono,
    this.pendientes = const [],
    this.tokensVivos = 0,
  });

  final bool emulador;
  final bool telefono;
  final List<DeployRequest> pendientes;
  final int tokensVivos;

  factory DeployState.fromJson(Map<String, dynamic> json) => DeployState(
        emulador: json['emulador'] == true,
        telefono: json['telefono'] == true,
        pendientes: ((json['pendientes'] as List?) ?? const [])
            .whereType<Map<String, dynamic>>()
            .map(DeployRequest.fromJson)
            .toList(),
        tokensVivos: (json['tokens_vivos'] as num?)?.toInt() ?? 0,
      );

  bool get hayPendientes => pendientes.isNotEmpty;
}
