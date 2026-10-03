/// Contrato de la capa domain: el repositorio que consume el bridge.
library;

import '../../data/models/agent_models.dart';
import '../../data/models/asistente_models.dart';

/// Lo que pasó al ejecutar una aprobación.
///
/// `ok` es si la tool corrió **y no denegó**: las tools de Aegis devuelven el
/// motivo como texto en vez de lanzar, así que un "hecho" sobre un "RECHAZADO"
/// detrás sería el falso éxito que el bridge ya pagó una vez.
class EjecucionAprobada {
  const EjecucionAprobada({
    required this.tool,
    required this.ok,
    this.resultado = '',
    this.error = '',
  });

  final String tool;
  final bool ok;
  final String resultado;
  final String error;

  factory EjecucionAprobada.fromJson(Map<String, dynamic> j) => EjecucionAprobada(
        tool: (j['tool'] ?? '') as String,
        ok: j['ok'] == true,
        resultado: (j['result'] ?? '') as String,
        error: (j['error'] ?? '') as String,
      );
}

abstract interface class AgentRepository {
  Future<BridgeHealth> health();

  /// Si Aegis está hablando ahora mismo. Lo pinta el glifo.
  Future<Actividad> actividad();

  Future<List<String>> models();

  /// Crea una tarea (run) en Hermes vía el bridge y devuelve su run_id.
  Future<AgentTask> createTask({
    required String agent, // Aegis tiene un solo agente: 'worker'
    required String prompt,
    String? instructions,
    /// Alias del proyecto (`compra-unida`, `aegis`…). Con esto el bridge carga
    /// su ficha y su memoria en el prompt: sin él, el agente razona sin saber
    /// de qué se trata, que es lo que el método prohíbe.
    String? project,
  });

  /// Proyectos que puede operar Aegis, con el estado de su ficha.
  Future<List<ProjectInfo>> projects();

  /// Fases de trabajo que el puente ofrece: `idea`, `arquitectura`, …
  ///
  /// Vienen del disco del bridge, no de una lista en la app: cada fase es un
  /// fichero que se puede escribir sin compilar nada. Vacía = ninguna, y la app
  /// simplemente no muestra el selector.
  Future<List<String>> fases();

  /// Despliegues esperando aprobación en el teléfono. Mientras haya algo aquí,
  /// Aegis **no ha instalado nada**: está esperando a que lo apruebes.
  Future<DeployState> deployState();

  /// Aprueba (o deniega) una instalación pendiente. Una aprobación es de un
  /// solo uso: sirve para instalar una vez.
  Future<void> decideDeploy(String id, {required bool aprobar});

  /// Lanza un run de autopilot en segundo plano y devuelve ya su run_id.
  ///
  /// Es la vía que ejecuta tools de verdad: el modelo elige qué tool usar y el
  /// bridge la corre con lista blanca, dejando traza.
  Future<String> startAutopilot({
    required String prompt,
    String? project,
    String? instructions,
    int maxSteps,
    bool remember,
    bool verify,
    String? token,
    String? fase,
  });

  /// Progreso del run de autopilot. `AutopilotRun.finished` dice si paró.
  Future<AutopilotRun> autopilotStatus(String runId);

  /// Escribe la ficha de un proyecto, **sin pasar por el modelo**.
  ///
  /// La ruta por el modelo no sirve, y se comprobó: un 7B al que se le pide
  /// copiar un texto literal **se come los `---` del frontmatter**, que es lo
  /// que declara el tipo. La ficha quedaba sin tipo y la puerta la rechazaba.
  /// Aquí la persona ya revisó el texto en el móvil y el bridge lo guarda tal
  /// cual: no hay nada que el modelo pueda tocar.
  Future<ProjectInfo> writeFicha({
    required String alias,
    required String contenido,
  });

  /// Streaming bidireccional: suscribe al canal WS del run y entrega eventos.
  ///
  /// Devuelve un controlador; `[onEvent]` se invoca por cada evento, y el
  /// stream se cierra cunado termina la tarea o se cancela el suscriptor.
  Stream<AgentEvent> streamTask(String runId);

  Future<void> approve(String runId, String decision, {String? comment});

  Future<void> steer(String runId, String text);

  Future<void> stop(String runId);

  // -- Lo que Aegis sabe y lo que recuerda -----------------------------------
  //
  // Hasta aquí el móvil veía siete rutas de un bridge que tenía quince: la
  // memoria existía —con 35 nodos, 588 aristas y episodios reales— y no había
  // forma de mirarla. Un asistente que no puede decir lo que recuerda se
  // comporta como si no tuviera memoria, que es exactamente lo que pasa si el
  // recuerdo es cierto y no se enseña.

  /// Lo que Aegis recuerda, en metadatos. Nunca el texto de lo que hablamos.
  Future<Memoria> memoria({String consulta, int limite});

  /// El historial de runs, leído del disco del bridge. No de la sesión de la
  /// app: esa se pierde al cerrarla.
  Future<List<RunHistorial>> runs({int limite, String proyecto});

  /// El estado de la autonomía: el modo, qué proyectos puede tocar sin
  /// preguntar, y qué está esperando tu OK ahora mismo.
  Future<Autonomia> autonomia();

  /// Cambia el nivel de autonomía. No existe modo que dispense de preguntar.
  Future<String> modoAutonomia(String modo);

  /// Marca un proyecto como "puedes escribir aquí".
  ///
  /// El bridge **niega** los que no tienen verificador declarado, y con razón:
  /// permiso de escritura sobre algo que no se puede verificar es autonomía sin
  /// forma de saber si salió bien.
  Future<List<String>> marcarProyecto(String alias, {required bool escribir});

  /// Lo que Aegis quiere hacer y no se atreve a hacer solo.
  ///
  /// Vienen las dos listas del puente: las que te preguntan (sin token) y las
  /// que ya aprobaste y nadie ha gastado (con token, listas para relanzar).
  Future<List<Aprobacion>> aprobaciones();

  /// Aprueba o deniega. Al aprobar devuelve el **token de un solo uso**, que
  /// solo vale para esa tool con esos argumentos; vacío al denegar.
  ///
  /// Antes esto devolvía `void` y el token se quedaba en la respuesta sin que
  /// nadie lo leyera: aprobar era un callejón sin salida.
  Future<String?> resolverAprobacion(String id, {required bool aprobar});

  /// Ejecuta la llamada que ya aprobaste, con sus argumentos, sin modelo.
  ///
  /// Relanzar el run obligaba a que el modelo emitiera la misma tool con los
  /// mismos argumentos, y medido no lo hacía casi nunca. Esto ejecuta lo que
  /// está en la fila: lo que leíste antes de decir que sí. De un solo uso.
  Future<EjecucionAprobada> ejecutarAprobacion(String id);

  /// **Por qué** denegas. Es lo que hace que la confianza crezca: no es que
  /// Aegis aprenda a tener cuidado, es que tú se lo dijiste una vez.
  Future<void> denegarConMotivo(String id, String motivo);

  // -- Tus cosas -----------------------------------------------------------
  Future<List<Nota>> notas({String proyecto});

  Future<Nota> crearNota({String titulo, String cuerpo, String proyecto});

  Future<void> borrarNota(String id);

  Future<List<Tarea>> tareas({String estado, String proyecto});

  Future<Tarea> crearTarea({required String titulo, String notas, String proyecto, String para});

  Future<Tarea> actualizarTarea(String id, {String titulo, String notas, String para, String estado});

  Future<void> borrarTarea(String id);
}
