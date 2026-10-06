/// Las cosas que Aegis recuerda, lo que te ha pedido y lo que hay en tu agenda.
///
/// ## Por qué estos modelos no traen el texto
/// La memoria del agente guarda el prompt que le escribiste y su respuesta. La
/// app **no** los muestra: se ve qué hizo, cuándo, con cuántas herramientas y
/// si salió bien. El texto se queda en el almacén del bridge.
///
/// ## Por qué no es un capricho
/// Todo lo que le cuentas a Aegis queda a un `GET` de distancia de cualquier
/// otra cosa en la red privada. Y no aporta para lo que se pinta aquí: para
/// saber "qué hice con qué", el metadato ya dice todo. Un historial que se puede
/// borrar desde la propia app es la condición para que exista.
///
/// ## Por qué `Episodio` no lleva el `outcome`
/// El endpoint ya filtra a `success` (A-016: un fallo presentado como solución es
/// instrucción contraria, y el modelo lo copia). Un campo `ok: true` siempre
/// puesto no informa de nada y ocupa sitio: que no exista es la información.
library;

/// Un episodio, en metadatos.
class Episodio {
  const Episodio({
    required this.runId,
    this.proyecto = '',
    this.herramientas = const [],
    this.pasos = 0,
    this.epoca = '',
  });

  final String runId;
  final String proyecto;
  final List<String> herramientas;
  final int pasos;
  final String epoca;

  factory Episodio.fromJson(Map<String, dynamic> j) => Episodio(
        runId: (j['run_id'] ?? '') as String,
        proyecto: (j['proyecto'] ?? '') as String,
        herramientas: ((j['herramientas'] as List?) ?? const []).cast<String>(),
        pasos: (j['pasos'] as num?)?.toInt() ?? 0,
        epoca: (j['epoca'] ?? '') as String,
      );
}

/// Lo que Aegis recuerda. [nota] lleva el porqué de los filtrados.
class Memoria {
  const Memoria({this.episodios = const [], this.nota = '', this.estado = const {}});

  final List<Episodio> episodios;
  final String nota;
  final Map<String, dynamic> estado;

  factory Memoria.fromJson(Map<String, dynamic> j) => Memoria(
        episodios: ((j['episodios'] as List?) ?? const [])
            .whereType<Map<String, dynamic>>()
            .map(Episodio.fromJson)
            .toList(),
        nota: (j['nota'] ?? '') as String,
        estado: (j['estado'] as Map?)?.cast<String, dynamic>() ?? const {},
      );

  /// Cuándo fue la última vez. `null` si nunca hizo nada.
  ///
  /// Viene del propio episodio y no de `DateTime.now()`: una getter que
  /// devuelve la hora actual siempre "sabe" cuándo fue la última vez, y eso es
  /// un dato inventado. Sin `epoca` —que es lo que pasa hoy, porque los
  /// episodios se guardaron con `at` vacío— no se dice nada en vez de mentir.
  DateTime? get ultimaVez {
    if (episodios.isEmpty) return null;
    return DateTime.tryParse(episodios.first.epoca);
  }
}

/// Una petición de permiso esperando tu OK — o ya concedida y sin gastar.
///
/// La misma clase cubre los dos estados, y se distinguen por [token]: vacío es
/// "te están preguntando", con token es "ya dijiste que sí y queda por
/// ejecutarla". Un solo widget para las dos, porque el segundo estado es
/// justamente el único en el que Aegis puede seguir solo.
class Aprobacion {
  const Aprobacion({
    required this.id,
    required this.tool,
    required this.motivo,
    required this.paso,
    this.runId = '',
    this.proyecto = '',
    this.creado = '',
    this.token = '',
  });

  final String id;
  final String tool;

  /// Lo que Aegis quiere hacer, **en sus palabras**. No el nombre de la tool:
  /// "voy a migrar la base de compra-unida" se puede aprobar leyendo.
  final String motivo;
  final int paso;
  final String runId;
  final String proyecto;
  final String creado;

