/// Contrato de la capa domain: el repositorio que consume el bridge.
library;

import '../../data/models/agent_models.dart';
import '../../data/models/asistente_models.dart';

/// Lo que pasó al ejecutar una aprobación.
///
/// `ok` es si la tool corrió **y no denegó**: las tools de Aegis devuelven el
/// motivo como texto en vez de lanzar, así que un "hecho" sobre un "RECHAZADO"
/// detrás sería el falso éxito que el bridge ya pagó una vez.
/// Lo que devuelve `POST /aprobaciones/{id}/ejecutar`.
///
/// ## Por qué `estado` y no `ok`
/// La ejecución va **en segundo plano**: una tool de nivel 3 puede ser la puerta
/// completa del despliegue —`flutter analyze`, `flutter test` y el humo en el
/// emulador— y eso son minutos. Con la respuesta esperando, el cliente se cansaba
/// a los 10 s y pintaba «No pude ejecutar» con el token ya gastado y la
/// instalación a medias: un gesto bien hecho que se contaba como fallido.
///
/// Así que la respuesta dice que **arrancó**, y el desenlace llega por el rastro y
/// el aviso. `ok` queda para cuando viene `estado: "terminada"`.
class EjecucionAprobada {
  const EjecucionAprobada({
    required this.tool,
    this.estado = 'en_curso',
    this.detalle = '',
    this.ok = false,
    this.resultado = '',
    this.error = '',
  });

  final String tool;

  /// `en_curso` | `terminada`. Lo que sea nuevo tiene que saber nombrarse aquí.
  final String estado;

  /// Lo que el bridge responde, en una frase, para que el móvil lo enseñe sin
  /// inventar un "hecho" que todavía no ha pasado.
  final String detalle;
  final bool ok;
  final String resultado;
  final String error;

  bool get terminada => estado == 'terminada';

