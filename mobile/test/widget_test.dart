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
        agents: ['worker', 'orchestrator'],
      );

  @override
  Future<List<String>> models() async => const ['qwen2.5-coder:7b'];

  @override
  Future<AgentTask> createTask({required String agent, required String prompt, String? instructions}) async =>
      AgentTask(runId: 'run_test', agent: agent, status: 'started');

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
    expect(find.text('WORKER'), findsOneWidget);
    expect(find.text('ORQUESTADOR'), findsOneWidget);
    expect(find.text('EJECUTAR  ▶'), findsOneWidget);

    await tester.pumpWidget(const SizedBox());
  });
}