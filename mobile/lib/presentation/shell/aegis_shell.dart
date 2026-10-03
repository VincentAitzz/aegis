/// El contenedor de secciones: barra de abajo, marca arriba, y el puente vivo.
///
/// ## Por qué `IndexedStack` y no un `switch`
/// `IndexedStack` conserva **el estado de todas las secciones**, no solo la
/// visible. Sin eso, escribir media misión y mirar el diagnóstico y volver
/// atrás tira el texto: la sesión de la misión vive en un provider y se
/// recupera, pero el scroll y los campos de texto de cada pantalla no. Una app
/// que pierde lo que acabas de escribir al cambiar de pestaña se siente rota
/// aunque todo esté bien.
///
/// ## Por qué la marca está arriba y no en la barra
/// La barra es para moverse; la marca es para saber dónde estás. Mezclarlas
/// hace que el rótulo desaparezca al desplazarse y obliga a repetir el nombre
/// de la app en cada barra de título.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/aegis_palette.dart';
import '../../core/widgets/aegis_mark.dart';
import '../../core/widgets/hud_overlay.dart';
import '../providers/agent_providers.dart';
import 'aegis_section.dart';

/// El alto de la cabecera, **sin** contar la barra del sistema.
///
/// ## Por qué es una constante y no se lee del sitio donde se dibuja
/// Los dos avisos de abajo son `Positioned`, y tienen que apoyarse *justo*
/// debajo de la cabecera. Si cada uno calculase su `top` por su cuenta habría
/// tres números que se pueden desincronizar; aquí hay uno y una función.
///
/// ## Por qué se suma el inset
/// Antes la cabecera era un `Container` de 52 px pelados dentro de
/// `Scaffold.body`, sin `SafeArea`: en cualquier dispositivo con barra de estado
/// la marca y los primeros píxeles de cada sección salían **debajo** del reloj.
/// Y los avisos clavados a `top: 52` se montaban encima de la cabecera, que es
/// un bug aparte del solape.
const double _marcaAlto = 52.0;

/// Dónde termina la cabecera contando la barra del sistema.
///
/// `MediaQuery.paddingOf` y no `MediaQuery.of`: no reconstruye a quien la
/// llama cuando cambia el inset, que es justo lo que pasa al abrir y cerrar el
/// teclado.
double _finCabecera(BuildContext context) =>
    _marcaAlto + MediaQuery.paddingOf(context).top;

class AegisShell extends ConsumerStatefulWidget {
  const AegisShell({super.key});

  @override
  ConsumerState<AegisShell> createState() => _AegisShellState();
}

class _AegisShellState extends ConsumerState<AegisShell> {
  @override
  Widget build(BuildContext context) {
    final alias = ref.watch(seccionActualProvider);
    final puente = ref.watch(puenteVivoProvider);
    // El glifo habla por sí solo: el estado sale de `/actividad`, no de que
    // alguien se acuerde de mirar si hay un run en marcha.
    final glifo = estadoDelGlifo(ref.watch(actividadProvider), puente: puente);
    final indice = kSecciones.indexWhere((s) => s.alias == alias);
    final i = indice < 0 ? 0 : indice;
    final activa = kSecciones[i];

    return AnnotatedRegion<SystemUiOverlayStyle>(
      // Sin esto, el texto del sistema sale en negro sobre el fondo oscuro y
      // la barra de estado desaparece.
      value: const SystemUiOverlayStyle(
        statusBarColor: Colors.transparent,
        statusBarIconBrightness: Brightness.light,
        statusBarBrightness: Brightness.dark,
      ),
      child: Scaffold(
        backgroundColor: AegisPalette.bg0,
        body: Stack(
          children: [
            Column(
              children: [
                _Marca(bridgeVivo: puente, estado: glifo),
                Expanded(
                  child: IndexedStack(
                    index: i,
                    children: [
                      for (final s in kSecciones)
                        _Seccion(seccion: s, bridgeVivo: puente),
                    ],
                  ),
                ),
              ],
            ),
            const IgnorePointer(child: HudOverlay()),
            if (!puente) const _AvisoSinPuente(),
            const _AvisoSinPermiso(),
          ],
        ),
        bottomNavigationBar: _Barra(
          activa: activa.alias,
          onElegir: (a) => ref.read(seccionActualProvider.notifier).abrir(a),
        ),
      ),
    );
  }
}

