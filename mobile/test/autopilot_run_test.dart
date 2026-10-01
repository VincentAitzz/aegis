// El modelo que decide si un run "hizo algo" o solo contó que lo hizo.
import 'package:flutter_test/flutter_test.dart';

import 'package:aegis_console/data/models/agent_models.dart';

void main() {
  group('AutopilotRun', () {
    test('un run con tool en la traza ejecutó algo', () {
      final run = AutopilotRun.fromJson(const {
        'run_id': 'autopilot-1',
        'status': 'completed',
        'steps': 2,
        'trace': [
          {'step': 1, 'tool': 'projects_list', 'ok': true, 'result': 'aegis'},
        ],
        'answer': 'listo',
        'fin': 'sin_tools',
      });
      expect(run.executedAnything, isTrue);
      expect(run.tools.single.tool, 'projects_list');
      expect(run.finished, isTrue);
    });

    test('un run SIN tool no puede pasar por hecho que trabajó', () {
      final run = AutopilotRun.fromJson(const {
        'run_id': 'autopilot-2',
        'status': 'completed',
        'steps': 1,
        'trace': [
          {'step': 1, 'action': 'repair', 'text': 'Ya está, son 4 proyectos.'},
        ],
        'answer': 'Ya está, son 4 proyectos.',
        'fin': 'respuesta_vacia',
      });
      // El agente respondió, pero no ejecutó nada: eso es `false`, y la UI lo dice.
      expect(run.executedAnything, isFalse);
      expect(run.tools, isEmpty);
      expect(run.answer, isNotEmpty);
      expect(run.finished, isTrue);
    });

    test('una tool con ok=false es un fallo, no un acierto', () {
      final run = AutopilotRun.fromJson(const {
        'run_id': 'autopilot-3',
        'status': 'completed',
        'steps': 1,
        'trace': [
          {'step': 1, 'tool': 'repo_verify', 'ok': false, 'result': 'ERROR: timeout'},
        ],
        'answer': 'no pude verificar',
      });
      expect(run.tools.single.failed, isTrue);
      expect(run.tools.single.summary, contains('FALLÓ'));
    });

    test('running no es finished', () {
      final run = AutopilotRun.fromJson(const {
        'run_id': 'autopilot-4',
        'status': 'running',
        'steps': 0,
        'trace': <dynamic>[],
      });
      expect(run.running, isTrue);
      expect(run.finished, isFalse);
      expect(run.executedAnything, isFalse);
    });
  });
}