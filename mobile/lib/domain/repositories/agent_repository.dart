/// Contrato de la capa domain: el repositorio que consume el bridge.
library;

import '../../data/models/agent_models.dart';

abstract interface class AgentRepository {
  Future<BridgeHealth> health();

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
}