  /// Token de un solo uso de una aprobación ya concedida. Vacío si la petición
  /// sigue pendiente. No es una credencial: solo vale para **esta** tool con
  /// **estos** argumentos, y el puente lo gasta al primer uso.
  final String token;

  /// Ya la concediste y todavía nadie la ha gastado: se puede relanzar el run.
  bool get relanzable => token.isNotEmpty;

  factory Aprobacion.fromJson(Map<String, dynamic> j) => Aprobacion(
        id: (j['id'] ?? '') as String,
        tool: (j['tool'] ?? '') as String,
        motivo: (j['motivo'] ?? '') as String,
        paso: (j['paso'] as num?)?.toInt() ?? 0,
        runId: (j['run_id'] ?? '') as String,
        proyecto: (j['proyecto'] ?? '') as String,
        creado: (j['creado'] ?? '') as String,
        token: (j['token'] ?? '') as String,
      );
}

/// El estado de la autonomía: el modo, qué proyectos puede tocar, qué espera.
class Autonomia {
  const Autonomia({
    this.modo = 'permiso',
    this.modos = const ['solo', 'permiso', 'pleno'],
    this.escritura = const {},
    this.pendientes = const [],
  });

  final String modo;
  final List<String> modos;

  /// alias -> permiso. Lo que Aegis puede escribir **sin preguntar**.
  final Map<String, String> escritura;
  final List<Aprobacion> pendientes;

  factory Autonomia.fromJson(Map<String, dynamic> j) => Autonomia(
        modo: (j['modo'] ?? 'permiso') as String,
        modos: ((j['modos'] as List?) ?? const []).cast<String>(),
        escritura: ((j['escritura'] as Map?) ?? const {}).cast<String, String>(),
        pendientes: ((j['pendientes'] as List?) ?? const [])
            .whereType<Map<String, dynamic>>()
            .map(Aprobacion.fromJson)
            .toList(),
      );

  /// Qué dice el modo, en una frase. El nombre solo (`solo`, `permiso`) no lo
  /// explica nadie; estas dos líneas sí.
  String get explicacion => switch (modo) {
        'solo' => 'No escribo en nada. Solo puedo leer y comprobar.',
        'pleno' => 'Trabajo solo en los proyectos marcados. Lo de fuera te lo pregunto.',
        _ => 'Trabajo solo en los proyectos que marques. El resto, solo lectura.',
      };

  /// Si Aegis puede escribir en ese proyecto sin preguntar.
  ///
  /// Vive aquí y no en las pantallas porque hay dos preguntas con la misma
  /// respuesta que se pueden desincronizar: si este proyecto está marcado, y si
  /// por tanto a un run hay que ponerle la puerta de verificación. La segunda es
  /// la que se olvidó: el móvil mandaba `verificar: false` fijo, y desde el
  /// teléfono ninguna escritura pasaba por el verificador aunque el proyecto
  /// estuviera marcado. La ruta de `curl` sí lo hacía, así que el mismo encargo se
  /// verificaba o no según desde dónde saliera.
  ///
  /// Sin proyecto no hay nada que verificar, así que `''` y un alias raro
  /// devuelven `false` los dos: sin destino no hay contra qué comprobar.
  bool escribible(String alias) =>
      alias.isNotEmpty && escritura.containsKey(alias);
}

/// Una nota tuya.
class Nota {
  const Nota({
    required this.id,
    this.titulo = '',
    this.cuerpo = '',
    this.proyecto = '',
    this.etiquetas = const [],
    this.creado = '',
    this.actualizado = '',
  });

  final String id;
  final String titulo;
  final String cuerpo;
  final String proyecto;
  final List<String> etiquetas;
  final String creado;
  final String actualizado;

  factory Nota.fromJson(Map<String, dynamic> j) => Nota(
        id: (j['id'] ?? '') as String,
        titulo: (j['titulo'] ?? '') as String,
        cuerpo: (j['cuerpo'] ?? '') as String,
        proyecto: (j['proyecto'] ?? '') as String,
        etiquetas: ((j['etiquetas'] as List?) ?? const []).cast<String>(),
        creado: (j['creado'] ?? '') as String,
        actualizado: (j['actualizado'] ?? '') as String,
      );
}

