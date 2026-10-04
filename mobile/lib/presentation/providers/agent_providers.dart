/// Providers Riverpod de la capa presentación (DI + estado reactivo).
library;

import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/config/app_config.dart';
import '../../core/network/permiso_notificaciones.dart';
import '../../core/widgets/aegis_mark.dart';
import '../../data/models/asistente_models.dart';
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

/// Despliegues esperando aprobación.
///
/// Con un `StreamProvider` y un `while(true)`, al desmontar la pantalla
/// quedaba un `Timer` vivo y el test fallaba con *"A Timer is still pending"*.
/// Aquí el temporizador es del `Notifier` y se cancela en `dispose()`, que es lo
/// que corresponde: el refresco muere con quien lo pidió.
///
/// Con algo pendiente se mira a menudo, porque es una decisión del usuario en
/// curso. Sin nada pendiente, de tanto en tanto: una alerta permanente se vuelve
/// fondo.
class DeploysController extends Notifier<DeployState?> {
  Timer? _temporizador;

  /// Urgencia del próximo tick. Vive aquí, no en `state`: `build()` programa el
  /// primer tick *antes* de devolver el estado, y leerlo ahí es usar el provider
  /// sin inicializar.
  bool _urgente = false;

  @override
  DeployState? build() {
    _programar();
    ref.onDispose(() => _temporizador?.cancel());
    return null;
  }

  void _programar() {
    _temporizador?.cancel();
    _temporizador = Timer(
      Duration(seconds: _urgente ? 3 : 20), _refrescar);
  }

  Future<void> _refrescar() async {
    try {
      final nuevo = await ref.read(agentRepositoryProvider).deployState();
      state = nuevo;
      _urgente = nuevo.hayPendientes;
    } catch (e) {
      state = DeployState(emulador: false, telefono: false);
      _urgente = false;
    }
    _programar();
  }

  /// Fuerza una lectura: se usa tras aprobar o denegar, para no esperar al tick.
  void refrescar() => _refrescar();
}

final deploysProvider =
    NotifierProvider<DeploysController, DeployState?>(DeploysController.new);

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

// -- Lo que Aegis sabe, y lo que puede hacer sin preguntar --------------------
//
// Los providers van aquí y no en las pantallas porque **dos pantallas necesitan
// lo mismo**: la cabecera de Ahora quiere saber si hay algo pendiente, y la
// sección Proyectos quiere la lista para poder marcarla. Con un provider
// compartido, aprobar una cosa en un sitio la desaparece del otro sin que
// ninguna se entere: antes.
/// Qué espera tu OK ahora mismo. Se refresca cada vez que se abre la app y
/// cuando se resuelve algo.
final aprobacionesProvider = FutureProvider<List<Aprobacion>>((ref) async {
  return ref.watch(agentRepositoryProvider).aprobaciones();
});

/// Las fases de trabajo que ofrece el puente. La lista sale de su disco, así
/// que aquí no hay nada que mantener cuando se añada una.
/// Qué enfoques hay. Solo para poder **fijar** uno a mano.
///
/// Lo normal es que Aegis pida el suyo y esto no se use: el plegable sale con
/// «fijar» y lo normal es que estés en «lo decide Aegis».
final enfoquesProvider = FutureProvider<List<Enfoque>>((ref) async {
  return ref.watch(agentRepositoryProvider).enfoques();
});

/// El enfoque **fijado a mano** para el próximo encargo. Vacío = lo decide Aegis.
///
/// ## Por qué está vacío por defecto y no puesto
/// Un enfoque es lo que Aegis deduce del encargo que recibe. Fijarlo a mano es
/// corregirlo cuando se ha equivocado, y esa corrección es de quien conoce el
/// encargo. Dejarlo fijado «por si acaso» haría que Aegis trabajara con unas
/// instrucciones que nadie ha comprobado que apliquen.
///
/// Vive en un provider y no en el `State` de la pantalla porque el botón de
/// relanzar un permiso está en otra tarjeta y necesita recuperarlo.
final enfoqueFijadoProvider =
    NotifierProvider<EnfoqueFijadoController, String>(EnfoqueFijadoController.new);

class EnfoqueFijadoController extends Notifier<String> {
  @override
  String build() => '';

  /// Fijarlo es una declaración para el próximo encargo, no un ajuste permanente:
  /// por eso pulsar dos veces el mismo lo suelta y vuelve a decidir Aegis.
  void alternar(String nombre) => state = state == nombre ? '' : nombre;

  void soltar() => state = '';
}

/// El estado de la autonomía: el modo y los proyectos marcados.
///
/// El repo fake y el real devuelven lo mismo, así que las pantallas no saben si
/// hay red o no. Esa es la razón de que exista un provider y no una llamada
/// directa desde cada widget.
final autonomiaProvider = FutureProvider<Autonomia>((ref) async {
  return ref.watch(agentRepositoryProvider).autonomia();
});