  factory EjecucionAprobada.fromJson(Map<String, dynamic> j) => EjecucionAprobada(
        tool: (j['tool'] ?? '') as String,
        estado: (j['estado'] ?? 'en_curso') as String,
        detalle: (j['detalle'] ?? '') as String,
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


  /// Proyectos que puede operar Aegis, con el estado de su ficha.
  Future<List<ProjectInfo>> projects();

  /// La ficha de un proyecto en texto, para poder corregirla antes de guardarla.
  ///
  /// Sin esto no se puede escribir una ficha desde el móvil: el botón que lo
  /// hacía vivía en una pantalla atada al motor de conversación, que ya no está.
  Future<FichaTexto> readFicha(String alias);

  /// Guarda la ficha **sin pasar por el modelo**. Se comprobó que un 7B copiando
  /// un texto literal se come los `---` del frontmatter y deja la ficha sin
  /// tipo, que es justo lo que la puerta rechaza.
  Future<ProjectInfo> writeFicha({
    required String alias,
    required String contenido,
  });

  /// Da de alta un proyecto: carpeta, registro, ficha pública y ficha privada.
  ///
  /// ## Por qué existe esto
  /// `project_create` ya estaba como tool del agente, pero solo se alcanzaba
  /// desde un run de autopilot. Eso obligaba a pasar por el modelo para escribir
  /// un alta que es enteramente determinista —una carpeta, un JSON y dos
  /// ficheros de texto—, con el modelo como intermediario innecesario y un
  /// aprobado de nivel 3 en medio. El alta es de la persona, no del agente.
  ///
  /// Devuelve qué secciones de la ficha quedan por escribir, porque un alta
  /// nunca las deja todas: eso lo sabe la persona, no el puente.
  Future<ProyectoAlta> crearProyecto({
    required String alias,
    required String area,
    required String kind,
    String nombre,
    String alcance,
    String verificar,
    String db,
    String carpeta,
    bool yaExiste,
  });

  /// Qué secciones hay que escribir en una ficha, por tipo.
  ///
  /// Sin esto, el formulario tendría su propia lista y se desincronizaría del
  /// bridge: el día que allí añadiese una sección, esta pantalla seguiría sin
  /// preguntarla y la puerta la seguiría exigiendo. Un bug sin ninguna pista de
  /// por qué pasa.
  ///
  /// Las secciones de la ficha privada vienen en el mismo sitio, y **no son
  /// obligatorias**: es una lista de temas, porque el modelo de cobro no tiene
  /// forma canónica.
  Future<PlantillaFichas> plantillasFichas();

  /// La ficha comercial del proyecto: cliente, presupuesto, forma de pago.
  ///
  /// Fuera de git por diseño —es información de un tercero— y por eso va en
  /// endpoint aparte: mezclarla con la pública acabaría metiendo datos de un
  /// cliente en un fichero versionado.
  ///
  /// No falla con 404 cuando el proyecto no tiene ficha privada: es el estado
  /// normal de un proyecto recién dado de alta, y el editor tiene que poder
  /// abrirse para crearla.
  Future<FichaPrivada> readFichaPrivada(String alias);

  /// Guarda la ficha comercial, también **sin pasar por el modelo**.
  ///
  /// Por el mismo motivo que [writeFicha]: a un 7B copiando un texto literal se
  /// le comen los `---`. Aquí además el contenido es el dato que Aegis tiene
  /// prohibido inventar —el precio, la fecha—, así que sale de una persona o no
  /// sale.
  Future<FichaPrivada> writeFichaPrivada({
    required String alias,
    required String contenido,
  });

  /// Fases de trabajo que el puente ofrece: `idea`, `arquitectura`, …
  ///
  /// Qué enfoques existen, para poder **fijar** uno a mano.
  ///
  /// Lo normal es que Aegis pida el suyo y aquí no haya nada que hacer: esto está
  /// para cuando la derivación falla y hay que corregirlo sin cambiar el encargo.
  /// Viene del disco del bridge, no de una lista en la app: añadir un enfoque es
  /// un `.md` más una entrada en el índice, sin tocar esto.
  ///
  /// Devuelve título y resumen, **no** el texto del enfoque: son ~2000 caracteres
  /// por enfoque para descargarlos en el móvil y igual no usarse nunca.
  Future<List<Enfoque>> enfoques();

  /// Despliegues esperando aprobación en el teléfono. Mientras haya algo aquí,
  /// Aegis **no ha instalado nada**: está esperando a que lo apruebes.
  Future<DeployState> deployState();

  /// Aprueba (o deniega) una instalación pendiente. Una aprobación es de un
  /// solo uso: sirve para instalar una vez.
  ///
  /// **Aprobar no instala.** Deja el token emitido, y hace falta llamar a
  /// [instalarDeploy]. Quien approve tiene que encadenar las dos.
  Future<void> decideDeploy(String id, {required bool aprobar});

  /// Instala un despliegue **ya aprobado**, sin que pase por el agente, y
  /// devuelve el detalle que el bridge responde (que es una confirmación de que
  /// **arranca**, no de que terminó).
  ///
  /// ## Por qué es una llamada aparte y no parte de [decideDeploy]
  /// El token se gasta dentro del bridge y no sale hacia el agente, y por eso
  /// instalar va por su propio endpoint. La razón para no fundirlas en el
  /// cliente está medida: aprobar sin instalar se convirtió en medio gesto, y
  /// quien aprobó desde la app se quedó con dos OK dados y **nada instalado**.
  /// Separarlas en el repo hace que el error sea visible: si `_decidir` olvida
  /// la segunda llamada, sale de aquí mirando.
  Future<String> instalarDeploy(String id);

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
    String? enfoque,
  });

  /// Progreso del run de autopilot. `AutopilotRun.finished` dice si paró.
  Future<AutopilotRun> autopilotStatus(String runId);

  /// Pide que el run deje de empezar pasos.
  ///
  /// No es una cancelación: el paso que ya está corriendo **se termina** y queda
  /// en la traza, porque `_execute` es síncrono y cortar a mitad dejaría una
  /// escritura sin el paso que la explica. La parada es "no empieces otro".
  Future<void> stopAutopilot(String runId);

  /// Mete una instrucción en un run que ya está corriendo.
  ///
  /// No interrumpe el paso en curso: entra en una cola y el bucle la drena antes
  /// del siguiente, que es el mismo criterio que la parada.
  Future<void> steerAutopilot(String runId, String text);

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

}
