/// Permiso de notificaciones, del lado de Dart.
library;

import 'package:flutter/services.dart';

/// Puente hacia el permiso `POST_NOTIFICATIONS`.
///
/// ## Por qué esto no es "solo un `requestPermission`"
/// Sin permiso, `NotificationManager.notify()` no publica nada y **no da error**.
/// La app parecía funcionar y los avisos no llegaban. El permiso es de Android
/// 13 en adelante, así que en un móvil viejo todo bien y en el nuevo nada.
///
/// ## Por qué se pregunta desde Dart y no al arrancar
/// El diálogo del sistema sale la primera vez sin contexto. Preguntado en
/// `Ajustes` o cuando hay algo pendiente, con una línea que dice para qué es, se
/// contesta bien. Un "¿permitir notificaciones?" en el primer frame se contesta
/// "no" casi siempre, y entonces no vuelve a haber avisos nunca.
class PermisoNotificaciones {
  PermisoNotificaciones._();

  static const _canal = MethodChannel('aegis/notificaciones');

  /// Ya está concedido, o no hace falta en esta versión de Android.
  static Future<bool> concedido() async {
    try {
      return await _canal.invokeMethod<bool>('estado') ?? false;
    } on MissingPluginException {
      // En pruebas de Dart no hay motor Android detrás. No es un fallo: es que
      // aquí no hay sistema operativo al que preguntarle.
      return true;
    } on PlatformException {
      return false;
    }
  }

  /// Pide el permiso. Devuelve el estado **inmediatamente después** de pedir,
  /// que sigue siendo `false`: el diálogo del sistema es asíncrono.
  ///
  /// Por eso hay que volver a consultar con [concedido] cuando la app vuelve del
  /// diálogo, y no leer el valor de aquí como si fuera la respuesta.
  static Future<void> pedir() async {
    try {
      await _canal.invokeMethod<bool>('pedir');
    } on MissingPluginException {
      return;
    } on PlatformException {
      return;
    }
  }
}
