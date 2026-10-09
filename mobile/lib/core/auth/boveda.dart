/// La bóveda: dónde viven las semillas y los códigos de recuperación.
///
/// ## Por qué esto no habla con el bridge
/// Es la decisión más importante del archivo, y está escrita en
/// `docs/decisiones/003`. Resumen: una semilla en el bridge acabaría en la
/// traza del autopilot, en el log de telemetría y en la memoria de Chroma, y
/// las tres son cosas que se pueden leer. Aquí no sale de este proceso.
///
/// ## Por qué `flutter_secure_storage` y no un fichero
/// Porque la clave del Keystore no sale del dispositivo. Un fichero en el
/// directorio de la app se copia con `adb pull` en cuanto el móvil está
/// desbloqueado, sin root y sin que se entere nadie. Con el Keystore, el
/// fichero está ahí pero sin la clave no dice nada.
///
/// ## Por qué los códigos de recuperación van hasheados
/// Porque un código de recuperación existe para el caso en que **ya no tienes
/// el móvil**. Si estuviera en claro en la bóveda, recuperarlo significaría
/// volver a abrir la bóveda — y si has perdido el móvil, no puedes. Guardado
/// hasheado, se comprueba con el mismo hash: tecleas el que tienes escrito y
/// se gast uno. Volver a mostrarlo no es una operación que exista.
library;

import 'dart:convert';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'otpauth.dart';
import 'totp.dart';

/// Una cuenta guardada.
///
/// [id] es estable y es lo que se usa para borrar y para el canje de un código
/// de recuperación: si fuera el emisor, dos cuentas del mismo servicio — dos
/// correos de GitHub, que es lo más normal del mundo— serían la misma y borrar
/// una se llevaría las dos.
class Cuenta {
  const Cuenta({
    required this.id,
    required this.emisor,
    required this.etiqueta,
    required this.semilla,
    required this.algoritmo,
    required this.digitos,
    required this.periodo,
    required this.anadidaEn,
    this.ultimoUso,
  });

  factory Cuenta.desdeQr(CuentaQr qr, DateTime ahora, String id) => Cuenta(
        id: id,
        emisor: qr.emisor,
        etiqueta: qr.etiqueta,
        semilla: qr.semilla,
        algoritmo: qr.algoritmo,
        digitos: qr.digitos,
        periodo: qr.periodo,
        anadidaEn: ahora,
      );

  final String id;
  final String emisor;
  final String etiqueta;

  /// La semilla, en bytes. Esto es el secreto: sale en la copia de seguridad
  /// y en ningún otro sitio.
  final Uint8List semilla;

  final AlgoritmoTotp algoritmo;
  final int digitos;
  final int periodo;
  final DateTime anadidaEn;
  final DateTime? ultimoUso;

  String get titulo => emisor.isEmpty
      ? etiqueta
      : (etiqueta.isEmpty ? emisor : '$emisor: $etiqueta');

  /// El cálculo de [CuentaTotp] de esta cuenta.
  CuentaTotp get totp => CuentaTotp(
        semilla: semilla,
        algoritmo: algoritmo,
        digitos: digitos,
        periodo: periodo,
      );

  String codigo(DateTime instante) => totp.codigo(instante);
  int segundosRestantes(DateTime instante) => totp.segundosRestantes(instante);
  double fraccionRestante(DateTime instante) => totp.fraccionRestante(instante);

  Cuenta copiaCon({DateTime? ultimoUso}) => Cuenta(
        id: id,
        emisor: emisor,
        etiqueta: etiqueta,
        semilla: semilla,
        algoritmo: algoritmo,
        digitos: digitos,
        periodo: periodo,
        anadidaEn: anadidaEn,
        ultimoUso: ultimoUso ?? this.ultimoUso,
      );

  Map<String, dynamic> aJson() => {
        'id': id,
        'emisor': emisor,
        'etiqueta': etiqueta,
        'semilla': base64Encode(semilla),
        'algoritmo': algoritmo.nombre,
        'digitos': digitos,
        'periodo': periodo,
        'anadidaEn': anadidaEn.toUtc().toIso8601String(),
        if (ultimoUso != null) 'ultimoUso': ultimoUso!.toUtc().toIso8601String(),
      };

