/// Implementación del repositorio: Dio (REST).
///
/// ## Por qué no hay WebSocket
/// El socket servía para el run de Hermes (`POST /tasks`), que además tenía
/// **cero tools** (`platform_toolsets.api_server: []` en Hermes) y era el motor
/// que el repo ya había medido como no fiable con un 7B. El autopilot va por
/// `POST /autopilot/start` y se sigue por polling de `GET /autopilot/{id}`, que
/// además es lo que ya hace la pantalla de Ahora desde que se quitó el
/// interruptor de motor.
library;

import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';

import '../../core/config/app_config.dart';
import '../../core/network/descubrimiento.dart';
import '../../core/network/instalador_nativo.dart';
import '../../core/network/resolvedor.dart';
import '../../domain/repositories/agent_repository.dart';
import '../models/agent_models.dart';
import '../models/asistente_models.dart';
import '../models/version_apk.dart';

/// De dónde viene esta app: `emulador` o `telefono`.
///
/// No es metadato: el emulador y el teléfono llegan al bridge los dos por
/// `adb reverse`, así que los dos se ven como `127.0.0.1` y son indistinguibles.
/// Esta cabecera es lo que permite al bridge decir "esto vino del emulador", que
/// es la prueba de que el humo es real, y responder a la pregunta de fondo:
/// ¿cuándo tocó Aegis mi teléfono?
const String _origen = String.fromEnvironment('AEGIS_ORIGIN', defaultValue: 'telefono');

/// Token de la API de operación, va en `X-Aegis-Token`.
///
/// ## Por qué va con `--dart-define` y no hardcodeado
/// Es una credencial, y una credencial en el código es una credencial en git.
/// Como `--dart-define` se compila dentro del APK, tampoco es un secreto que
/// valga para siempre: cualquiera con el APK puede extraerlo. Para una app de
/// una persona en su red privada es aceptable, y es mejor que no tener puerta
/// ninguna; para algo compartido, no.
///
/// ## Por qué vacío funciona
/// Vacío = el bridge no exige token (`AEGIS_API_KEY` sin valor). Así la app
/// arranca el primer día sin tener que generar un secreto, y el día que actives
/// la clave el token ya viaja en la cabecera. Los dos lados van juntos: si
/// pones la clave en el bridge sin recompilar la app, lo nuevo devuelve 401.
const String _token = String.fromEnvironment('AEGIS_TOKEN', defaultValue: '');

class AgentRepositoryImpl implements AgentRepository {
  /// ## Por qué el resolvedor se puede pasar
  /// Para los tests: sin eso, probar que la app elige bien el bridge exigiría
  /// levantar un bridge real y abrir un socket mDNS de verdad. Es el mismo motivo
  /// que en `Resolvedor`.
  AgentRepositoryImpl({required this.config, Resolvedor? resolvedor})
      : _resolutor = resolvedor,
        _dio = Dio(BaseOptions(
          connectTimeout: const Duration(seconds: 10),
          receiveTimeout: const Duration(seconds: 10),
          headers: {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'X-Aegis-Origen': _origen,
            // Se manda siempre, incluso vacía: una cabecera vacía y una
            // ausente se comportan igual en el bridge, y mandarla hace que el
            // problema sea "el token no viaja" y no "falta la cabecera".
            'X-Aegis-Token': _token,
          },
        )) {
    _dio.interceptors.add(
      InterceptorsWrapper(onRequest: (o, _) async {
        o.baseUrl = await _base();
      }),
    );
  }

  final AppConfig config;
  final Dio _dio;
  final Resolvedor? _resolutor;

  /// La base ya resuelta. Vive aquí para que la resolución pase **una vez**.
  String? _baseResuelta;
  Future<String>? _baseEnCurso;

