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
import 'presentation/pages/primera_vez.dart';
import 'presentation/providers/agent_providers.dart';
import 'core/permisos.dart';
import 'presentation/providers/primera_vez_providers.dart';
import 'presentation/shell/aegis_shell.dart';

class AegisApp extends ConsumerWidget {
  const AegisApp({super.key, this.yaPreguntados = const {}});

  /// Qué permisos se han preguntado ya, **resuelto antes de pintar**.
  ///
  /// Viene de `main()`, que espera la lectura del disco antes de `runApp`. Por
  /// eso es un `Set` y no un provider: el árbol no depende de nada asíncrono y
  /// no existe un estado en el que «todavía no lo sé» se parezca a «no
  /// toca». La versión con `watch` sobre el provider tenía ese estado, y en un
  /// test —y en cualquier arranque lento— la rama de carga escribía lo mismo
  /// que el éxito: el pase de permisos no aparecía y nadie se enteraba.
  ///
  /// Vacío significa primera vez, que es lo que un test que monta la app tal
  /// cual está viendo.
  final Set<String> yaPreguntados;

  /// Qué se pinta dentro del arranque: la primera vez o de siempre.
  ///
  /// ## Por qué va **dentro** del arranque y no antes
  /// Porque el arranque es lo único que ya está montado y lo primero que se
  /// ve. Una pantalla de permisos **por encima** del arranque escondería el
  /// logo —que es lo que dice «la app está despertando»— detrás de un
  /// formulario, y eso convierte un arranque normal en algo que parece roto.
  ///
  /// Y aquí se decide con qué datos: el banner de «no hay conexión» y el aviso
  /// de «sin puente» **no tienen sentido** en una app que aún no ha preguntado
  /// nada, porque lo que se presenta todavía no es «Aegis funcionando» sino
  /// «Aegis explicándose». Por eso no pasan por el shell.
  ///
  /// El [ref] se pasa como parámetro porque un método de un `ConsumerWidget` no
  /// lo tiene: solo existe dentro de `build`. Guardarlo como campo sería
  /// apuntar a un árbol que ya no está.
  ///
  /// ## Por qué el set **y** el provider
  ///
  /// Porque hacen falta los dos, y quedarse con uno de los dos rompe algo:
  ///
  /// - Solo el set (que era como estaba): el set es un campo del constructor y
  ///   no cambia. Cuando alguien contestaba y el notificador marcaba
  ///   «preguntado», la app **se quedaba en el pase con el permiso ya
  ///   concedido**. Se comprobó en el emulador: `granted=true` y el formulario
  ///   delante. Un test con un `salir` de mentira no lo ve, porque nunca
  ///   ejercita el cableado real.
  /// - Solo el provider: el primer frame depende de una lectura asíncrona, y
  ///   su estado de carga se escribía igual que el éxito — el pase no salía y
  ///   no había fallo visible (esto ya pasó una vez aquí).
  ///
  /// Así que el set es lo que `main()` resolvió **antes** de pintar, y el
  /// provider manda en cuanto tiene valor. Loading no significa «no lo sé»:
  /// significa «usa lo que te pasaron», que sí se sabe.
  Widget _arranque(WidgetRef ref) {
    final ya = switch (ref.watch(preguntadosProvider)) {
      AsyncData(:final value) => value,
      _ => yaPreguntados,
    };
    final faltan = permisosDePrimeraVez.where((p) => !ya.contains(p.id));
    if (faltan.isEmpty) return const AegisShell();
    return PrimeraVezPage(
      faltan: faltan.toList(growable: false),
      saltar: () {
        ref.read(preguntadosProvider.notifier).marcarTodas();
        _refrescarAvisos(ref);
      },
      preguntar: (p) =>
          ref.read(preguntadosProvider.notifier).preguntar(p),
      // Solo cuando hay veredicto: invalidar antes de que el usuario conteste
      // releería el mismo «no» de antes, que es el estado viejo que
      // la franja puesta.
      alResponder: () => _refrescarAvisos(ref),
    );
  }

  /// Vuelve a preguntar al sistema si los avisos están dados.
  ///
  /// Se invalida en vez de escribirse el valor porque el permiso pudo cambiar
  /// fuera de la app —Ajustes— y lo que interesa es la verdad de ahora.
  void _refrescarAvisos(WidgetRef ref) {
    ref.invalidate(permisoNotificacionesProvider);
  }

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
        child: _arranque(ref),
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