  /// `null` si el JSON no cuadra, en vez de lanzar.
  ///
  /// El motivo de que sea blando: un registro ilegible no puede impedir abrir
  /// la bóveda. Si una cuenta está corrupta se pierde esa cuenta; si la bóveda
  /// no abre, se pierden todas, y un import de un fichero de hace un año que
  /// alguien editó con un editor de textos no puede dejarte sin cuentas.
  static Cuenta? desdeJson(Map<String, dynamic> j) {
    final semillaB64 = j['semilla'];
    if (semillaB64 is! String) return null;
    final Uint8List semilla;
    try {
      semilla = base64Decode(semillaB64);
    } on FormatException {
      return null;
    }
    if (semilla.isEmpty) return null;

    final anadida = DateTime.tryParse(j['anadidaEn'] as String? ?? '');
    if (anadida == null) return null;

    return Cuenta(
      id: j['id'] as String? ?? '',
      emisor: j['emisor'] as String? ?? '',
      etiqueta: j['etiqueta'] as String? ?? '',
      semilla: semilla,
      // Si el algoritmo guardado no se reconoce, SHA-1: es lo que se usaba
      // cuando se guardó y lo que va a seguir aceptando el servicio.
      algoritmo: AlgoritmoTotp.desdeNombre(j['algoritmo'] as String?) ??
          AlgoritmoTotp.sha1,
      digitos: (j['digitos'] as num?)?.toInt() ?? 6,
      periodo: (j['periodo'] as num?)?.toInt() ?? 30,
      anadidaEn: anadida,
      ultimoUso: DateTime.tryParse(j['ultimoUso'] as String? ?? ''),
    );
  }
}

/// Un código de recuperación guardado, **hasheado**.
///
/// [hash] es SHA-256 del código normalizado. [usado] es una marca, no un
/// borrado: si se borrara el hash, el contador de «cuántos te quedan» no
/// podría sabía y el registro se llenaría de huecos.
class CodigoRecuperacion {
  const CodigoRecuperacion({required this.hash, required this.usado});

  final String hash;
  final bool usado;

  CodigoRecuperacion copia({bool? usado}) =>
      CodigoRecuperacion(hash: hash, usado: usado ?? this.usado);

  Map<String, dynamic> aJson() => {'hash': hash, 'usado': usado};

  static CodigoRecuperacion? desdeJson(Map<String, dynamic> j) {
    final h = j['hash'];
    if (h is! String || h.isEmpty) return null;
    return CodigoRecuperacion(hash: h, usado: j['usado'] == true);
  }
}

/// Cuántos códigos de recuperación genera cada cuenta.
///
/// Diez es lo que usa GitHub y Google. Menos de cinco es insuficiente — con dos
/// te quedas sin ellos—, y más de quince es un papel que nadie va a guardar.
const _codigosPorCuenta = 10;

/// Formato del código de recuperación.
///
/// `X4K9-2NPQ-7RTZ`: tres grupos de cuatro de un alfabeto **sin** caracteres
/// que se parezcan. Fuera `0`, `O`, `1`, `I` y `L`, que son las cinco
/// confusiones que hacen que alguien teclee un código que no es el suyo y
/// descubra que no le funciona. El guion va porque son 12 caracteres y sin él
/// hay que contar.
const _alfabetoCodigo = '23456789ABCDEFGHJKMNPQRSTUVWXYZ';

/// Normaliza lo que teclea la gente antes de hashearlo.
///
/// Sin esto, un código tecleado en minúsculas o sin guiones no casaría con su
/// hash y el usuario vería «ese código no vale» siendo correcto. **Un código de
/// recuperación que falla por una mayúscula es peor que uno que no existe**,
/// porque hace desconfar de los que sí valen.
String normalizarCodigo(String tecleado) => tecleado
    .toUpperCase()
    .replaceAll(RegExp(r'[^0-9A-Z]'), '')
    .trim();