/// Una sección, con su puerta puesta si la necesita.
class _Seccion extends StatelessWidget {
  const _Seccion({required this.seccion, required this.bridgeVivo});

  final AegisSection seccion;
  final bool bridgeVivo;

  @override
  Widget build(BuildContext context) {
    if (seccion.requierePuente && !bridgeVivo) {
      return _SinPuente(motivo: seccion.globo);
    }
    return seccion.pantalla(context);
  }
}

/// La cabecera: glifo, nombre, y el LED que dice si hay alguien al otro lado.
class _Marca extends StatelessWidget {
  const _Marca({required this.bridgeVivo, required this.estado});

  final bool bridgeVivo;

  /// Lo que está haciendo Aegis: celeste en reposo, magenta hablando. Se calcula
  /// una vez arriba, en `estadoDelGlifo`, y se pasa. Si lo calculara cada widget,
  /// dos partes de la cabecera podrían discrepar.
  final EstadoAegis estado;

  @override
  Widget build(BuildContext context) {
    // El `SafeArea` va **por fuera** del borde, no dentro del padding: el borde
    // tiene que caer justo bajo el texto de la cabecera, y con el inset
    // mezclado en el `padding` la línea se separaba de la marca.
    return SafeArea(
      bottom: false,
      child: Container(
        // La clave existe para poder medir la cabecera en un test. `_marcaAlto`
        // es un número en un fichero y lo natural es que nadie lo compruebe: si
        // mañana alguien lo cambia a 60, el único síntoma es que el aviso se
        // solapa, y eso solo se ve en el emulador.
        key: const Key('aegis.cabecera'),
        height: _marcaAlto,
        padding: const EdgeInsets.fromLTRB(16, 6, 12, 4),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: AegisPalette.line)),
      ),
      child: Row(
        children: [
          AegisMark(size: 20, vivo: bridgeVivo, estado: estado),
          const SizedBox(width: 9),
          const Text(
            'AEGIS',
            style: TextStyle(
              fontFamily: AegisPalette.display,
              fontSize: 15,
              fontWeight: FontWeight.w700,
              letterSpacing: 4,
              height: 1.1,
              color: AegisPalette.fg,
            ),
          ),
          const Spacer(),
          Text(
            bridgeVivo ? 'en línea' : 'sin puente',
            style: TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 10.5,
              letterSpacing: 1,
              color: bridgeVivo ? AegisPalette.ok : AegisPalette.warn,
            ),
          ),
        ],
      ),
      ),
    );
  }
}

/// La barra. El ícono se pone en `labelSmall` y el texto en 10 px porque con la
/// tipografía de títulos a 14 px tres pestañas no caben en 1080 px de ancho.
class _Barra extends StatelessWidget {
  const _Barra({required this.activa, required this.onElegir});