/// Una tarea. [para] es la fecha acordada; vacía significa "cuando pueda", y
/// eso no vence nunca.
class Tarea {
  const Tarea({
    required this.id,
    required this.titulo,
    this.notas = '',
    this.proyecto = '',
    this.para = '',
    this.creada = '',
    this.hecha = '',
    this.estado = 'pendiente',
  });

  final String id;
  final String titulo;
  final String notas;
  final String proyecto;
  final String para;
  final String creada;
  final String hecha;
  final String estado;

  factory Tarea.fromJson(Map<String, dynamic> j) => Tarea(
        id: (j['id'] ?? '') as String,
        titulo: (j['titulo'] ?? '') as String,
        notas: (j['notas'] ?? '') as String,
        proyecto: (j['proyecto'] ?? '') as String,
        para: (j['para'] ?? '') as String,
        creada: (j['creada'] ?? '') as String,
        hecha: (j['hecha'] ?? '') as String,
        estado: (j['estado'] ?? 'pendiente') as String,
      );

  bool get esPendiente => estado == 'pendiente' || estado == 'aplazada';

  /// ¿Venció ya? Solo si tiene fecha: sin fecha es "cuando pueda".
  bool get vencida {
    if (para.isEmpty || !esPendiente) return false;
    final limite = DateTime.now().add(const Duration(days: 1));
    return DateTime.tryParse('${para}T23:59:59')?.isBefore(limite) ?? false;
  }
}

/// Un run del historial, leído del disco del bridge.
class RunHistorial {
  const RunHistorial({
    required this.runId,
    this.proyecto = '',
    this.iniciado = '',
    this.estado = 'desconocido',
    this.pasos = 0,
    this.herramientas = const [],
    this.duracionS = 0,
    this.error = '',
  });

  final String runId;
  final String proyecto;
  final String iniciado;
  final String estado;
  final int pasos;
  final List<String> herramientas;
  final double duracionS;
  final String error;

  factory RunHistorial.fromJson(Map<String, dynamic> j) => RunHistorial(
        runId: (j['run_id'] ?? '') as String,
        proyecto: (j['proyecto'] ?? '') as String,
        iniciado: (j['iniciado'] ?? '') as String,
        estado: (j['estado'] ?? 'desconocido') as String,
        pasos: (j['pasos'] as num?)?.toInt() ?? 0,
        herramientas: ((j['herramientas'] as List?) ?? const []).cast<String>(),
        duracionS: (j['duracion_s'] as num?)?.toDouble() ?? 0,
        error: (j['error'] ?? '') as String,
      );

  bool get fallo => error.isNotEmpty || estado == 'failed' || estado == 'stopped';
}

/// Lo que el bridge dice de Aegis en este instante.
///
/// ## Por qué existe un endpoint para esto
/// Porque «está hablando» no es lo mismo que «tiene una misión abierta», y para
/// lo único que se usa —**pintar el glifo de magenta**— importa la primera. Un
/// run puede estar pensando treinta segundos antes de decir nada, y con esa otra
/// señal el glifo se encendería durante el silencio y estaría mintiendo.
///
/// Y de paso arregla el LED de la cabecera: hasta ahora no tenía nada que
/// consultar, porque `healthProvider` no se sondea. Se leía al arrancar y al
/// tocar el aviso, así que «en línea» era verdad solo en aquel instante y durante
/// los diez segundos siguientes.
class Actividad {
  const Actividad({
    this.hablando = false,
    this.haceS = -1,
    this.que = '',
    this.run = '',
  });

  final bool hablando;

  /// Cuántos segundos desde la última frase. Negativo si nunca ha hablado.
  final double haceS;

  /// De dónde salió: `hermes` o `autopilot`.
  final String que;
  final String run;

