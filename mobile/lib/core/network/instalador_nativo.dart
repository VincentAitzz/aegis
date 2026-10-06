/// Hablar con la parte nativa de la instalación.
///
/// ## Por qué esto vive detrás de una interfaz y no se llama al canal en las
/// pantallas
/// Un `MethodChannel` en un widget es un test imposible: para probarlo hay que
/// tener un emulador encendido. Con [InstaladorNativo] detrás, el diálogo prueba
/// la **decisión** (qué botón, qué texto, cuándo pedir permiso) con un doble, y
/// el canal queda con una sola línea por detrás.
///
/// ## Por qué el canal devuelve `null` o un motivo, y no un `bool`
/// `instalar` devuelve si el intent **pudió lanzarse**, no si la app se
/// instaló. Android controla ese desenlace en un diálogo que esta app no puede
/// observar, así que cualquier `bool` de «instalado» sería una mentira. Un
/// `String?` con el motivo del fallo sí es verdad, y es lo que permite decir
/// «no hay instalador» en vez de «no se pudo instalar», que son dos problemas
/// distintos.
library;

import 'package:flutter/services.dart';

/// Lo que la parte nativa sabe y esta app no puede deducir.
abstract interface class InstaladorNativo {
  /// El `versionCode` de lo que hay instalado ahora mismo.
  Future<int> versionCode();

  /// ¿Está concedido el permiso de «instalar apps desconocidas»?
  Future<bool> puedeInstalar();

  /// Abre Ajustes, en el sitio donde se concede ese permiso.
  Future<void> abrirPermiso();

  /// Pasa un APK al instalador. Devuelve `null` si el intent se lanzó, o el
  /// motivo por el que no.
  Future<String?> instalar(String ruta);

  /// Dónde dejar el APK descargado. Lo decide el nativo para que el directorio
  /// externo y el `FileProvider` no puedan desincronizarse.
  Future<String> destino();
}

/// El canal real.
class InstaladorPorCanal implements InstaladorNativo {
  const InstaladorPorCanal([this.canal = _nombre]);

  final String canal;
  static const String _nombre = 'aegis/instalar';

  @override
  Future<int> versionCode() async {
    final v = await _canal.invokeMethod<int>('versionCode');
    // `0` si el nativo no sabe. No se lanza: una app que no puede leer su
    // versión propia debe poder seguir usando todo lo demás, y la actualización
    // se queda en «no se pudo comprobar» en vez de tumbar el arranque.
    return v ?? 0;
  }

  @override
  Future<bool> puedeInstalar() async =>
      await _canal.invokeMethod<bool>('puedeInstalar') ?? false;

  @override
  Future<void> abrirPermiso() => _canal.invokeMethod<void>('abrirPermiso');

  @override
  Future<String?> instalar(String ruta) =>
      _canal.invokeMethod<String>('instalar', {'ruta': ruta});

  @override
  Future<String> destino() async =>
      await _canal.invokeMethod<String>('destino') ?? '';

  MethodChannel get _canal => MethodChannel(canal);
}

/// El doble de los tests: responde lo que se le dice, sin canal ni emulador.
class InstaladorFalso implements InstaladorNativo {
  InstaladorFalso({
    this.versionCodeValue = 1,
    this.puedeInstalarValue = false,
    this.fallaInstalar = false,
    this.ruta = '/data/apk/aegis-2.apk',
  });

  int versionCodeValue;
  bool puedeInstalarValue;

  /// Para probar el camino de «el sistema no aceptó», que tiene su propio texto.
  bool fallaInstalar;
  String ruta;

  /// Rutas que se le pidieron instalar, en orden. Un test necesita saber **qué**
  /// se instaló, no solo que se llamó.
  final List<String> instaladas = [];

  /// Si se pidió abrir el permiso. Un botón que lo ofrece y no lo abre es un
  /// botón roto, y el test tiene que poder verlo.
  bool permisoAbierto = false;

  @override
  Future<int> versionCode() async => versionCodeValue;

  @override
  Future<bool> puedeInstalar() async => puedeInstalarValue;

  @override
  Future<void> abrirPermiso() async => permisoAbierto = true;

  @override
  Future<String?> instalar(String r) async {
    instaladas.add(r);
    return fallaInstalar ? 'sin_instalador' : null;
  }

  @override
  Future<String> destino() async => ruta;
}