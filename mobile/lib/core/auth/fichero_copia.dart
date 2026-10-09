/// Guardar y leer el fichero de la copia de seguridad.
///
/// ## Por qué está en almacenamiento externo de la app
/// La primera versión lo escribía con `getApplicationDocumentsDirectory()`, que
/// en Android devuelve `/data/user/0/<paquete>/app_flutter/`: **almacenamiento
/// interno**, que el explorador de archivos de Android no ve. La función
/// «exportar copia» producía un fichero que el usuario no podía sacar de
/// ninguna manera sin `adb`.
///
/// Ahora va a `getExternalStorageDirectory()/copias/`, que es
/// `Android/data/<paquete>/files/copias/`. Sigue sin salir del móvil, y
/// además se expone con el `FileProvider` que ya declara el `AndroidManifest`
/// (`<external-files-path name="copias" path="copias/" />`) para que otra app
/// local pueda leerlo.
///
/// ## Por qué no SAF (`ACTION_CREATE_DOCUMENT`)
/// SAF deja elegir el destino, y entre los destinos están Drive, Drive
/// compartido y el correo. La app no manda nada por su cuenta —el fichero no se
/// envía, se guarda donde se ordene— pero **ofrecer la nube** en una app cuyo
/// activo son semillas de autenticación es una concesión que aquí no está
/// concedida. Se pidió full local, y esto es full local.
///
/// La consecuencia, dicha antes de que se encuentre: `Android/data/` **se
/// borra al desinstalar la app**, y desinstalar es justo lo que hace la gente
/// cuando recupera un móvil. Es la misma carta que el formato en papel, que no
/// se pierde al desinstalar, y por eso sigue existiendo como segunda opción.
///
/// ## Por qué importar solo mira aquí
/// Por simetría y por la misma razón: si la importación usara SAF, el usuario
/// podría señalar un fichero de Drive y acabar trayendo la bóveda de una nube
/// sin querer. Importar es **leer de la misma carpeta donde exportar escribe**.
library;

import 'dart:io';

import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';

/// El nombre del fichero, sin ruta.
///
/// ## Por qué está aquí y no en la pantalla
/// Importar tiene que encontrar **exactamente** el fichero que exportar escribió.
/// Si cada uno decide el nombre, un cambio de uno deja al otro leyendo un
/// fichero que ya no existe, y el error es «no hay copia», que es el mismo
/// mensaje que da «no has exportado nunca».
const nombreCopia = 'aegis-claves.json';

/// El nombre con el que **se propone** el fichero al guardar.
///
/// ## Por qué lleva fecha y hora
/// Porque exportar dos veces sin querer **pisa** la copia anterior, y una copia
/// que se sobrescribe sin preguntar no era una copia: era la última, y solo
/// mientras no guardaras otra.
///
/// En local (`nombreCopia`) no lleva fecha porque solo hay una: es el
/// automático que se regenera al exportar y del que no se pierde la cuenta.
/// Fuera del móvil, cada exportación es una decisión y se queda registrada.
String nombreCopiaConFecha([DateTime? ahora]) {
  final t = ahora ?? DateTime.now();
  String dos(int n) => n.toString().padLeft(2, '0');
  return 'aegis-claves-${t.year}${dos(t.month)}${dos(t.day)}'
      '-${dos(t.hour)}${dos(t.minute)}.json';
}

/// La carpeta de las copias, dentro del almacenamiento externo de la app.
///
/// Un subdirectorio propio y no la raíz: el `FileProvider` declara `copias/`, y
/// todo lo que hay fuera no es alcanzable desde fuera de la app.
const _subdir = 'copias';

/// Dónde se guarda la copia. Devuelve `null` si no se puede resolver.
///
/// Devuelve `null` y no lanza porque quien llama tiene que poder decir «no se ha
/// podido guardar» en la pantalla, y eso es un mensaje, no un fallo de la app.
Future<Directory?> _dir() async {
  try {
    final base = await getExternalStorageDirectory();
    if (base == null) return null;
    final dir = Directory('${base.path}/$_subdir');
    if (!await dir.exists()) await dir.create(recursive: true);
    return dir;
  } on FileSystemException {
    return null;
  } on MissingPluginException {
    return null;
  }
}

/// Escribe la copia cifrada y devuelve la ruta, o `null` si no se pudo.
Future<String?> guardarCopia(String contenido) async {
  final dir = await _dir();
  if (dir == null) return null;
  try {
    final fichero = File('${dir.path}/$nombreCopia');
    await fichero.writeAsString(contenido, flush: true);
    return fichero.path;
  } on FileSystemException {
    return null;
  }
}

/// Lee la copia de esa misma carpeta.
///
/// `null` si no hay ninguna o si no se puede leer. No hay selector de destino a
/// propósito: ver la nota de la cabecera.
Future<String?> leerCopia() async {
  final dir = await _dir();
  if (dir == null) return null;
  try {
    final fichero = File('${dir.path}/$nombreCopia');
    if (!await fichero.exists()) return null;
    return await fichero.readAsString();
  } on FileSystemException {
    return null;
  }
}

/// Borra la copia de esa carpeta.
///
/// Existe para que «borrar» sea de verdad borrar: una copia cifrada de tus
/// semillas en la tarjeta de memoria es lo que alguien con el móvil en la mano
/// no quiere tener ahí.
Future<void> borrarCopia() async {
  final dir = await _dir();
  if (dir == null) return;
  try {
    final fichero = File('${dir.path}/$nombreCopia');
    if (await fichero.exists()) await fichero.delete();
  } on FileSystemException {
    // Si no se puede borrar, no se dice nada: la copia ya está cifrada y el
    // mensaje de error sería más ruido que información.
  }
}

/// Las copias que hay en la carpeta, para poder elegir cuál importar.
///
/// Con un solo nombre fijo, guardar por encima de la anterior **pisa** la
/// anterior sin preguntar, y una copia que se sobrescribe sin avisar no era una
/// copia: era la última, y solo mientras no guardaras otra.
Future<List<String>> listarCopias() async {
  final dir = await _dir();
  if (dir == null) return const [];
  try {
    final archivos = dir
        .listSync()
        .whereType<File>()
        .where((f) => f.path.endsWith('.json'))
        .toList()
      ..sort((a, b) => b.path.compareTo(a.path));
    return archivos.map((f) => f.path).toList();
  } on FileSystemException {
    return const [];
  }
}

/// El nombre del `FileProvider` para las copias, y su ruta.
///
/// Tiene que coincidir con lo que declara `res/xml/file_paths.xml`. Si los dos
/// no coinciden, Android lanza `IllegalArgumentException` al abrir el fichero
/// y el mensaje no dice nada de rutas —lo dice de permisos—, que es el peor
/// sitio para buscar un error de configuración.
/// Es `${applicationId}.ficheros`, y `applicationId` es
/// `com.aegis.aegis_console` en el `build.gradle.kts`.
const proveedorCopias = 'com.aegis.aegis_console.ficheros';