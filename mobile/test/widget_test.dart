// Prueba de humo de la app Aegis (repo fake, sin red).
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aegis_console/app.dart';
import 'package:aegis_console/data/models/agent_models.dart';
import 'package:aegis_console/domain/repositories/agent_repository.dart';
import 'package:aegis_console/presentation/providers/agent_providers.dart';

class FakeAgentRepository implements AgentRepository {
  @override
  Future<BridgeHealth> health() async => const BridgeHealth(
        ok: true,
        host: 'test-host',
        hermesOk: true,
        ollamaOk: true,
        models: ['qwen2.5-coder:7b'],
        agents: ['worker'],
      );

  @override
  Future<List<String>> models() async => const ['qwen2.5-coder:7b'];

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
        ProjectInfo(alias: 'aegis', kind: 'herramienta', estado: 'completa', verify: ['check', 'test']),
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

void main() {
  testWidgets('Aegis Console renders DedSec home', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [agentRepositoryProvider.overrideWithValue(FakeAgentRepository())],
        child: const AegisApp(),
      ),
    );

    // Secuencia de arranque (boot) → centro de control.
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 1500));
    await tester.pump(const Duration(milliseconds: 500));

    expect(find.text('AEGIS CONSOLE'), findsOneWidget);
    expect(find.text('[NUEVO ENCARGO]'), findsOneWidget);
    // Un solo agente: se elige motor, no rol.
    expect(find.text('HERMES'), findsOneWidget);
    expect(find.text('AUTOPILOT'), findsOneWidget);
    expect(find.text('ORQUESTADOR'), findsNothing);
    expect(find.text('EJECUTAR  ▶'), findsOneWidget);

    await tester.pumpWidget(const SizedBox());
  });
}