/// El hash con el que se guarda un código.
///
/// SHA-256 del normalizado. **No** lleva sal por código: el espacio es de 12
/// caracteres de un alfabeto de 31, unos 59 bits, y un hash salado obliga a
/// mantener la sal en el registro para poder comprobarlo. Con sal, el registro
/// pesa el doble y no gana nada: atacar un código de recuperación significa
/// probarlos todos contra el hash, y eso no se acelera con la sal.
String hashearCodigo(String codigo) =>
    sha256.convert(utf8.encode(normalizarCodigo(codigo))).toString();

/// Genera [n] códigos de recuperación en claro, para enseñar una vez.
///
/// Van **sin hashear**: esta es la única vez que existen en claro. La pantalla
/// que los enseña es la única que los tiene.
List<String> generarCodigos({int n = _codigosPorCuenta, Random? aleatorio}) {
  final r = aleatorio ?? Random.secure();
  return List<String>.generate(
    n,
    (_) => List<String>.generate(
      3,
      (_) => List<String>.generate(
        4,
        // `Random.secure` por defecto: con `Random()` un `seed` de
        // millisecondsSinceEpoch hace la secuencia predecible, y un código de
        // recuperación predecible no es un código de recuperación.
        (_) => _alfabetoCodigo[r.nextInt(_alfabetoCodigo.length)],
      ).join(),
    ).join('-'),
  );
}

/// La versión del formato de la bóveda.
///
/// ## Por qué vive en el contenido y no en el nombre de la clave
/// La clave del Keystore se llama `aegis.boveda.v1`. Si al cambiar el formato
/// se cambiara **también** el nombre, los datos de la v1 quedarían bajo una
/// clave que ya nadie lee: serían huérfanos, y sin copia fuera no hay
/// recuperación. La versión viaja en el contenido y la clave se queda.
///
/// ## Por qué hay que subirla
/// Cuando cambie algo que no se deduce solo —un campo nuevo sin valor por
/// defecto sensato, un tipo que cambia— hay que subir esto **y** añadir la
/// migración. Subirla sin migración deja copias viejas ilegibles; añadir la
/// migración sin subirla no llega a ejecutarse nunca.
const versionBovedaActual = 1;

/// Un paso de la cadena de migraciones.
class MigracionBoveda {
  const MigracionBoveda({required this.hasta, required this.aplicar});

  /// La versión a la que lleva este paso.
  final int hasta;

  /// Devuelve el mapa en la versión siguiente.
  final Map<String, dynamic> Function(Map<String, dynamic>) aplicar;
}

/// La cadena, de la más antigua a la más nueva.
///
/// Vacía a propósito: la v1 es la primera y no hay nada anterior que migrar.
/// Existe ahora, **probada con una v1 real**, para que cuando llegue la v2 sea
/// añadir una entrada y no escribir un lector desde cero.
const _migraciones = <MigracionBoveda>[];

/// La copia guardada es de una versión que esta app no entiende.
///
/// Distinto de [BovedaCorrupta] a propósito: el fichero está bien, es que es
/// más nuevo que la app. La respuesta es actualizar Aegis, no borrar nada.
class BovedaDeFuturo implements Exception {
  const BovedaDeFuturo();

  @override
  String toString() =>
      'La copia es de una versión más nueva que esta app.';
}

/// La bóveda completa: cuentas y sus códigos de recuperación.
class Boveda {
  Boveda({
    List<Cuenta>? cuentas,
    Map<String, List<CodigoRecuperacion>>? recuperacion,
    this.corrupta = false,
    this.demasiadoNueva = false,
  })  : cuentas = cuentas ?? <Cuenta>[],
        _recuperacion = recuperacion ?? <String, List<CodigoRecuperacion>>{};

  final List<Cuenta> cuentas;
  final Map<String, List<CodigoRecuperacion>> _recuperacion;

  /// Lo que hay guardado en el Keystore existe pero no se puede leer.
  ///
  /// ## Por qué es un valor y no una excepción
  /// Porque es un estado **que hay que seguir enseñando**: si el almacén lanzara
  /// y el `provider` lo tradujera a error, el error vive en un `AsyncError` que
  /// se recalcula en cada reconstrucción, y basta con un `build()` que devuelva
  /// la bóveda vacía para que la pantalla vuelva a pintarse como si no tuvieras
  /// nada — que es exactamente el fallo que hace que alguien añada cuentas y
  /// destruya lo que quedaba.
  ///
  /// Con el estado dentro del valor, la pantalla no puede confundir «no tienes
  /// cuentas» con «no se pueden leer», y [escribir] puede negarse a escribir
  /// encima de algo que no ha leído.
  final bool corrupta;

