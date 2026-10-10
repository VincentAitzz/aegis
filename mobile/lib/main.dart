/// Aegis Console: cliente móvil del backend multi-agente (a través de la malla).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'presentation/providers/primera_vez_providers.dart';

/// ## Por qué se lee el «ya preguntado» **antes** de `runApp`
///
/// Porque la decisión de si toca el pase de permisos tiene que estar tomada
/// cuando se pinta el primer frame.
///
/// La primera versión montaba la app con un `AsyncNotifier` y observando
/// `preguntadosProvider`, y su rama de carga era «entra sin preguntar». Sobre
/// el papel era prudente —nunca una pantalla en blanco—, pero en la práctica
/// **era indistinguible de que no tocara**: si la lectura no resolvía, el pase
/// no aparecía y nadie se enteraba. Se comprobó montando la app entera en un
/// test: el estado se quedaba en `AsyncLoading` para siempre.
///
/// El problema de fondo es que un `AsyncValue` con una rama de carga que
/// significa «no hagas nada» **escribe el mismo resultado que el éxito**, así
/// que no se puede distinguir «todavía no lo sé» de «lo sé y no toca». Eso no
/// se arregla con más ramas: se arregla no teniendo la duda durante el primer
/// frame.
///
/// Leerlo antes cuesta un instante de pantalla en blanco al arrancar, que es
/// exactamente lo que ya hace el `BootScreen` de Aegis, y compra una decisión
/// única y verificable. Además el contenedor se pasa ya construido, así que
/// las escrituras posteriores van al **mismo** sitio que esta lectura: dos
/// contenedores sería leer de un sitio y escribir en otro.
/// El contenedor ya con la decisión de la primera vez tomada.
///
/// Se resuelve **antes** de `runApp` y se le pasa a `AegisApp` como un `Set`,
/// no se deja un provider a medio cargar. La diferencia no es de estilo: un
/// provider sin resolver tiene un estado en el que «no lo sé» y «no toca» se
/// escriben igual, y en ese estado el pase de permisos no salía y no se veía
/// ningún fallo.
Future<Set<String>> leerYaPreguntados() async {
  final contenedor = ProviderContainer();
  try {
    return await contenedor.read(preguntadosProvider.future);
  } finally {
    contenedor.dispose();
  }
}

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final yaPreguntados = await leerYaPreguntados();
  runApp(ProviderScope(
    child: AegisApp(yaPreguntados: yaPreguntados),
  ));
}