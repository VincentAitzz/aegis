/// Lo que hay que saber antes de ofrecer una actualización.
///
/// ## Por qué estos datos vienen en **cabeceras** y no en el cuerpo
/// El cuerpo de `GET /apk` son 50 MB de binario. Para saber qué versión hay
/// bastan tres cabeceras, así que consultarlas con un `HEAD` evita bajarse el
/// fichero entero para descubrir que ya tienes esa versión. Con un móvil en datos
/// eso son 50 MB por una respuesta que cabe en tres números.
///
/// Y por eso `consultar` no es un `GET`: descargar para mirar es el error
/// contrario al que se quiere evitar.
library;

/// Lo que el bridge anuncia sobre su APK, y lo que la app tiene instalado.
///
/// ## Por qué esto NO es una actualización todavía
/// Porque ofrecer una actualización es una afirmación: «esto se va a instalar y
/// va a funcionar». El dato de la cabecera solo dice que el binario existe, que
/// pasó la puerta y qué número tiene. Que «pasó la puerta» venga en una
/// cabecera es lo que hace que la app pueda decirlo en voz alta en vez de
/// suponerlo.
class VersionApk {
  const VersionApk({
    required this.versionCode,
    this.versionName = '',
    this.etag = '',
    this.disponible = false,
    this.motivo = '',
    this.puedeInstalar = false,
  });

  /// Lo que hay que guardar del `versionCode`: final y `const`-able, porque son
  /// datos que vienen de una respuesta.
  ///
  /// ## Por qué el permiso NO es un campo
  /// Porque no viene de la respuesta del bridge: lo dice Android, y cambia
  /// mientras la app está abierta (la persona lo concede en Ajustes y vuelve).
  /// Metido aquí, el objeto entero dejaría de ser `const` y habría que
  /// reconstruirlo en cada consulta por un dato que no es del bridge.
  ///
  /// Se pasa a [estado] en su lugar, que es donde se usa.

  /// El `versionCode` del APK que sirve el bridge. `0` si no hay ninguno.
  final int versionCode;

  /// El nombre legible (`1.0.1`). Decorativo: la comparación es por número.
  final String versionName;

  /// Huella del binario. Permite saber si el fichero es **el mismo** que ya
  /// tienes, aunque el número coincida.
  final String etag;

  /// Hay algo más nuevo que lo que hay instalado.
  final bool disponible;

  /// Por qué no hay actualización, cuando [disponible] es falso y no es porque
  /// ya esté al día. Sin esto, un APK que el bridge no tiene aparece igual que
  /// una app al día, y son dos situaciones opuestas.
  final String motivo;

  /// Lo que se le dice a la persona, según el estado y si hay permiso.
  ///
  /// ## Por qué es una frase y no un booleano más un cálculo
  /// Porque en la UI se lee mejor una frase, y porque fija aquí la regla que
  /// importa: **no se ofrece instalar el mismo número**, que es lo que Android
  /// rechazaría.
  String get estado {
    if (versionCode <= 0) return motivo.isEmpty ? 'El bridge no tiene APK que servir.' : motivo;
    if (puedeInstalar) return 'Listo: al instalar te lo confirmará Android.';
    return 'Antes hay que concederle a Aegis el permiso de instalar apps '
        'desconocidas (Ajustes → Apps → Acceso especial).';
  }

  /// Si el APK del bridge es más nuevo que el instalado.
  ///
  /// ## Por qué `<` y no `!=`
  /// Porque con `!=`, bajar de versión —un `pubspec` corregido, un APK antiguo
  /// en el router— mostraría «hay actualización» sobre algo que Android va a
  /// rechazar. Solo cuenta como nuevo lo que es estrictamente mayor.
  bool hayVersionesNuevasQue(int instalado) => versionCode > instalado;

  /// La respuesta del bridge, ya comparada con lo que hay instalado.
  ///
  /// ## Por qué la comparación se hace aquí y no en la pantalla
  /// Porque `disponible` depende de dos cosas —el número del bridge y el de
  /// Android— y si cada pantalla lo calculara por su cuenta habría dos sitios
  /// donde equivocarse y uno se olvidaría. Aquí solo hay una regla, y hay un
  /// test que la vigila.
  factory VersionApk.evaluado({
    required int instalado,
    required bool hayPermiso,
    VersionApk? delBridge,
    String motivo = '',
  }) {
    if (delBridge == null || delBridge.versionCode <= 0) {
      return VersionApk(
        versionCode: 0,
        puedeInstalar: hayPermiso,
        motivo: motivo.isEmpty ? 'El bridge no tiene un APK que servir todavía.' : motivo,
      );
    }
    return VersionApk(
      versionCode: delBridge.versionCode,
      versionName: delBridge.versionName,
      etag: delBridge.etag,
      disponible: delBridge.hayVersionesNuevasQue(instalado),
      puedeInstalar: hayPermiso,
      motivo: motivo,
    );
  }

  /// Si Android permitirá instalar apps desconocidas. Lo dice Android, no el
  /// bridge: [VersionApk.evaluado] lo recibe y lo guarda aquí.
  final bool puedeInstalar;
}