  /// Lo guardado es de una versión **más nueva** que esta app.
  ///
  /// Separate de [corrupta] porque el consejo es el contrario: corrupto dice
  /// «no añadas nada, no vas a poder leer lo que hay», y esto dice «actualiza
  /// Aegis». Confundirlos hace que alguien borre una bóveda que solo necesitaba
  /// una app más al día.
  final bool demasiadoNueva;

  /// `escribir` sobre una bóveda corrupta no toca lo que hay.
  ///
  /// Se pone aquí y no en cada llamador porque un olvido en uno de ellos es
  /// exactamente la forma de perder la bóveda.
  /// `asFuture` y no un `throw` directo, porque la función devuelve un
  /// `Future`: lanzar antes de crearlo deja al que llama con una excepción en
  /// una línea síncrona y a otro con un `Future` en error, según cuándo llegue.
  /// Con `asFuture` los dos caminos son el mismo.
  Future<void> escribirEn(AlmacenBoveda almacen) {
    if (demasiadoNueva) {
      return Future<void>.error(const BovedaDeFuturo());
    }
    if (corrupta) {
      return Future<void>.error(const BovedaCorrupta());
    }
    return almacen.escribir(this);
  }

  bool get vacia => cuentas.isEmpty && !corrupta;

  /// No se puede escribir encima: o no se entiende, o es más nuevo que la app.
  ///
  /// Los dos casos se niegan por la misma razón y con la misma consecuencia —no
  /// perder lo que hay— pero por motivos distintos, y por eso el segundo tiene
  /// su bandera.
  bool get intocable => corrupta || demasiadoNueva;

  /// Los códigos sin gastar de una cuenta. Lo que ve el usuario.
  List<CodigoRecuperacion> recuperacionDe(String id) =>
      _recuperacion[id] ?? const [];

  int sinGastar(String id) =>
      recuperacionDe(id).where((c) => !c.usado).length;

  /// Añade una cuenta y le crea sus códigos de recuperación.
  ///
  /// Devuelve los códigos **en claro**, una única vez. Quien llama los enseña y
  /// los guarda; después solo quedan hashes.
  List<String> anadir(CuentaQr qr, DateTime ahora, {required String id}) {
    final cuenta = Cuenta.desdeQr(qr, ahora, id);
    cuentas.add(cuenta);
    final codigos = generarCodigos();
    _recuperacion[id] =
        codigos.map((c) => CodigoRecuperacion(hash: hashearCodigo(c), usado: false)).toList();
    return codigos;
  }

  /// Canjea un código de recuperación.
  ///
  /// Devuelve el `id` de la cuenta a la que pertenece, o `null` si no vale
  /// para ninguna. Compara **normalizado**, para que en minúsculas o sin
  /// guiones cuente igual.
  String? canjear(String codigo, DateTime ahora) {
    final objetivo = hashearCodigo(codigo);
    for (final entrada in _recuperacion.entries) {
      final lista = entrada.value;
      final i = lista.indexWhere((c) => c.hash == objetivo && !c.usado);
      if (i >= 0) {
        lista[i] = lista[i].copia(usado: true);
        final id = entrada.key;
        final j = cuentas.indexWhere((c) => c.id == id);
        if (j >= 0) cuentas[j] = cuentas[j].copiaCon(ultimoUso: ahora);
        return id;
      }
    }
    return null;
  }

  void marcarUsada(String id, DateTime ahora) {
    final j = cuentas.indexWhere((c) => c.id == id);
    if (j >= 0) cuentas[j] = cuentas[j].copiaCon(ultimoUso: ahora);
  }