  /// La base contra la que hablar ahora mismo.
  ///
  /// ## Por qué una `Future` cacheada y no un `await` en cada llamada
  /// Sin cachear, cada una de las 35 llamadas del repositorio esperaría a una
  /// resolución que abre un socket mDNS: tres segundos antes de contestarte. Y
  /// en el peor caso lo haría cada pantalla por su cuenta, dejando varios
  /// sockets abiertos en el dispositivo.
  ///
  /// ## Por qué guarda la `Future` en curso y no solo el resultado
  /// Porque dos pantallas piden la base a la vez en el arranque, y sin esto se
  /// hacen dos búsquedas simultáneas. Con la `Future` en curso, la segunda se
  /// engancha a la primera y espera su resultado.
  Future<String> _base() async {
    final hecha = _baseEnCurso;
    if (hecha != null) return hecha;
    final f = _resolutorDe().resolver().then((r) {
      // Si nadie respondió, se vuelve al host compilado en vez de dejar la app
      // sin destino.
      // El error tiene que salir de la llamada de verdad, con su mensaje de
      // HTTP, y no de una resolución que se quedó sin respuesta.
      // Sin host compilado se cae a `localhost`, que es lo que funciona con
      // `adb reverse` y en el emulador, que es donde se desarrolla.
      _baseResuelta =
          r ?? (config.usesMeshHostname ? config.httpBase : 'http://localhost:8000');
      return _baseResuelta!;
    });
    _baseEnCurso = f;
    return f;
  }

  Resolvedor _resolutorDe() =>
      _resolutor ?? Resolvedor(config: config, descubridor: Descubridor());

  /// Descarta la base cacheada. Para cuando alguien ha movido el bridge y
  /// quiere que la app lo busque otra vez.
  void olvidarBase() {
    _baseResuelta = null;
    _baseEnCurso = null;
  }

  @override
  Future<BridgeHealth> health() async {
    final r = await _dio.get<Map<String, dynamic>>('/health');
    return BridgeHealth.fromJson(r.data!);
  }

  @override
  Future<List<String>> models() async {
    final r = await _dio.get<Map<String, dynamic>>('/models');
    final models = r.data?['available'] as List? ?? const [];
    return models.cast<String>();
  }

  @override
  Future<List<ProjectInfo>> projects() async {
    final r = await _dio.get<Map<String, dynamic>>('/proyectos');
    final lista = (r.data!['proyectos'] as List?) ?? const [];
    return lista.whereType<Map<String, dynamic>>().map(ProjectInfo.fromJson).toList();
  }

  @override
  Future<FichaTexto> readFicha(String alias) async {
    final r = await _dio.get<Map<String, dynamic>>('/fichas/$alias');
    return FichaTexto.fromJson(r.data!);
  }

  @override
  Future<List<Enfoque>> enfoques() async {
    final r = await _dio.get<Map<String, dynamic>>(
        '/enfoques');
    return ((r.data?['enfoques'] as List?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(Enfoque.fromJson)
        .toList();
  }

  @override
  Future<ProjectInfo> writeFicha({
    required String alias,
    required String contenido,
  }) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '/fichas/$alias',
      data: jsonEncode({'contenido': contenido}),
    );
    final d = r.data!;
    // El bridge devuelve el estado ya calculado: la app no lo adivina, lo lee.
    return ProjectInfo(
      alias: (d['alias'] ?? alias) as String,
      kind: (d['kind'] ?? '') as String,
      estado: d['estado'] == 'completa' ? 'completa' : 'parcial',
      faltan: ((d['faltan'] as List?) ?? const []).cast<String>(),
    );
  }