  final String activa;
  final ValueChanged<String> onElegir;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        border: Border(top: BorderSide(color: AegisPalette.line)),
      ),
      child: SafeArea(
        top: false,
        child: SizedBox(
          height: 60,
          child: Row(
            children: [
              for (final s in kSecciones)
                Expanded(
                  child: _Pestana(
                    seccion: s,
                    activa: s.alias == activa,
                    onTap: () => onElegir(s.alias),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Pestana extends StatelessWidget {
  const _Pestana({
    required this.seccion,
    required this.activa,
    required this.onTap,
  });

  final AegisSection seccion;
  final bool activa;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    // La pestaña activa es **estructura**: hueso, no el color de marca. Si el
    // celeste dijera «estás aquí» y además «estoy vivo», el mismo color estaría
    // diciendo dos cosas.
    final color = activa ? AegisPalette.hueso : AegisPalette.fgFaint;
    return InkWell(
      onTap: onTap,
      child: Semantics(
        selected: activa,
        button: true,
        label: seccion.label,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            // La rayita de arriba marca la activa sin depender del color: con
            // ámbar y gris apagado los dos son legibles, pero el color solo no
            // distingue bien a quien tenga menos contraste del que debería.
            AnimatedContainer(
              duration: const Duration(milliseconds: 180),
              height: 2,
              width: activa ? 20 : 0,
              decoration: BoxDecoration(
                color: AegisPalette.hueso,
                borderRadius: BorderRadius.circular(1),
              ),
            ),
            const SizedBox(height: 6),
            Icon(activa ? seccion.iconActivo : seccion.icon, size: 19, color: color),
            const SizedBox(height: 3),
            Text(
              seccion.label,
              style: TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 10,
                letterSpacing: 0.5,
                color: color,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// La franja de arriba que dice que no hay puente.
///
/// Va superpuesta y **no** sustituye a la sección: saber que no hay puente y
/// ver el motivo a la vez es lo que evita que abras la app y no entiendas por
/// qué está callada. Es también lo único que se puede pulsar: al tocarla
/// fuerza una relectura del estado, que es lo único útil que se puede hacer
/// mientras no hay puente.
class _AvisoSinPuente extends ConsumerWidget {
  const _AvisoSinPuente();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Positioned(
      top: _finCabecera(context),
      left: 0,
      right: 0,
      child: Material(
        color: AegisPalette.warn,
        child: InkWell(
          onTap: () => ref.invalidate(healthProvider),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 7, horizontal: 16),
            child: Row(
              children: [
                const Icon(Icons.link_off, size: 14, color: AegisPalette.bg0),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text(
                    'Sin puente. Toca para reintentar.',
                    style: TextStyle(
                      fontFamily: AegisPalette.mono,
                      fontSize: 11,
                      color: AegisPalette.bg0,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Cuando hay algo esperando tu OK pero el sistema no deja avisarte.
///
/// ## Por qué sale solo y no al abrir la app
/// El permiso de notificaciones es el caso raro de la app: sin él, Aegis
/// puede quedarse esperando una decisión que solo tú puedes tomar, y no te
/// enteras. Un aviso que aparece **justo cuando hay algo pendiente** y se
/// guarda en cuanto lo concedes es exactamente lo contrario de molestar.
///
/// ## Por qué se calla en cuanto lo concedes
/// Si no se fuera, quedaría una tira diciendo "no te avisamos" sobre una app que
/// ya te está avisando. Se calla por el permiso, no por un flag: lo que decide
/// es el estado real del sistema.
class _AvisoSinPermiso extends ConsumerWidget {
  const _AvisoSinPermiso();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final permiso = ref.watch(permisoNotificacionesProvider);
    final deploys = ref.watch(deploysProvider);
    final pendiente = (permiso.value ?? true) || deploys?.hayPendientes != true;

    if (pendiente) return const SizedBox.shrink();

    return Positioned(
      top: _finCabecera(context),
      left: 0,
      right: 0,
      child: Material(
        color: AegisPalette.brand,
        child: InkWell(
          onTap: () => pedirAvisos(ref),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 7, horizontal: 16),
            child: Row(
              children: [
                const Icon(Icons.notifications_off_outlined,
                    size: 14, color: AegisPalette.bg0),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text(
                    'Aegis espera tu OK y el móvil no le deja avisarte. Toca para '
                    'permitirlo.',
                    style: TextStyle(
                      fontFamily: AegisPalette.mono,
                      fontSize: 11,
                      color: AegisPalette.bg0,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// El cuerpo de una sección que necesita el puente y no lo tiene.
class _SinPuente extends StatelessWidget {
  const _SinPuente({this.motivo});

  final String? motivo;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.link_off, size: 34, color: AegisPalette.fgFaint),
            const SizedBox(height: 14),
            const Text(
              'No llego al puente',
              style: TextStyle(
                fontFamily: AegisPalette.display,
                fontSize: 17,
                fontWeight: FontWeight.w600,
                letterSpacing: 2.5,
                color: AegisPalette.fg,
              ),
            ),
            const SizedBox(height: 10),
            Text(
              motivo ??
                  'Aegis vive en tu portátil. Sin él, no puedo hacer nada todavía.\n'
                      'Levanta el bridge con `bash bridge/run.sh` y vuelve a intentarlo.',
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 12,
                height: 1.6,
                color: AegisPalette.fgDim,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
