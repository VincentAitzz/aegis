/// Si esta es la primera vez, y qué se ha preguntado ya.
///
/// ## Por qué se guarda una **lista**, y no un «ya arrancó»
/// Porque un booleano se queda viejo el día que se añade un permiso: la app
/// abriría con la marca puesta, el permiso nuevo **no se preguntaría nunca**,
/// y nadie vería por qué.
///
/// Guardando **qué identificadores** se han preguntado, un permiso nuevo se
/// pregunta en su primera vez aunque la app se hubiera abierto mil veces antes,
/// y uno viejo no se vuelve a preguntar. Es lo que hace que añadir un permiso
/// sea añadir una entrada y nada más.
///
/// ## Por qué en un fichero, y no solo en memoria
/// Porque empezó en memoria, y eso hacía que **el pase se repitiera en cada
/// arranque en frío**: la lista se perdía al morir el proceso, `faltan` volvía a
/// ser todo, y la pantalla tapaba la app para siempre. Los tests de humo lo
/// detectaron, pero el fallo real es de uso —alguien abre Aegis, contesta,
/// cierra, y al volver a abrirlo se lo preguntan otra vez—, y un permiso que se
/// pregunta en cada arranque deja de informar.
///
/// ## Por qué en el directorio interno, y no en el externo de la copia
/// Porque esto no es un documento del usuario: es estado de la instalación. La
/// copia sí va a una carpeta que él elige, y|Download quizá algún día lo borra;
/// esto no debería aterrizar al lado.
///
/// ## Por qué no se guarda el resultado
/// Porque el diálogo del sistema es asíncrono y su respuesta llega después.
/// Guardar el resultado sería guardar un `false` que después nadie corrige, y
/// la siguiente apertura preguntaría otra vez.
library;

import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';

import '../../core/permisos.dart';

const _fichero = 'preguntado.txt';

/// Dónde vive la lista de preguntados.
///
/// ## Por qué es un provider y no una llamada dentro de [_leer]
/// Porque `getApplicationSupportDirectory()` es un canal de plataforma, y en un
/// test no existe: la llamada se tragaba la excepción, `_escribir` devolvía
/// fingiendo que había guardado, y **los tests de persistencia pasaban sin
/// haber escrito nada**. Un test que verde porque el código fallido se tragó su
/// error no está probando lo que dice.
///
/// Con la ruta en un provider, el test la sustituye por una temporal y escribe
/// un fichero de verdad. El resto del código no cambia, y lo que se prueba es la
/// escritura, no la excepción.
///
/// Va con `watch` y no con `read`: en Riverpod 3, `.future` de un
/// `FutureProvider` es un `Refreshable`, y `read` lo devuelve sin desarrollar.
final rutaMarcadorProvider = FutureProvider<String>((ref) async {
  final base = await getApplicationSupportDirectory();
  return '${base.path}/$_fichero';
});

/// Qué se ha preguntado, leído del disco.
///
/// Devuelve vacío si no se puede leer. No es «funciona sin saber»: es que
/// preguntar de más es un annoyance, y no saber nada es no poder avisar de
/// nada. Ante la duda se pregunta.
Future<Set<String>> _leer(String ruta) async {
  try {
    final f = File(ruta);
    if (!await f.exists()) return {};
    return (await f.readAsString())
        .split('\n')
        .map((l) => l.trim())
        .where((l) => l.isNotEmpty)
        .toSet();
  } on FileSystemException {
    return {};
  } on MissingPluginException {
    return {};
  }
}

Future<void> _escribir(String ruta, Set<String> ids) async {
  try {
    final f = File(ruta);
    await f.parent.create(recursive: true);
    // Se escribe **todo** y de golpe. Añadir línea a línea deja un fichero a
    // medias si se muere en medio, y un fichero a medias con «A» y medio «B» es
    // un estado que el código de lectura tendría que adivinar.
    await f.writeAsString((ids.toList()..sort()).join('\n'));
  } on FileSystemException {
    // Sin persistir, el pase se repetirá al próximo arranque. Molesto, no
    // roto: por eso aquí no se lanza.
  } on MissingPluginException {
    // En un test, o en un proceso sin canal: no hay disco, y no hay nada que
    // guardar tampoco.
  }
}

final preguntadosProvider =
    AsyncNotifierProvider<PreguntadosController, Set<String>>(
        PreguntadosController.new);

class PreguntadosController extends AsyncNotifier<Set<String>> {
  @override
  Future<Set<String>> build() async =>
      _leer(await ref.watch(rutaMarcadorProvider.future));

  /// Lo que hay escrito, o vacío.
  ///
  /// Riverpod 3 no tiene `valueOrNull`, y `requireValue` sobre un estado en
  /// carga lanza. El switch dice «si lo tengo, úsalo» sin las dos cosas que no
  /// queremos: mentir con un vacío fingido es lo correcto aquí, porque
  /// esta lista solo decide si se pregunta, y preguntar de más se arregla
  /// solo al siguiente arranque.
  Set<String> get _ya => switch (state) {
        AsyncData(:final value) => value,
        _ => const {},
      };

  /// Anota uno como preguntado y lo persiste.
  ///
  /// Se marca al **preguntar**, no al conceder: la pregunta es lo que agota el
  /// diálogo del sistema de Android, y volver a preguntar algo ya denegado dos
  /// veces no abre nada y parece la app colgada.
  Future<void> preguntar(PermisoApp p) async {
    final ya = {..._ya, p.id};
    state = AsyncData(ya);
    await _escribir(await ref.watch(rutaMarcadorProvider.future), ya);
  }

  /// Se acabó: entra a la app y no vuelve a preguntar.
  ///
  /// Se marcan **todos** los del registro, no solo el visto: quien salta en el
  /// primer paso entra con el resto sin preguntar, y preguntárselo en el
  /// siguiente arranque es volver a interrumpir a alguien que ya dijo que no.
  Future<void> marcarTodas() async {
    final ya = {..._ya, for (final p in permisosDePrimeraVez) p.id};
    state = AsyncData(ya);
    await _escribir(await ref.watch(rutaMarcadorProvider.future), ya);
  }
}