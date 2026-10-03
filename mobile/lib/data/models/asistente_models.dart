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
