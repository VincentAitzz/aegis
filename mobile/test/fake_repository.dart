// El repo falso que usa toda la suite.
//
// Vive en su propio fichero porque varios tests lo necesitan y cada uno con lo
// suyo se desincroniza: en cuanto uno cambia el `health()` para probar el caso
// sin puente, el otro sigue esperando un bridge sano y falla sin decir por qué.
import 'package:aegis_console/data/models/agent_models.dart';
import 'package:aegis_console/data/models/asistente_models.dart';
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

  // Lo que los tests del asistente necesitan poder mover sin red.
  Memoria memoriaFake = const Memoria();
  List<RunHistorial> runsFake = const [];
  Autonomia autonomiaFake = const Autonomia();
  List<Aprobacion> aprobacionesFake = const [];
  List<String> denegacionesFake = [];
  Set<String> marcadosFake = {};
  List<Nota> notasFake = [];
  List<Tarea> tareasFake = [];

  /// Lo que el app le mandó al puente de verdad, para poder afirmar que se
  /// gastó. Un token de un solo uso que se puede gastar dos veces es una puerta
  /// corriente, y eso se comprueba, no se supone.
  List<String> tokensGastados = [];
  List<String> fasesLanzadas = [];
  List<String> promptsLanzados = [];
  List<String> ejecutadasFake = [];

  /// Lo que el repo falso dice que Aegis hace. Por defecto, quieto: los tests
  /// que no hablan de esto no tienen que saber de él.
  ///
  /// Se puede cambiar en caliente porque hay tests que **dependen** de que el
  /// glifo se encienda: si el falso no lo permitiera, nadie probaría que el
  /// magenta sale cuando tiene que salir. Por eso el campo se llama distinto
  /// del método: un repo puede tener un campo y un método del mismo nombre en
  /// Dart, pero aquí sería el mismo nombre en dos sitios y colisiona.
  Actividad estado = const Actividad();

  @override
  Future<Actividad> actividad() async => estado;

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
    String? token,
    String? fase,
  }) async {
    promptsLanzados.add(prompt);
    if (token != null && token.isNotEmpty) tokensGastados.add(token);
    if (fase != null && fase.isNotEmpty) fasesLanzadas.add(fase);
    return 'autopilot_test';
  }

  @override
  Future<List<String>> fases() async => const ['idea', 'arquitectura'];

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

  // -- lo que Aegis sabe (fake) --------------------------------------------

  @override
  Future<Memoria> memoria({String consulta = '', int limite = 20}) async =>
      memoriaFake;

  @override
  Future<List<RunHistorial>> runs({int limite = 20, String proyecto = ''}) async =>
      runsFake;

  @override
  Future<Autonomia> autonomia() async => autonomiaFake;

  @override
  Future<String> modoAutonomia(String modo) async => modo;

  @override
  Future<List<String>> marcarProyecto(String alias, {required bool escribir}) async {
    marcadosFake = {...marcadosFake};
    escribir ? marcadosFake.add(alias) : marcadosFake.remove(alias);
    return marcadosFake.toList();
  }

  @override
  Future<List<Aprobacion>> aprobaciones() async => aprobacionesFake;

  @override
  Future<String?> resolverAprobacion(String id, {required bool aprobar}) async {
    final peticion = aprobacionesFake.firstWhere((a) => a.id == id);
    aprobacionesFake = [...aprobacionesFake.where((a) => a.id != id)];
    if (!aprobar) return null;
    // Aprobar deja el permiso en la cola **con su token**, como hace el puente:
    // es lo que permite relanzar sin volver a preguntar.
    aprobacionesFake = [
      ...aprobacionesFake,
      Aprobacion(
        id: peticion.id,
        tool: peticion.tool,
        motivo: peticion.motivo,
        paso: peticion.paso,
        runId: peticion.runId,
        proyecto: peticion.proyecto,
        creado: peticion.creado,
        token: 'token_${peticion.id}',
      ),
    ];
    return 'token_${peticion.id}';
  }

  @override
  Future<EjecucionAprobada> ejecutarAprobacion(String id) async {
    ejecutadasFake.add(id);
    // El falso **no ejecuta nada**: la tool es la que escribe, y aquí solo se
    // anota. Un fake que "hace" lo que se le pide acaba mintiendo en el test.
    final p = aprobacionesFake.where((a) => a.id == id).toList();
    aprobacionesFake = [...aprobacionesFake.where((a) => a.id != id)];
    return EjecucionAprobada(
      tool: p.isEmpty ? 'project_create' : p.first.tool,
      ok: p.isNotEmpty,
      resultado: p.isEmpty ? '' : 'Alta de prueba',
    );
  }

  @override
  Future<void> denegarConMotivo(String id, String motivo) async {
    denegacionesFake = [...denegacionesFake, motivo];
    // El puente saca la petición de la cola al resolverla, approve o deny. Si el
    // falso no lo hiciera, la tarjeta seguiría ahí después de responder.
    aprobacionesFake = [...aprobacionesFake.where((a) => a.id != id)];
  }

  // -- tus cosas (fake) ----------------------------------------------------

  @override
  Future<List<Nota>> notas({String proyecto = ''}) async => notasFake;

  @override
  Future<Nota> crearNota({String titulo = '', String cuerpo = '', String proyecto = ''}) async {
    final n = Nota(id: 'nota-fake', titulo: titulo, cuerpo: cuerpo, proyecto: proyecto);
    notasFake = [n, ...notasFake];
    return n;
  }

  @override
  Future<void> borrarNota(String id) async {
    notasFake = notasFake.where((n) => n.id != id).toList();
  }

  @override
  Future<List<Tarea>> tareas({String estado = '', String proyecto = ''}) async => tareasFake;

  @override
  Future<Tarea> crearTarea({
    required String titulo,
    String notas = '',
    String proyecto = '',
    String para = '',
  }) async {
    final t = Tarea(id: 'tarea-fake', titulo: titulo, notas: notas,
        proyecto: proyecto, para: para);
    tareasFake = [t, ...tareasFake];
    return t;
  }

  @override
  Future<Tarea> actualizarTarea(String id,
      {String? titulo, String? notas, String? para, String? estado}) async {
    return tareasFake.firstWhere((t) => t.id == id,
        orElse: () => Tarea(id: id, titulo: titulo ?? ''));
  }

  @override
  Future<void> borrarTarea(String id) async {
    tareasFake = tareasFake.where((t) => t.id != id).toList();
  }
}