  /// Borra una cuenta y sus códigos.
  ///
  /// Se borran los dos porque un código de recuperación sin su cuenta es un
  /// código que no lleva a ningún lado: dejarlo ahí permite canjear algo que ya
  /// no existe, y el usuario vería «correcto» con una cuenta que no está.
  bool borrar(String id) {
    final antes = cuentas.length;
    cuentas.removeWhere((c) => c.id == id);
    _recuperacion.remove(id);
    return cuentas.length < antes;
  }

  /// Sustituye todas las cuentas. Lo usa el import.
  void reemplazarTodo(List<Cuenta> nuevas,
      Map<String, List<CodigoRecuperacion>> recuperacion) {
    cuentas
      ..clear()
      ..addAll(nuevas);
    _recuperacion
      ..clear()
      ..addAll(recuperacion);
  }

  /// Un id nuevo que no choca con ninguno.
  String nuevoId() {
    final r = Random.secure();
    String candidato() {
      final bytes = List<int>.generate(12, (_) => r.nextInt(256));
      return base32Codificar(Uint8List.fromList(bytes)).toLowerCase();
    }
    final usados = cuentas.map((c) => c.id).toSet();
    var id = candidato();
    while (usados.contains(id)) {
      id = candidato();
    }
    return id;
  }

  /// Una copia con contenido nuevo.
  ///
  /// ## Por qué existe
  /// `BovedaController` repone el estado con `AsyncData(await leer())` después de
  /// cada cambio. Riverpod **solo notifica si el estado nuevo es distinto del
  /// anterior**, y dos `AsyncData` que envuelven la misma instancia son iguales.
  /// Con un almacén que relee del disco cada vez, cada lectura es un objeto
  /// nuevo y todo funciona; con uno que devuelve la misma instancia —un `Boveda`
  /// en memoria, una caché, o el `leer()` que alguien escriba mañana— la lista
  /// **no se repinta** y el borrado parece no haber pasado.
  ///
  /// Depender de que el almacén devuelva objetos frescos es un accidente, y esto
  /// lo quita de en medio: la copia es siempre un objeto nuevo, así que la
  /// notificación sale siempre.
  Boveda copia() => Boveda(
        cuentas: [...cuentas],
        recuperacion: _recuperacion.map((k, v) => MapEntry(k, [...v])),
        corrupta: corrupta,
        demasiadoNueva: demasiadoNueva,
      );

  Map<String, dynamic> aJson() => {
        'version': versionBovedaActual,
        'cuentas': cuentas.map((c) => c.aJson()).toList(),
        'recuperacion': _recuperacion.map(
          (k, v) => MapEntry(
              k, v.map((c) => c.aJson()).toList()),
        ),
      };

  /// Lee una bóveda de JSON, **migrándola** si es de una versión anterior.
  ///
  /// Un registro que no cuadra se salta y el resto se carga. Antes de que existiera
  /// esto, una `try` alrededor de todo devolvía una bóveda vacía: importabas
  /// tu copia de seguridad y la app te decía que no tienes cuentas, sin decir
  /// que se ha leído mal. Ahora cada cuenta se lee por separado y solo se pierde la
  /// que está mal.
  ///
  /// ## Por qué la versión se lee, y no se asumía
  /// Porque `version: 1` se escribía y **nunca se leía**. Eso no es un detalle:
  /// el día que el formato cambie, una copia hecha con la versión anterior se
  /// leería con los valores por defecto de cada campo, sin decir nada. Los
  /// silencios son los que hacen que una copia deje de servir justo cuando se
  /// necesita, y peor: sirven mientras la cuenta tiene menos campos y dejan de
  /// servir cuando le añades uno.
  ///
  /// ## Por qué una migración por pasos y no «leer la actual»
  /// Porque cuando la `v2` llegue, tener que escribir el lector de la `v1` y el
  /// de la `v2` desde cero es justo el error que se quiere evitar. Con una
  /// cadena, la `v2` solo tiene que saber pasar de `v1` a `v2`, y todo lo demás
  /// se arrastra.
  static Boveda desdeJson(Map<String, dynamic> j) {
    final version = (j['version'] as num?)?.toInt() ?? 1;
    if (version > versionBovedaActual) {
      // De un futuro que esta app no entiende. Se rechaza entero, con motivo,
      // en vez de leerlo a medias: leer campos que no conoces produce una
      // bóveda que parece buena y no lo es, que es peor que no tenerla.
      throw const BovedaDeFuturo();
    }
    var datos = j;
    // La cadena va de la más antigua a la actual, y cada paso deja el mapa en la
    // versión siguiente.
    for (final m in _migraciones) {
      if (version >= m.hasta) continue;
      datos = m.aplicar(datos);
    }
    return Boveda._desdeVersionActual(datos);
  }

