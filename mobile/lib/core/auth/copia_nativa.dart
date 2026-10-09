/// Hablar con el selector de archivos de Android.
///
/// ## Por qué esto vive detrás de una interfaz
/// Igual que `InstaladorNativo`: un `MethodChannel` en un widget es un test
/// imposible, porque probarlo necesita un emulador y un diálogo del sistema que
/// hay que tocar. Con [CopiaNativa] detrás, la pantalla prueba la **decisión** —
/// qué se escribe, qué se dice cuando se cancela, cuándo se avisa— con un doble,
/// y el canal queda con una línea por detrás.
///
/// ## Por qué `String?` y no `bool`
/// Porque «se lanzó el selector» no es «se guardó». El desenlace —cancelar,
/// elegir una carpeta sin permiso— vive en un diálogo que controla el sistema.
/// Un `true` sería mentir, y un motivo es lo que permite decir «cancelaste» en
/// vez de «no se pudo guardar»: son dos cosas distintas y la persona que las
/// oye hace cosas distintas.
library;

import 'package:flutter/services.dart';

/// Lo que la parte nativa sabe y esta app no puede deducir.
abstract interface class CopiaNativa {
  /// Pide destino a la persona y escribe [texto].
  ///
  /// `null` si se eligió destino y se escribió, un motivo si no. **Cancelar
  /// devuelve `null`**, igual que guardar bien: cancelar es una decisión y no
  /// es un fallo, así que la app no enseña un error por decidir no hacerlo.
  Future<String?> exportar(String texto, String nombre);

  /// Pide un fichero y devuelve su contenido, o `null` si se canceló.
  Future<String?> importar();
}

/// El canal real.
class CopiaPorCanal implements CopiaNativa {
  CopiaPorCanal({MethodChannel? canal})
      : _canal = canal ?? const MethodChannel(canalNombre);

  /// Tiene que coincidir con `CopiaNativa.CANAL` en Kotlin.
  static const canalNombre = 'aegis/copia';

  final MethodChannel _canal;

  @override
  Future<String?> exportar(String texto, String nombre) =>
      _canal.invokeMethod<String>('exportar', {
        'texto': texto,
        'nombre': nombre,
      });

  @override
  Future<String?> importar() => _canal.invokeMethod<String>('importar');
}