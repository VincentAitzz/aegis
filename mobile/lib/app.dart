/// Raíz de Aegis: tema, arranque y navegación.
///
/// ## Por qué el arranque necesita el estado del bridge
/// `BootScreen` antes anunciaba `handshake ok` y `auth ok` sin haber comprobado
/// nada. Ahora espera a que alguien le diga lo que **sabe de verdad** —el
/// provider de salud— y lo dice en pantalla. Si el puente no contesta, el
/// arranque lo dice. Es A-016 puesto delante de la persona que usa la app.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/theme/aegis_theme.dart';
import 'core/widgets/boot_screen.dart';
import 'data/models/agent_models.dart';
import 'presentation/providers/agent_providers.dart';
import 'presentation/shell/aegis_shell.dart';

class AegisApp extends ConsumerWidget {
  const AegisApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final salud = ref.watch(healthProvider);
    // El arranque y la cabecera pintan el **mismo** glifo. Si cada uno sacara su
    // color por su cuenta, un día uno se contradicen y no hay forma de saber
    // cuál mintió.
    final glifo = estadoDelGlifo(
      ref.watch(actividadProvider),
      puente: salud.when(data: (h) => h.ok, loading: () => true, error: (_, _) => false),
    );

    return MaterialApp(
      title: 'Aegis',
      debugShowCheckedModeBanner: false,
      theme: AegisTheme.dark(),
      themeMode: ThemeMode.dark,
      home: BootScreen(
        saludo: _saludo(salud),
        lineas: _lineas(salud),
        estado: glifo,
        child: const AegisShell(),
      ),
    );
  }

  /// La primera línea: qué está pasando, no qué debería pasar.
  static String _saludo(AsyncValue<BridgeHealth> salud) => salud.when(
        loading: () => 'Despertando…',
        error: (_, _) => 'Desperté, pero no llego al portátil.',
        data: (h) => h.ok ? 'Desperté. Estoy listo.' : 'Desperté, pero el portátil no contesta.',
      );

  /// Lo que ya sabe de verdad, y en el orden en que lo va sabiendo.
  ///
  /// Solo entra lo comprobado. Un "listo" aquí sería mentira con tipografía
  /// monoespaciada.
  static List<String> _lineas(AsyncValue<BridgeHealth> salud) => salud.when(
        loading: () => const ['preguntando al puente…'],
        error: (e, _) => ['sin puente: $e'],
        data: (h) => [
            h.ok ? 'puente: contesta' : 'puente: no contesta',
            h.hermesOk ? 'hermes: arrancado' : 'hermes: caído',
            h.ollamaOk ? 'ollama: arrancado' : 'ollama: caído',
            if (h.models.isNotEmpty) 'modelos: ${h.models.length}',
          ],
      );
}