  @override
  Future<PlantillaFichas> plantillasFichas() async {
    final r = await _dio.get<Map<String, dynamic>>(
      '/fichas/plantillas',
    );
    return PlantillaFichas.fromJson(r.data!);
  }

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
    final r = await _dio.post<Map<String, dynamic>>(
      '/proyectos',
      // Se manda el mapa entero, con los vacíos incluidos: el modelo del
      // bridge los declara con valor por defecto, y mandar solo lo que hay
      // obligaría a construir el body a mano y a que se desincronice del
      // contrato sin que nada avise.
      data: jsonEncode({
        'alias': alias,
        'area': area,
        'kind': kind,
        'nombre': nombre,
        'alcance': alcance,
        'verificar': verificar,
        'db': db,
        'carpeta': carpeta,
        'ya_existe': yaExiste,
      }),
    );
    return ProyectoAlta.fromJson(r.data!);
  }

  @override
  Future<FichaPrivada> readFichaPrivada(String alias) async {
    final r = await _dio.get<Map<String, dynamic>>(
      '/fichas/$alias/privada',
    );
    // Sin `existe` el bridge no lo está mandando y la app lo trataría como
    // una ficha vacía que se puede guardar: mejor un tipo explícito.
    return FichaPrivada.fromJson(r.data!);
  }

  @override
  Future<FichaPrivada> writeFichaPrivada({
    required String alias,
    required String contenido,
  }) async {
    await _dio.post<Map<String, dynamic>>(
      '/fichas/$alias/privada',
      data: jsonEncode({'contenido': contenido}),
    );
    // El POST no devuelve el texto guardado, solo que se escribió. Se relee
    // para que quien llama tenga el documento real y no una suposición: si el
    // puente normalizara algo al escribir, aquí se vería.
    return readFichaPrivada(alias).timeout(
      const Duration(seconds: 5),
      onTimeout: () => FichaPrivada(alias: alias, texto: contenido, existe: true),
    );
  }

  @override
  Future<Actividad> actividad() async {
    final r = await _dio.get<Map<String, dynamic>>('/actividad');
    return Actividad.fromJson(r.data!);
  }

  @override
  Future<DeployState> deployState() async {
    final r = await _dio.get<Map<String, dynamic>>('/deploys');
    return DeployState.fromJson(r.data!);
  }

  @override
  Future<void> decideDeploy(String id, {required bool aprobar}) async {
    await _dio.post<Map<String, dynamic>>(
      '/deploys/$id',
      data: jsonEncode({'decision': aprobar ? 'aprobar' : 'denegar'}),
    );
  }

  @override
  Future<String> instalarDeploy(String id) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '/deploys/$id/instalar',
    );
    // Devuelve el detalle y no un `void`: quien aprueba tiene que poder decir
    // "arranca" y no "hecho", porque la instalación va en un hilo aparte y el
    // resultado llega en el aviso, no en esta respuesta.
    return (r.data?['detalle'] as String?) ?? 'la instalación arranca ya';
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
    final r = await _dio.post<Map<String, dynamic>>(
      '/autopilot/start',
      data: jsonEncode({
        'prompt': prompt,
        'max_steps': maxSteps,
        'remember': remember,
        'verificar': verify,
        if (project != null && project.isNotEmpty) 'project': project,
        if (instructions != null && instructions.isNotEmpty) 'instructions': instructions,
        if (token != null && token.isNotEmpty) 'token': token,
        if (enfoque != null && enfoque.isNotEmpty) 'enfoque': enfoque,
      }),
    );
    return r.data!['run_id'] as String;
  }

  @override
  Future<AutopilotRun> autopilotStatus(String runId) async {
    final r = await _dio.get<Map<String, dynamic>>(
      '/autopilot/$runId',
    );
    return AutopilotRun.fromJson(r.data!);
  }

  @override
  Future<void> stopAutopilot(String runId) async {
    await _dio.post<Map<String, dynamic>>('/autopilot/$runId/stop');
  }

  @override
  Future<void> steerAutopilot(String runId, String text) async {
    await _dio.post<Map<String, dynamic>>(
      '/autopilot/$runId/steer',
      data: jsonEncode({'text': text}),
    );
  }

  // -- Lo que Aegis sabe ---------------------------------------------------

  @override
  Future<Memoria> memoria({String consulta = '', int limite = 20}) async {
    final r = await _dio.get<Map<String, dynamic>>(
      '/memoria',
      queryParameters: {
        'limite': limite,
        if (consulta.isNotEmpty) 'consulta': consulta,
      },
    );
    return Memoria.fromJson(r.data!);
  }

  @override
  Future<List<RunHistorial>> runs({int limite = 20, String proyecto = ''}) async {
    final r = await _dio.get<Map<String, dynamic>>(
      '/runs',
      queryParameters: {
        'limite': limite,
        if (proyecto.isNotEmpty) 'proyecto': proyecto,
      },
    );
    return ((r.data?['runs'] as List?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(RunHistorial.fromJson)
        .toList();
  }

  @override
  Future<Autonomia> autonomia() async {
    final r = await _dio.get<Map<String, dynamic>>('/autonomy');
    return Autonomia.fromJson(r.data!);
  }

  @override
  Future<String> modoAutonomia(String modo) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '/autonomy/modo',
      data: jsonEncode({'modo': modo}),
    );
    return (r.data?['modo'] ?? modo) as String;
  }

  @override
  Future<List<String>> marcarProyecto(String alias, {required bool escribir}) async {
    if (!escribir) {
      await _dio.delete<Map<String, dynamic>>('/autonomy/$alias');
    } else {
      await _dio.post<Map<String, dynamic>>(
        '/autonomy/$alias',
        data: jsonEncode({'permiso': 'escribir'}),
      );
    }
    final r = await _dio.get<Map<String, dynamic>>('/autonomy');
    return ((r.data?['escritura'] as Map?) ?? const {}).keys.cast<String>().toList();
  }

  @override
  Future<List<Aprobacion>> aprobaciones() async {
    final r = await _dio.get<Map<String, dynamic>>('/aprobaciones');
    final lista = <Aprobacion>[];
    for (final clave in const ['aprobadas', 'pendientes']) {
      lista.addAll(((r.data?[clave] as List?) ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(Aprobacion.fromJson));
    }
    return lista;
  }

  @override
  Future<String?> resolverAprobacion(String id, {required bool aprobar}) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '/aprobaciones/$id',
      data: jsonEncode({'decision': aprobar ? 'aprobar' : 'denegar'}),
    );
    return r.data?['token'] as String?;
  }

  @override
  Future<EjecucionAprobada> ejecutarAprobacion(String id) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '/aprobaciones/$id/ejecutar',
    );
    return EjecucionAprobada.fromJson(r.data ?? const {});
  }

  @override
  Future<void> denegarConMotivo(String id, String motivo) async {
    await _dio.post<Map<String, dynamic>>(
      '/aprobaciones/$id/motivo',
      data: jsonEncode({'contenido': motivo}),
    );
  }

  // -- Tus cosas -----------------------------------------------------------

  @override
  Future<List<Nota>> notas({String proyecto = ''}) async {
    final r = await _dio.get<Map<String, dynamic>>(
      '/notas',
      queryParameters: {if (proyecto.isNotEmpty) 'proyecto': proyecto},
    );
    return ((r.data?['notas'] as List?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(Nota.fromJson)
        .toList();
  }

  @override
  Future<Nota> crearNota({String titulo = '', String cuerpo = '', String proyecto = ''}) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '/notas',
      data: jsonEncode({'titulo': titulo, 'cuerpo': cuerpo, 'proyecto': proyecto}),
    );
    return Nota.fromJson(r.data!);
  }

  @override
  Future<void> borrarNota(String id) async {
    await _dio.delete<Map<String, dynamic>>('/notas/$id');
  }

  @override
  Future<List<Tarea>> tareas({String estado = '', String proyecto = ''}) async {
    final r = await _dio.get<Map<String, dynamic>>(
      '/tareas',
      queryParameters: {
        if (estado.isNotEmpty) 'estado': estado,
        if (proyecto.isNotEmpty) 'proyecto': proyecto,
      },
    );
    return ((r.data?['tareas'] as List?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(Tarea.fromJson)
        .toList();
  }

  @override
  Future<Tarea> crearTarea({
    required String titulo,
    String notas = '',
    String proyecto = '',
    String para = '',
  }) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '/tareas',
      data: jsonEncode({'titulo': titulo, 'notas': notas, 'proyecto': proyecto, 'para': para}),
    );
    return Tarea.fromJson(r.data!);
  }

  @override
  Future<Tarea> actualizarTarea(
    String id, {
    String? titulo,
    String? notas,
    String? para,
    String? estado,
  }) async {
    // Los campos que no cambian no se mandan: `PATCH` con un `null` explícito
    // vaciaría el campo, y "no tocar" y "vaciar" son cosas distintas.
    final cambios = <String, String>{};
    if (titulo != null) cambios['titulo'] = titulo;
    if (notas != null) cambios['notas'] = notas;
    if (para != null) cambios['para'] = para;
    if (estado != null) cambios['estado'] = estado;
    final r = await _dio.patch<Map<String, dynamic>>(
      '/tareas/$id',
      data: jsonEncode(cambios),
    );
    return Tarea.fromJson(r.data!);
  }

  // -- Actualización de la propia app ---------------------------------------
  //
  // Esto NO es una puerta atrás a instalar nada: aquí solo se baja un fichero.
  // Lo que lo instala es el diálogo del sistema de Android, y lo que autoriza
  // la publicación del binario es la cola de aprobaciones de siempre, en el
  // bridge. La separación es deliberada — si esto instalara, «nada irreversible
  // sin OK» se podría saltar con una descarga.

  /// Qué versión del APK tiene el bridge, y si hay algo más nuevo que lo
  /// instalado.
  ///
  /// Consulta con `HEAD`, no bajando el fichero: las tres cabeceras que dice
  /// esto pesan menos que una cabecera, y el cuerpo son 50 MB que no sirven para
  /// responder «¿tengo la última?».
  @override
  Future<VersionApk> versionApk({required int instalado, required bool hayPermiso}) async {
    // `telefono` es el **destino**, no el nombre del fichero. El bridge compone
    // el nombre con su perfil; mandar el fichero entero devuelve un 404 con
    // «destino desconocido», que es un mensaje sobre un parámetro mal escrito
    // donde lo que de verdad se quería preguntar era la versión.
    try {
      final r = await _dio.head<void>(
        '/apk/telefono',
        options: Options(
          responseType: ResponseType.bytes,
          // Sin esto el 404 del «no hay APK» entraría por la excepción y el
          // motivo del 409 —«el APK es más viejo que el código»— se perdería.
          validateStatus: (s) => s != null && s < 500,
        ),
      );
      return VersionApk.evaluado(
        instalado: instalado,
        hayPermiso: hayPermiso,
        delBridge: VersionApk(
          versionCode: int.tryParse(_cabecera(r, 'x-aegis-version') ?? '') ?? 0,
          versionName: _cabecera(r, 'x-aegis-version-name') ?? '',
          etag: _cabecera(r, 'etag') ?? '',
        ),
        motivo: r.statusCode == 409 ? (_cuerpo(r) ?? 'el bridge no tiene un APK al día') : '',
      );
    } on Object {
      // Sin bridge, o con un error de red. No es una excepción que merezca tirar
      // la app: lo que se dice es que no se pudo comprobar.
      return VersionApk.evaluado(
        instalado: instalado,
        hayPermiso: hayPermiso,
        motivo: 'no se pudo preguntar al bridge por su APK',
      );
    }
  }

  /// Baja el APK al directorio que el `FileProvider` expone.
  ///
  /// ## Por qué se escribe a un fichero y no a memoria
  /// Son 50 MB. En memoria son 50 MB de RAM que el proceso puede no tener
  /// (Android mata por memoria antes que por disco), y además habría que
  /// escribirlos después. Ir a disco de una vez es lo que hace que esto funcione
  /// en un móvil de gama baja.
  ///
  /// Devuelve la ruta, que es lo que se le pasa al canal nativo para instalar.
  @override
  Future<String> descargarApk({
    required String destino,
    void Function(int recibidos, int total)? onProgreso,
  }) async {
    final base = await _base();
    final destino_ = destino.isEmpty ? await InstaladorPorCanal().destino() : destino;
    final dio = Dio(BaseOptions(
      baseUrl: base,
      // Sin timeout de escritura: un APK de 50 MB por una línea de datos
      // lenta es lento, y cortar la descarga a los 10 s la deja siempre a medias.
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(minutes: 10),
      headers: {
        'X-Aegis-Token': _token,
        'X-Aegis-Origen': _origen,
      },
    ));
    final r = await dio.download(
      '/apk/telefono',
      destino_,
      onReceiveProgress: onProgreso,
      // Sin esto, un 409 —«el APK es más viejo que el código»— deja un fichero
      // de texto de 40 bytes en el destino y el instalador recibe un fichero que
      // no es un APK, con un error que no dice nada.
      deleteOnError: true,
      options: Options(validateStatus: (s) => s != null && s < 300),
    );
    if (r.statusCode != 200) {
      throw StateError('el bridge no sirvió el APK (HTTP ${r.statusCode})');
    }
    return destino_;
  }

  String? _cabecera(Response<dynamic> r, String nombre) {
    final v = r.headers.value(nombre);
    return (v == null || v.isEmpty) ? null : v;
  }

  String? _cuerpo(Response<dynamic> r) {
    final d = r.data;
    if (d is String && d.isNotEmpty) return d;
    return null;
  }
}
