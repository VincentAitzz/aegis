/// Contrato de la capa domain: el repositorio que consume el bridge.
library;

import '../../data/models/agent_models.dart';

abstract interface class AgentRepository {
  Future<BridgeHealth> health();

  Future<List<String>> models();

  /// Crea una tarea (run) en Hermes vía el bridge y devuelve su run_id.
  Future<AgentTask> createTask({
    required String agent, // 'worker' | 'orchestrator'
    required String prompt,
    String? instructions,
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