/// El registro de permisos de la app.
///
/// ## Por qué un registro y no una lista en la pantalla
/// Porque una lista escrita en la pantalla se pudre sola: el día que Aegis lea
/// NFC o escuche el micrófono, alguien añade el permiso al manifest, se
/// olvida de la lista, y el asistente deja de pedirlo **sin que nada se entere**.
/// Con un registro, añadir es **una entrada** y la pantalla lo recorre.
///
/// Y hay un test que cruza el registro con el manifest, que es lo que
/// convierte «un registro» en «un registro que no puede quedarse corto».
///
/// ## Por qué `CAMERA` **no** está aquí
/// Porque `mobile_scanner` la pide solo, al abrir la pantalla del escáner, y
/// en ese momento la persona **ya está apuntando a un QR**: tiene el contexto
/// delante.
///
/// Preguntarla al arrancar sería preguntarla sin motivo visible, que es
/// exactamente el fallo que la nota de este repo ya escribió una vez sobre las
/// notificaciones. Y una app que pide la cámara nada más abrir parece una app
/// que vigila.
///
/// ## Por qué `REQUEST_INSTALL_PACKAGES` **no** está aquí
/// Porque Android no tiene diálogo para ese permiso: es «acceso especial» y
/// hay que abrir los Ajustes del sistema. No hay forma de pedirlo en un pase, y
/// disimularlo no cambia nada.
///
/// Se comprueba antes de ofrecer la actualización, y se manda a Ajustes con un
/// motivo. Es lo que ya hace el instalador.
library;

import 'network/permiso_notificaciones.dart';

/// Un permiso que Aegis necesita y que puede pedir con un diálogo.
class PermisoApp {
  const PermisoApp({
    required this.id,
    required this.nombre,
    required this.paraQue,
    required this.concedido,
    required this.pedir,
  });

  /// El nombre del permiso **tal cual está en el manifest de Android**.
  ///
  /// ## Por qué el nombre de Android y no uno nuestro
  /// Porque es lo que se compara con el manifest, y un identificador propio
  /// obligaría a mantener una tabla de traducción que nadie va a mirar. Con el
  /// nombre real, el test que cruza registro y manifest es una igualdad, y una
  /// entrada puede tener además un nombre bonito para enseñarlo.
  ///
  /// Estable. No cambia nunca, aunque el texto o el motivo sí: es lo que se
  /// guarda para saber si ya se preguntó.
  final String id;

  /// Lo que se enseña: «cámara», «avisos».
  final String nombre;

  /// Lo que se explica **antes** del diálogo, que es lo que decide que alguien
  /// lo conceda.
  final String paraQue;

  /// Si ya está concedido, o no hace falta en esta versión de Android.
  final Future<bool> Function() concedido;

  /// Lanza el diálogo del sistema.
  final Future<void> Function() pedir;
}

/// El registro.
///
/// ## Por qué es una lista y no un `const` con más campos
/// Porque `concedido` y `pedir` son funciones, y una función no es un valor
/// constante. Lo que **sí** es constante es la lista de identificadores, que es
/// lo que se guarda en disco para saber qué se ya se preguntó.
const permisosDePrimeraVez = <PermisoApp>[
  PermisoApp(
    id: 'POST_NOTIFICATIONS',
    nombre: 'Avisos',
    paraQue: 'Aegis te avisa cuando hay algo pendiente de decidir, o cuando '
        'una tarea vence. Sin esto no te enteras de nada hasta que abres la '
        'app.',
    concedido: PermisoNotificaciones.concedido,
    pedir: PermisoNotificaciones.pedir,
  ),
];