/// Lo que Aegis recuerda.
///
/// `autoDispose` a propósito: no tiene sentido conservar en memoria lo que Aegis
/// recuerda para una pantalla que no se está viendo, y el repo de por sí ya está
/// en caché por HTTP.
final memoriaProvider = FutureProvider<Memoria>((ref) async {
  return ref.watch(agentRepositoryProvider).memoria();
});

final runsProvider = FutureProvider<List<RunHistorial>>((ref) async {
  return ref.watch(agentRepositoryProvider).runs();
});

final notasProvider = FutureProvider<List<Nota>>((ref) async {
  return ref.watch(agentRepositoryProvider).notas();
});

final tareasProvider = FutureProvider<List<Tarea>>((ref) async {
  return ref.watch(agentRepositoryProvider).tareas();
});

/// Si Aegis está hablando, y si el puente sigue vivo.
///
/// ## Por qué esto sondea y `healthProvider` no
/// Porque son cosas distintas. `/health` va por la **salud**: si el bridge está en
/// pie. Se leía al arrancar y al tocar el aviso, y por eso el LED de la cabecera
/// decía «en línea» en el momento de arrancar y mentía a partir del minuto
/// siguiente, sin ninguna forma de enterarse.
///
/// `/actividad` va por la **vitalidad**: si hay texto saliendo ahora. Eso sí
/// cambia cada pocos segundos, y un dato que cambia cada pocos segundos necesita
/// perguntarse cada pocos segundos.
///
/// ## La cadencia
/// 1,2 s mirando, 6 s si lleva tres mirando sin nada. La ventana del bridge es
/// de 2,5 s, así que a 1,2 s no se pierde ni un parpadeo entre deltas; y cuando
/// lleva tres vueltas callado no hay nada que ver y 6 s no se notan. El otro
/// Importante es el: subir a 2,6 s perdería el final de cada frase, y el
/// glifo se quedaría encendido después de que Aegis haya callado —que es
/// exactamente la mentira que este indicator no puede decir.
class ActividadController extends Notifier<Actividad> {
  static const _viva = Duration(milliseconds: 1200);
  static const _triste = Duration(seconds: 6);
  static const _calladoPara = 3;

  Timer? _temporizador;
  int _vueltasCallado = 0;

  @override
  Actividad build() {
    _programar(const Duration(milliseconds: 0));
    ref.onDispose(() => _temporizador?.cancel());
    return const Actividad();
  }

  void _programar(Duration dentro) {
    _temporizador?.cancel();
    _temporizador = Timer(dentro, _preguntar);
  }

  Future<void> _preguntar() async {
    try {
      final a = await ref.read(agentRepositoryProvider).actividad();
      state = a;
      _vueltasCallado = a.hablando ? 0 : _vueltasCallado + 1;
    } catch (_) {
      // Sin bridge no hay nadie hablando, y tampoco hay quien lo diga: se
      // deja el estado como estaba y se reintenta. Un error aquí **no** es un
      // fallo de la app, es Aegis sin portátil, que es lo normal.
    }
    _programar(_vueltasCallado >= _calladoPara ? _triste : _viva);
  }

  /// Fuerza una lectura: tras mandar una misión, para no esperar al tick.
  void refrescar() => _preguntar();
}

final actividadProvider =
    NotifierProvider<ActividadController, Actividad>(ActividadController.new);

/// El estado del glifo, en los tres términos en que lo pinta.
///
/// ## Por qué un solo sitio
/// Porque el glifo aparece en la cabecera, en el arranque, en Misiones, en
/// Memoria, en el detalle de una misión y en la notificación. Si cada uno
///|tradujera `Actividad` a su manera, un día uno queda celeste con el agente
/// hablando y el resto en reposo, y no se nota hasta que se comparan dos
/// pantallas.
EstadoAegis estadoDelGlifo(Actividad a, {required bool puente}) {
  if (!puente) return EstadoAegis.sinPuente;
  return a.hablando ? EstadoAegis.hablando : EstadoAegis.reposo;
}

/// Si el sistema ya permite avisarte.
final permisoNotificacionesProvider = FutureProvider<bool>((ref) async {
  return PermisoNotificaciones.concedido();
});

/// Pide el permiso de avisos y vuelve a comprobar.
///
/// Se invalida a mano porque el diálogo del sistema es asíncrono: cuando vuelve
/// el resultado, no hay ninguna invalidación automática, y sin ella el badge
/// seguiría diciendo "sin permiso" con el permiso ya dado.
Future<void> pedirAvisos(WidgetRef ref) async {
  await PermisoNotificaciones.pedir();
  ref.invalidate(permisoNotificacionesProvider);
}

/// Refresca lo que Aegis sabe. Se llama después de aprobar, denegar, marcar o
/// escribir: si no, la pantalla siguiente muestra el estado anterior y parece
/// que la acción no surtió efecto.
void refrescarAsistente(WidgetRef ref) {
  ref.invalidate(aprobacionesProvider);
  ref.invalidate(autonomiaProvider);
  ref.invalidate(memoriaProvider);
  ref.invalidate(runsProvider);
  ref.invalidate(notasProvider);
  ref.invalidate(tareasProvider);
  ref.invalidate(healthProvider);
}