  static Boveda _desdeVersionActual(Map<String, dynamic> j) {
    final cuentas = <Cuenta>[];
    for (final c in (j['cuentas'] as List? ?? const [])) {
      if (c is Map<String, dynamic>) {
        final cuenta = Cuenta.desdeJson(c);
        if (cuenta != null) cuentas.add(cuenta);
      }
    }
    final recuperacion = <String, List<CodigoRecuperacion>>{};
    final r = j['recuperacion'];
    if (r is Map<String, dynamic>) {
      for (final entrada in r.entries) {
        final lista = <CodigoRecuperacion>[];
        for (final c in (entrada.value as List? ?? const [])) {
          if (c is Map<String, dynamic>) {
            final cod = CodigoRecuperacion.desdeJson(c);
            if (cod != null) lista.add(cod);
          }
        }
        recuperacion[entrada.key] = lista;
      }
    }
    return Boveda(cuentas: cuentas, recuperacion: recuperacion);
  }
}

/// Dónde se guarda, y qué pasa si no se puede leer.
abstract class AlmacenBoveda {
  Future<Boveda> leer();
  Future<void> escribir(Boveda b);

  /// Crea una cuenta y devuelve sus códigos en claro, una vez.
  Future<List<String>> anadir(CuentaQr qr);

  Future<String?> canjear(String codigo);

  Future<bool> borrar(String id);

  Future<List<Cuenta>> todas();
}

/// La bóveda sobre el Keystore.
///
/// ## Por qué una sola clave con todo dentro
/// El sobre entero es un JSON en una entrada. Con una entrada por cuenta habría
/// que saber cuántas hay y cuáles son, y **saber cuáles son ya es filtrar
/// información**: el número de cuentas de una persona no es asunto suyo de
/// nadie. Un solo documento no lo enseña.
class BovedaKeystore implements AlmacenBoveda {
  BovedaKeystore({FlutterSecureStorage? storage, DateTime Function()? reloj})
      : _storage = storage ?? const FlutterSecureStorage(),
        _reloj = reloj ?? DateTime.now;

  static const _clave = 'aegis.boveda.v1';

  final FlutterSecureStorage _storage;
  final DateTime Function() _reloj;