  factory Actividad.fromJson(Map<String, dynamic> d) => Actividad(
        hablando: d['hablando'] == true,
        haceS: (d['hace_s'] as num?)?.toDouble() ?? -1,
        que: d['que']?.toString() ?? '',
        run: d['run']?.toString() ?? '',
      );
}

/// La ficha de un proyecto tal como está escrita, para poder corregirla.
class FichaTexto {
  const FichaTexto({
    required this.alias,
    this.texto = '',
    this.kind = '',
    this.estado = 'sin_ficha',
    this.faltan = const [],
    this.secciones = const {},
    this.escritas = const [],
  });

  final String alias;

  /// El fichero completo, frontmatter incluido.
  ///
  /// Se manda entero a propósito: reconstruirlo desde secciones es donde el
  /// modelo se come los `---` y la ficha acaba sin tipo. Quien edita es una
  /// persona, y edita el documento, no un resumen de él.
  final String texto;
  final String kind;
  final String estado;
  final List<String> faltan;

  /// El mapa de secciones ya parseado **por el bridge**.
  ///
  /// Existe para que el formulario pueda prellenar los campos sin parsear
  /// markdown en Dart: `fichas._escrito` tiene reglas que no son triviales
  /// (comentarios multilínea, `###` que no rellena el `##`, marcadores de
  /// «pendiente») y duplicarlas aquí es la forma fiable de que las dos copias
  /// digan cosas distintas.
  final Map<String, String> secciones;

  /// Las secciones con contenido de verdad. El complemento exacto de `faltan`.
  final List<String> escritas;

  bool get completa => estado == 'completa';

  factory FichaTexto.fromJson(Map<String, dynamic> j) => FichaTexto(
        alias: (j['alias'] ?? '') as String,
        texto: (j['texto'] ?? '') as String,
        kind: (j['kind'] ?? '') as String,
        estado: (j['estado'] ?? 'sin_ficha') as String,
        faltan: ((j['faltan'] as List?) ?? const []).cast<String>(),
        secciones: _mapaDeTexto(j['secciones']),
        escritas: ((j['escritas'] as List?) ?? const []).cast<String>(),
      );
}

/// Un `secciones` del bridge puede llegar con cualquier tipo de valor, y un
/// `cast` fallaría en pantalla si algo viniera raro. Se filtra lo que es texto.
Map<String, String> _mapaDeTexto(Object? crudo) {
  if (crudo is! Map) {
    return const {};
  }
  return {
    for (final e in crudo.entries)
      if (e.value != null) e.key.toString(): e.value.toString(),
  };
}

/// La ficha **comercial** de un proyecto: quién es el cliente y a qué se te
/// compromete. Fuera de git, y por eso va en un fichero aparte.
///
/// ## Por qué no reusa `FichaTexto`
/// Porque no son el mismo contrato y el bridge lo dice con dos endpoints
/// distintos. La pública trae `kind`, `estado` y `faltan` —la puerta necesita
/// esas tres para decirte si puedes trabajar—. La privada trae `existe` y
/// `plantilla`, y no lleva puerta: el modelo de cobro no tiene forma canónica
/// (precio cerrado, por hitos, por horas, a partes, o nada), así que exigir un
/// esquema fijo obligaría a rellenar campos que en un encargo dado no existen.
/// Reusar la clase y dejar los campos vacíos sería peor que tener dos.
class FichaPrivada {
  const FichaPrivada({
    required this.alias,
    this.texto = '',
    this.existe = false,
    this.path = '',
    this.plantilla = '',
    this.secciones = const {},
    this.escritas = const [],
  });

  final String alias;

  /// El fichero entero. Se manda entero por la misma razón que en la pública:
  /// quien lo escribió es una persona y edita el documento.
  final String texto;

  /// False cuando el proyecto no tiene ficha privada todavía.
  ///
  /// No es un error ni un 404: es el estado normal de un proyecto recién dado
  /// de alta, y la app tiene que poder abrir el editor para crearla. Por eso el
  /// endpoint responde 200 con el texto vacío en vez de fallar.
  final bool existe;

