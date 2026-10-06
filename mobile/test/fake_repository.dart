// El repo falso que usa toda la suite.
//
// Vive en su propio fichero porque varios tests lo necesitan y cada uno con lo
// suyo se desincroniza: en cuanto uno cambia el `health()` para probar el caso
// sin puente, el otro sigue esperando un bridge sano y falla sin decir por qué.
import 'package:aegis_console/data/models/agent_models.dart';
import 'package:aegis_console/data/models/asistente_models.dart';
import 'package:aegis_console/data/models/version_apk.dart';
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
  /// El enfoque de cada run lanzado: `''` cuando no iba ninguno fijado.
  /// Se registra aunque esté vacío porque lo que se afirma es que Aegis
  /// **no** recibe nada por defecto, y eso necesita un dato, no un silencio.
  List<String> enfoquesLanzados = [];
  List<String> promptsLanzados = [];
  List<String> proyectosLanzados = [];

  /// Si cada run salió con la puerta de verificación. Vacía significa que aún no
  /// se lanzó nada: una lista vacía pasa el `isEmpty` de cualquier `every`, así
  /// que el assert tiene que mirar que no esté vacía antes.
  List<bool> verificacionesLanzadas = [];

  /// Que `/ejecutar` responda como el bridge de verdad: `en_curso`. Ver A-066.
  bool enCurso = false;

  /// Los runs a los que se pidió parar y los textos con los que se dirigió.
  final List<String> parados = [];
  final List<String> dirigidos = [];
  List<String> ejecutadasFake = [];

  /// Lo que `readFicha` devuelve, para probar la pantalla sin bridge.
  FichaTexto? fichaFake;

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

  /// Lo que se decidió y lo que se instaló, en orden. El orden es el punto: un
  /// approve sin su `/instalar` detrás es exactamente el fallo que se cubría, y
  /// una lista de llamadas sueltas no lo delata.
  final List<String> deploys = [];

  @override
  Future<void> decideDeploy(String id, {required bool aprobar}) async =>
      deploys.add('${aprobar ? 'aprobar' : 'denegar'}:$id');

  @override
  Future<String> instalarDeploy(String id) async {
    deploys.add('instalar:$id');
    return 'la instalación arranca ya; el aviso del móvil confirma al terminar';
  }

  @override
  Future<FichaTexto> readFicha(String alias) async =>
      fichaFake ?? FichaTexto(alias: alias, texto: '', estado: 'sin_ficha');

  @override
  Future<ProjectInfo> writeFicha({
    required String alias,
    required String contenido,
  }) async {
    if (errorFicha != null) throw errorFicha!;
    contenidoFichaGuardado = contenido;
    return const ProjectInfo(alias: 'compra-unida', kind: 'encargo', estado: 'parcial');
  }

  /// Lo que se guardó en la última escritura de ficha, para comprobar que el
  /// markdown que genera el formulario llega al puente entero y con sus `---`.
  String? contenidoFichaGuardado;

  /// Si está a true, la escritura de la ficha **pública** falla. Es lo que
  /// permite probar que un guardado fallido no avanza a la siguiente sección.
  ///
  /// Va aparte de `errorPrivada` a propósito: si compartieran campo, no se
  /// podría probar a la vez el fallo de una y el éxito de la otra, que es
  /// justo el caso que importa —el usuario está en la pestaña del cliente y no
  /// debe verse afectado por lo que pasó en la técnica—.
  Object? errorFicha;

  /// Las altas que se pidieron, en orden. Sin esto, un test del formulario de
  /// alta no puede distinguir «no se envió» de «se envió mal».
  final List<Map<String, dynamic>> altasFake = [];

  /// Lo que devuelve `crearProyecto`. Por defecto, un alta recién hecha: con
  /// todo lo de la ficha pendiente, que es lo que de verdad pasa.
  ProyectoAlta altaFake = const ProyectoAlta(
    alias: 'encargo-nuevo',
    tipo: 'encargo',
    estado: 'incompleta (faltan 8)',
    faltan: [
      'Qué problema resuelve',
      'Para qué se usa',
      'Quién lo usa',
      'Criterio de aceptación',
      'Alcance dentro',
      'Alcance fuera',
      'Alternativas consideradas',
      'Cómo se verifica',
    ],
    mensaje: "Alta de 'encargo-nuevo' (tipo encargo) en el workspace.",
  );

  /// Si está a true, `crearProyecto` lanza. Es lo que permite probar el 409 del
  /// verificador y el 400 del alias inválido sin levantar un bridge de verdad.
  Object? errorAlta;

  /// Lo que devuelve `readFichaPrivada`. Por defecto, la plantilla sin
  /// rellenar: es lo que ve alguien que acaba de dar de alta un proyecto.
  FichaPrivada? privadaFake;

  String? contenidoPrivadaGuardado;

  Object? errorPrivada;

  @override
  Future<PlantillaFichas> plantillasFichas() async => plantillasFake;

  /// Lo que dice el bridge que hay que rellenar. Por defecto, un encargo con sus
  /// ocho secciones y una privada con las doce suyas.
  ///
  /// Va hardcodeado aquí, y no leído de `bridge/app/fichas.py`, a diferencia del
  /// test del generador: el fake existe para que un widget test monte pantalla sin
  /// bridge, y un `File` en un test de widget lo haría depender del disco.
  /// El test `generador_ficha_test.dart` es el que compara las dos listas, y ese
  /// sí lee el bridge. Así las tres copias no se pueden desincronizar sin que un
  /// test lo note.
  PlantillaFichas plantillasFake = const PlantillaFichas(
    secciones: {
      'encargo': [
        'Qué problema resuelve',
        'Para qué se usa',
        'Quién lo usa',
        'Criterio de aceptación',
        'Alcance dentro',
        'Alcance fuera',
        'Alternativas consideradas',
        'Cómo se verifica',
      ],
      'producto': [
        'Qué es',
        'Para quién',
        'Dónde estamos',
        'Próximo paso',
        'Invariantes',
        'Cómo se verifica',
      ],
      'herramienta': [
        'Qué es',
        'Por qué existe',
        'Invariantes',
        'Cómo se verifica',
        'Qué no toca',
      ],
    },
    tipos: ['encargo', 'producto', 'herramienta'],
    privada: [
      'Cliente y contacto',
      'El encargo, en sus palabras',
      'Modelo de cobro',
      'Presupuesto y pagos',
      'Fechas y plazos',
      'Hitos y facturación',
      'Horas extra o trabajos fuera de alcance',
      'Canal y reuniones',
      'Garantía y soporte',
      'Lo prometido',
      'Riesgos y qué lo haría pelota',
      'Lo que hay que tener cuidado de decir',
    ],
  );

  @override
  Future<ProyectoAlta> crearProyecto({
    required String alias,
    required String area,
    required String kind,
    String nombre = '',
    String alcance = '',
    String verificar = '',
    String db = '',
    String carpeta = '',
    bool yaExiste = false,
  }) async {
    if (errorAlta != null) throw errorAlta!;
    altasFake.add({
      'alias': alias,
      'area': area,
      'kind': kind,
      'nombre': nombre,
      'alcance': alcance,
      'verificar': verificar,
      'db': db,
      'carpeta': carpeta,
      'ya_existe': yaExiste,
    });
    return ProyectoAlta(
      alias: altaFake.alias.isEmpty ? alias : altaFake.alias,
      tipo: altaFake.tipo,
      estado: altaFake.estado,
      faltan: altaFake.faltan,
      mensaje: altaFake.mensaje,
    );
  }

  @override
  Future<FichaPrivada> readFichaPrivada(String alias) async {
    if (errorPrivada != null) throw errorPrivada!;
    return privadaFake ?? FichaPrivada(alias: alias, existe: false);
  }

  @override
  Future<FichaPrivada> writeFichaPrivada({
    required String alias,
    required String contenido,
  }) async {
    if (errorPrivada != null) throw errorPrivada!;
    contenidoPrivadaGuardado = contenido;
    return FichaPrivada(alias: alias, texto: contenido, existe: true);
  }

  @override
  Future<String> startAutopilot({
    required String prompt,
    String? project,
    String? instructions,
    int maxSteps = 6,
    bool remember = true,
    bool verify = false,
    String? token,
    String? enfoque,
  }) async {
    promptsLanzados.add(prompt);
    if (project != null && project.isNotEmpty) proyectosLanzados.add(project);
    // Se registra aparte de `promptsLanzados` porque es el dato que se olvidó: el
    // móvil mandaba `verificar: false` fijo, y desde aquí ninguna escritura pasaba
    // por el verificador ni en un proyecto marcado.
    verificacionesLanzadas.add(verify);
    if (token != null && token.isNotEmpty) tokensGastados.add(token);
    // Se registra **siempre**, vacio incluido: lo que hay que poder afirmar es
    // que Aegis NO recibe enfoque por defecto, y eso necesita un dato.
    enfoquesLanzados.add(enfoque ?? '');
    return 'autopilot_test';
  }

  @override
  Future<List<Enfoque>> enfoques() async => const [
        Enfoque(
          nombre: 'arquitectura',
          titulo: 'Cómo se va a construir',
          resumen: 'para decidir cómo, y defender por qué esta y no las otras',
          restringe: ['aegis_write_file', 'aegis_patch_file'],
          bloqueChars: 1970,
        ),
      ];

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

  // El fake se queda en silencio a propósito: los tests que suben un run
  // comprueban cómo se pinta, no que el bucle se deje dirigir. Registrar las
  // llamadas sí es útil, y por eso están en `parados` y `dirigidos`.
  @override
  Future<void> stopAutopilot(String runId) async => parados.add(runId);

  @override
  Future<void> steerAutopilot(String runId, String text) async =>
      dirigidos.add(text);

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
    // Permite fingir la respuesta real del bridge, que es `en_curso` (A-066).
    if (enCurso) {
      return EjecucionAprobada(
        tool: p.isEmpty ? 'project_create' : p.first.tool,
        estado: 'en_curso',
        detalle: 'la llamada arranca ya; el rastro y el aviso confirman al terminar',
      );
    }
    // `estado: "terminada"` a propósito: el bridge responde `en_curso` y ejecuta
    // después, así que el camino de «terminada con resultado» necesita su propio
    // fake. El `en_curso` real lo cubre `deploy_flow_test`.
    return EjecucionAprobada(
      tool: p.isEmpty ? 'project_create' : p.first.tool,
      estado: 'terminada',
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

  // -- La actualización de la app ---------------------------------------------
  //
  // ## Por qué está en el falso y no se deja abstracto
  // Porque toda la suite usa este falso, y añadir un método abstracto obliga a
  // tocarlo para que los tests que no hablan de actualizaciones| que
  // inventen una implementación. Aquí se pone la que casi siempre sirve: la app
  // está al día.

  /// Lo que el bridge «dice» que tiene. Los tests que hablan de actualizaciones
  /// lo mueven antes de preguntar, en vez de construir un falso nuevo.
  ///
  /// ## Por qué el falso pasa por [VersionApk.evaluado]
  /// Porque es lo que hace el repositorio real. Si devolviera este objeto tal
  /// cual, [VersionApk.disponible] se quedaría en `false` siempre y **ningún
  /// test vería el botón de bajar**: todos pasarían probando la pantalla
  /// equivocada, y un falso que hace pasar tests sin probar nada es peor que no
  /// tenerlo. Lo que se guarda es lo que el bridge contesta; la comparación con
  /// lo instalado la hace la misma regla de producción.
  VersionApk versionApkDelBridge = const VersionApk(versionCode: 0);

  /// Si la descarga «funciona». Para probar el camino de error del diálogo.
  bool fallaDescarga = false;

  /// Cuántos reportes de progreso manda la descarga falsa.
  ///
  /// ## Por qué existe
  /// A `0` por defecto porque una descarga que termina en el acto no deja que la
  /// barra se pinte **nunca**: el `await` se resuelve antes de que el framework
  /// tenga un opportunity de dibujar. Un test de la barra escrito contra un falso
  /// instantáneo pasa por probarlo todo menos la barra.
  ///
  /// El diálogo se ve de verdad en cuanto este número es >0: entre un `pump` y
  /// otro hay un frame, y en ese frame la barra existe.
  int pasosDeProgreso = 0;

  @override
  Future<VersionApk> versionApk({required int instalado, required bool hayPermiso}) async =>
      VersionApk.evaluado(
        instalado: instalado,
        hayPermiso: hayPermiso,
        delBridge: versionApkDelBridge,
      );

  @override
  Future<String> descargarApk({
    required String destino,
    void Function(int recibidos, int total)? onProgreso,
  }) async {
    if (fallaDescarga) throw StateError('no se pudo descargar');
    final total = 100 * 1024 * 1024; // 100 MB, como un APK de verdad
    for (var i = 1; i <= pasosDeProgreso; i++) {
      onProgreso?.call(total ~/ pasosDeProgreso * i, total);
      // Sin este `delay`, los reportes salen en el mismo microtask y el widget
      // los ve todos de golpe: hay progreso en los datos pero ninguno en la
      // pantalla.
      await Future<void>.delayed(const Duration(milliseconds: 10));
    }
    onProgreso?.call(total, total);
    return destino;
  }
}
