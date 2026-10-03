// El repo falso que usa toda la suite.
//
// Vive en su propio fichero porque varios tests lo necesitan y cada uno con lo
// suyo se desincroniza: en cuanto uno cambia el `health()` para probar el caso
// sin puente, el otro sigue esperando un bridge sano y falla sin decir por qué.
import 'package:aegis_console/data/models/agent_models.dart';
import 'package:aegis_console/domain/repositories/agent_repository.dart';

class FakeAgentRepository implements AgentRepository {
  FakeAgentRepository({
    this.salud = const BridgeHealth(
      ok: true,
      host: 'test-host',
      hermesOk: true,
      ollamaOk: true,
      models: ['qwen2.5-coder:7b'],
      agents: ['worker'],
    ),
    this.fallaHealth = false,
    this.despliegues = const DeployState(
      emulador: true,
      telefono: true,
      tokensVivos: 0,
    ),
  });

  final BridgeHealth salud;

  /// Para probar el arranque sin puente: es el caso en el que el texto del
  /// arranque tiene que decir otra cosa que en el de "todo en verde".
  final bool fallaHealth;

  final DeployState despliegues;

  @override
  Future<BridgeHealth> health() async {
    if (fallaHealth) throw StateError('sin puente');
    return salud;
  }

  @override
  Future<List<String>> models() async => salud.models;

  @override
  Future<AgentTask> createTask({
    required String agent,
    required String prompt,
    String? instructions,
    String? project,
  }) async =>
      AgentTask(runId: 'run_test', agent: agent, status: 'started');

  @override
  Future<List<ProjectInfo>> projects() async => const [
        ProjectInfo(
            alias: 'aegis',
            kind: 'herramienta',
            estado: 'completa',
            verify: ['check', 'test']),
        ProjectInfo(
            alias: 'compra-unida',
            kind: 'encargo',
            estado: 'sin_ficha',
            verify: ['check', 'test']),
        ProjectInfo(
            alias: 'data-sending',
            kind: 'herramienta',
            estado: 'parcial',
            faltan: ['Invariantes', 'Qué no toca']),
      ];

  @override
  Future<DeployState> deployState() async => despliegues;

  @override
  Future<void> decideDeploy(String id, {required bool aprobar}) async {}

  @override
  Future<ProjectInfo> writeFicha({
    required String alias,
    required String contenido,
  }) async =>
      const ProjectInfo(alias: 'compra-unida', kind: 'encargo', estado: 'parcial');

  @override
  Future<String> startAutopilot({
    required String prompt,
    String? project,
    String? instructions,
    int maxSteps = 6,
    bool remember = true,
    bool verify = false,
  }) async =>
      'autopilot_test';

  @override
  Future<AutopilotRun> autopilotStatus(String runId) async => const AutopilotRun(
        runId: 'autopilot_test',
        status: 'completed',
        steps: 1,
        trace: [
          AutopilotStep(step: 1, tool: 'projects_list', ok: true, result: 'ok'),
        ],
        answer: 'listo',
        fin: 'sin_tools',
      );

  @override
  Stream<AgentEvent> streamTask(String runId) => const Stream.empty();

  @override
  Future<void> approve(String runId, String decision, {String? comment}) async {}

  @override
  Future<void> steer(String runId, String text) async {}

  @override
  Future<void> stop(String runId) async {}
}