  final String path;

  /// Dónde está la plantilla, para poder abrirla si el usuario la destruyó.
  final String plantilla;

  /// El mapa de secciones ya parseado, como en la pública.
  final Map<String, String> secciones;

  /// Las secciones con contenido. Aquí es lo que distingue «existe» de «tiene
  /// datos»: el bridge devuelve la plantilla parseada cuando el fichero no está,
  /// así que `existe: false` con las doce secciones es el estado normal de un
  /// proyecto recién dado de alta.
  final List<String> escritas;

  /// ¿Es una plantilla sin rellenar, o una ficha de verdad?
  ///
  /// La plantilla trae las preguntas y ninguna respuesta. Pintar «Cliente» al
  /// lado de una plantilla sin contestar sería mentir: lo que hay es una lista
  /// de temas.
  ///
  /// Lo decide [escritas], que es el bridge aplicando su propia regla de
  /// «escrito». Antes se calculaba aquí mirando el texto, y era una segunda
  /// copia de esa regla que un día iba a decir otra cosa.
  bool get sinRellenar => !existe || escritas.isEmpty;

  factory FichaPrivada.fromJson(Map<String, dynamic> j) => FichaPrivada(
        alias: (j['alias'] ?? '') as String,
        texto: (j['texto'] ?? '') as String,
        existe: (j['existe'] ?? false) as bool,
        path: (j['path'] ?? '') as String,
        plantilla: (j['plantilla'] ?? '') as String,
        secciones: _mapaDeTexto(j['secciones']),
        escritas: ((j['escritas'] as List?) ?? const []).cast<String>(),
      );
}

/// Lo que devuelve `POST /proyectos`: qué se creó y qué falta por escribir.
///
/// ## Por qué `faltan` y no solo un estado
/// Un alta nunca deja la ficha completa, porque lo que la completa lo sabe la
/// persona y no el bridge. Devolver los nombres exactos de las secciones
/// pendientes es lo que permite a la app decir «te faltan estas tres» en vez de
/// «se creó», que es un mensaje que no sirve para saber qué hacer después.
class ProyectoAlta {
  const ProyectoAlta({
    required this.alias,
    this.tipo = '',
    this.estado = '',
    this.faltan = const [],
    this.mensaje = '',
  });

  final String alias;

  /// El tipo que quedó declarado. Se lee del disco, no del cuerpo del POST:
  /// la fuente de verdad es la ficha escrita, no lo que se pidió.
  final String tipo;

  final String estado;
  final List<String> faltan;

  /// El texto largo que arma el bridge. Se enseña entero: explica qué se
  /// creó, dónde, y avisa de que sin verificador no habrá permiso de escritura.
  final String mensaje;

  bool get completa => faltan.isEmpty;

  factory ProyectoAlta.fromJson(Map<String, dynamic> j) => ProyectoAlta(
        alias: (j['alias'] ?? '') as String,
        tipo: (j['tipo'] ?? '') as String,
        estado: (j['estado'] ?? '') as String,
        faltan: ((j['faltan'] as List?) ?? const []).cast<String>(),
        mensaje: (j['mensaje'] ?? '') as String,
      );
}

/// Los modelos de cobro que la plantilla privada ofrece como menú.
///
/// ## Por qué es un enum y no un campo de texto
/// Porque los encargos no se cobran todos igual, y un campo libre produce dos
/// fallos a la vez: o dejas «precio cerrado» y no queda claro cuánto, o
/// inventas un número que el cliente nunca dijo. Con opciones excluyentes
/// eliges **una forma de cobrar** y la app decide qué secciones tienen sentido,
/// que es la parte que hace cómodo rellenarlo.
///
/// Ningún valor trae un importe. El precio lo pone la persona, porque Aegis no
/// lo inventa nunca (`fichas/_plantilla-privada.md`) y la app tampoco.
enum ModeloDeCobro {
  precioCerrado('precio cerrado', 'Una cantidad por el entregable completo.'),
  porHitos('por hitos', 'Cuánto se paga al entregar cada parte, y en qué orden.'),
  porHoras('por horas', 'Cuántas horas, a qué tarifa, con qué tope.'),
  aPartes('a partes', 'Cuota fija recurrente más trabajos fuera de ella.'),
  sinCobro('sin cobro', 'Proyecto interno, o cliente que ya paga una cuota.'),
  otro('otro', 'El modelo y sus reglas.');