  /// Devuelve una bóveda marcada como [BovedaCorrupta] en vez de lanzar.
  ///
  /// ## Por qué no lanza
  /// Porque «el sobre no se puede leer» y «no tienes nada» tienen que ser
  /// estados distintos **para siempre**, no solo hasta la próxima reconstrucción.
  /// Devolver una [Boveda] con `corrupta` lo convierte en un valor, y entonces
  /// ni la pantalla puede confundirlos ni [escribir] puede pasar por encima.
  ///
  /// ## Por qué el `try` envuelve la **lectura**, y no solo el `jsonDecode`
  /// Porque `FlutterSecureStorage` **documenta que todos sus métodos pueden
  /// lanzar [PlatformException]**, y en Android es lo que hace cuando la clave
  /// se invalida: una restauración del dispositivo, un `adb uninstall`, el
  /// Keystore bloqueado, una migración de versión de la librería.
  ///
  /// Y eso no es una casualidad: el `try` que solo cubría el `jsonDecode` dejaba
  /// escapar la excepción **fuera**, el futuro de `build()` se rechazaba, y
  /// (medido) en Riverpod 3 la pantalla se quedaba con el spinner de carga
  /// **para siempre**: ni error ni fallo, solo «cargando». Es el mismo fallo que
  /// ya se cerró para el sobre malformado, abierto por otra puerta — y esta es
  /// la que más probable se abre, porque un JSON roto no pasa nunca y un
  /// Keystore que falla sí.
  ///
  /// El fallo bueno de este `try` es que no distingue: cualquier cosa que
  /// impida leer devuelve el mismo estado, y ese estado **dice lo que hay que
  /// hacer** en la pantalla.
  @override
  Future<Boveda> leer() async {
    String? bruto;
    try {
      bruto = await _storage.read(key: _clave);
    } on PlatformException {
      // El Keystore no contesta. No hay nada que leer y no se puede leer nada:
      // se marca como dañada para que la pantalla lo diga y para que
      // [Boveda.escribirEn] se niegue a pasar por encima.
      return Boveda(corrupta: true);
    } on MissingPluginException {
      // Sin plugin registrado: solo pasa en pruebas o en un arranque raro. Lo
      // mismo desde el punto de vista de quien usa la app: no hay bóveda.
      return Boveda(corrupta: true);
    }
    if (bruto == null || bruto.isEmpty) return Boveda();
    try {
      final j = jsonDecode(bruto);
      if (j is! Map<String, dynamic>) return Boveda(corrupta: true);
      return Boveda.desdeJson(j);
    } on BovedaDeFuturo {
      // El sobre es de una versión más nueva. **No** se marca como corrupto:
      // el fichero está bien, lo que falla es que la app sea vieja. Tratarlo
      // como corrupción haría que la pantalla dijera «no se puede leer» —que
      // invita a borrar— cuando lo cierto es «actualiza Aegis».
      return Boveda(corrupta: true, demasiadoNueva: true);
    } on FormatException {
      // No se sobrescribe: [Boveda.escribirEn] se niega cuando está corrupta, y
      // con eso cualquier cambio posterior —añadir, borrar— deja el sobre como
      // estaba. Perder la bóveda por un `try` mal puesto es el peor fallo
      // posible y el más fácil de evitar.
      return Boveda(corrupta: true);
    }
  }

  @override
  Future<void> escribir(Boveda b) =>
      _storage.write(key: _clave, value: jsonEncode(b.aJson()));

  @override
  Future<List<String>> anadir(CuentaQr qr) async {
    final b = await leer();
    final codigos = b.anadir(qr, _reloj(), id: b.nuevoId());
    await b.escribirEn(this);
    return codigos;
  }

  @override
  Future<String?> canjear(String codigo) async {
    final b = await leer();
    final id = b.canjear(codigo, _reloj());
    if (id != null) await b.escribirEn(this);
    return id;
  }

  @override
  Future<bool> borrar(String id) async {
    final b = await leer();
    final hubo = b.borrar(id);
    if (hubo) await b.escribirEn(this);
    return hubo;
  }

  // -- acceso por clave, para los tests de integración ------------------------
  //
  // Estos cuatro métodos existen para que `integration_test` pueda usar una clave
  // **distinta** de la de la app. Sin ellos, probar el Keystore real desde el
  // emulador pondría una bóveda de pruebas encima de las de quien está probando
  // la app en su teléfono — y lo que hay en la clave de la app son sus semillas.
  //
  // No se han puesto como parámetro opcional del constructor porque entonces la
  // clase de producción tendría una puerta que nadie usa desde la app.

  /// Lo que hay guardado bajo [clave], como JSON crudo.
  Future<String?> leerComoTexto(String clave) => _storage.read(key: clave);

  /// Escribe [contenido] bajo [clave].
  Future<void> escribirComoTexto(String clave, Object contenido) =>
      _storage.write(key: clave, value: jsonEncode(contenido));

  /// Borra la entrada entera bajo [clave].
  Future<void> borrarClave(String clave) => _storage.delete(key: clave);

  @override
  Future<List<Cuenta>> todas() async => (await leer()).cuentas;
}

/// El sobre está corrupto: hay algo en el Keystore que no se puede leer.
///
/// Es una excepción propia y no un `FormatException` porque la respuesta de la
/// app es otra: **no escribir nada y decirlo**, en vez de tratar un fichero
/// ilegible como una bóveda vacía.
class BovedaCorrupta implements Exception {
  const BovedaCorrupta();

  @override
  String toString() => 'La bóveda guardada no se puede leer.';
}