  const ModeloDeCobro(this.etiqueta, this.ayuda);

  final String etiqueta;
  final String ayuda;

  String get clave => name;

  static ModeloDeCobro? desdeEtiqueta(String e) {
    for (final m in ModeloDeCobro.values) {
      if (m.etiqueta == e) {
        return m;
      }
    }
    return null;
  }
}

/// Las áreas del workspace, con su etiqueta.
///
/// Viven en Dart y no se piden al bridge porque `/proyectos` devuelve el área
/// **derivada** de la ruta de los proyectos ya existentes, no la lista de las
/// válidas para crear uno nuevo. Con tres valores, hardcodearlas sale más barato
/// que un endpoint, y el bridge vuelve a validar la que llegue: si aquí se
/// desincroniza, el alta se rechaza con un 400 que dice las áreas buenas.
const List<({String valor, String etiqueta})> kAreas = [
  (valor: 'apps', etiqueta: 'Apps'),
  (valor: 'web', etiqueta: 'Web'),
  (valor: 'mobile', etiqueta: 'Móvil'),
];

/// Los tipos de proyecto, que son los que deciden qué secciones hay que escribir.
const List<({String valor, String etiqueta})> kTiposProyecto = [
  (valor: 'encargo', etiqueta: 'Encargo'),
  (valor: 'producto', etiqueta: 'Producto'),
  (valor: 'herramienta', etiqueta: 'Herramienta'),
];

/// Qué secciones hay que escribir, por tipo, y cuáles tiene la ficha privada.
///
/// ## Por qué la app pregunta en vez de tener la lista dentro
/// Las secciones viven en `fichas.SECCIONES_POR_TIPO` del bridge. Copiarlas a
/// Dart produce un fallo silencioso: el día que el bridge añada una sección, la
/// app seguiría sin preguntarla, la puerta la seguiría exigiendo, y el usuario
/// vería «incompleta» sin ninguna sección que la pueda completar. Un bug que
/// no se puede diagnosticar desde la pantalla.
///
/// Es el mismo criterio que los enfoques: el índice sale del disco.
class PlantillaFichas {
  const PlantillaFichas({
    this.secciones = const {},
    this.tipos = const [],
    this.privada = const [],
    this.aviso = '',
  });

  /// Tipo → secciones ordenadas. El orden es la secuencia en que se rellena.
  final Map<String, List<String>> secciones;
  final List<String> tipos;

  /// Los encabezados de la plantilla privada. **No son obligatorios**: es una
  /// lista de temas, porque el modelo de cobro no tiene forma canónica.
  final List<String> privada;

  /// Si el bridge no pudo leer la plantilla privada. No es un fallo de la
  /// llamada —la privada saldría vacía— pero hay que decirlo, porque una lista
  /// vacía parece un proyecto que no tiene nada que rellenar.
  final String aviso;

  /// Las secciones de un tipo, o vacío si el tipo no existe.
  List<String> de(String tipo) => secciones[tipo] ?? const [];

  factory PlantillaFichas.fromJson(Map<String, dynamic> j) {
    final crudas = (j['secciones'] as Map?) ?? const {};
    return PlantillaFichas(
      secciones: {
        for (final e in crudas.entries)
          e.key.toString():
              ((e.value as List?) ?? const []).map((s) => s.toString()).toList(),
      },
      tipos: ((j['tipos'] as List?) ?? const []).map((t) => t.toString()).toList(),
      privada: ((j['privada'] as List?) ?? const []).map((s) => s.toString()).toList(),
      aviso: (j['aviso'] ?? '') as String,
    );
  }
}
