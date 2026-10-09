/// Pide una misión: dónde, y qué hacer.
///
/// ## Por qué no se elige motor
/// Aquí había un interruptor HERMES / AUTOPILOT, y era lo primero que te
/// cruzabas. La diferencia entre los dos no era de capacidad: **los dos llamaban
/// a las mismas 18 tools** de `mcp_ops.py` — Hermes por MCP, el autopilot
/// llamándolas en proceso. El interruptor no elegía qué se podía hacer, elegía en
/// qué proceso vivía el bucle, y el bucle es lo que decide qué guardarraíl se
/// aplica. Dos motores son **dos sitios donde puede vivir un guardarraíl**, y el
/// que se ejecutaba acababa siendo Hermes, que es el que no los tenía.
///
/// ## Por qué el proyecto va con su color de estado
/// Un proyecto sin ficha sale en rojo porque Aegis **no puede escribir** en él.
/// Saberlo antes de pedir la misión evita la sorpresa de que se niegue tres
/// pasos después, y el color es la forma más rápida de verlo sin leer nada.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth/boveda.dart';
import '../../core/theme/aegis_palette.dart';
import '../../core/widgets/aegis_mark.dart';
import '../../core/widgets/hud_panel.dart';
import '../../core/widgets/status_led.dart';
import '../../data/models/agent_models.dart';
import '../../data/models/asistente_models.dart';
import '../providers/agent_providers.dart';
import '../providers/boveda_providers.dart';
import 'claves_page.dart';

class AhoraPage extends ConsumerStatefulWidget {
  const AhoraPage({super.key});

  @override
  ConsumerState<AhoraPage> createState() => _AhoraPageState();
}

class _AhoraPageState extends ConsumerState<AhoraPage> {
  final _prompt = TextEditingController();
  bool _busy = false;
  String? _error;

  AutopilotRun? _run;
  Timer? _poll;

  @override
  void dispose() {
    _prompt.dispose();
    _poll?.cancel();
    super.dispose();
  }

  void _parar() {
    _poll?.cancel();
    _poll = null;
  }

  /// Autopilot no tiene WS: se consulta hasta que el run termina.
  ///
  /// Cada tool aparece en la traza en cuanto se ejecutó, así que el usuario ve
  /// qué está pasando en vez de mirar un spinner dos minutos.
  Future<void> _seguir(String runId) async {
    final repo = ref.read(agentRepositoryProvider);
    try {
      final run = await repo.autopilotStatus(runId);
      if (!mounted) return;
      setState(() => _run = run);
      if (run.finished) {
        _parar();
        return;
      }
      _poll = Timer(const Duration(seconds: 3), () => _seguir(runId));
    } catch (e) {
      if (!mounted) return;
      _parar();
      setState(() => _error = 'Se perdió el seguimiento del run: $e');
    }
  }

  Future<void> _lanzar({String? token, String? proyectoForzado}) async {
    final prompt = _prompt.text.trim();
    if (prompt.isEmpty) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final proyecto = proyectoForzado ?? ref.read(selectedProjectProvider) ?? '';
      final sinProyecto = proyecto.isEmpty ? null : proyecto;
      final fijado = ref.read(enfoqueFijadoProvider);
      final runId = await ref.read(agentRepositoryProvider).startAutopilot(
            prompt: prompt,
            project: sinProyecto,
            maxSteps: 6,
            // La puerta de verificación no se elige a mano. Antes iba `false`
            // fijo desde aquí, y eso significaba que **desde el móvil ninguna
            // escritura pasaba por el verificador**, ni en un proyecto que la
            // persona había marcado como escribible. La ruta de `curl` sí la
            // tenía. La puerta depende de si el proyecto está marcado, no de
            // qué botón pulsaste.
            verify: _autonomiaEscribible(sinProyecto),
            token: token,
            // Sin nada fijado, Aegis pide su enfoque solo si lo necesita.
            enfoque: fijado.isEmpty ? null : fijado,
          );
      if (!mounted) return;
      setState(() {
        _run = null;
        _error = null;
      });
      _parar();
      await _seguir(runId);
    } catch (e) {
      setState(() => _error = 'No pude lanzar la tarea: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Si Aegis puede escribir en ese proyecto, el run lleva la puerta.
  ///
  /// Sin proyecto no hay nada que verificar: `db_query` y `repo_verify` no
  /// escriben, y una puerta sin proyecto solo añadiría un paso de inferencia por
  /// comprobar lo que ya se sabe.
  bool _autonomiaEscribible(String? proyecto) {
    if (proyecto == null || proyecto.isEmpty) return false;
    final aut = ref.read(autonomiaProvider).value;
    return aut?.escribible(proyecto) ?? false;
  }

  /// Pide que el run en marcha deje de empezar pasos.
  ///
  /// ## Por qué sale en la traza y no en la barra
  /// Parar es una decisión sobre **este** run, no sobre la pantalla: ponerlo
  /// arriba obligaría a decidir antes de saber si hay algo que parar, y el botón
  /// estaría vivo cuando no hay run. Aquí solo existe mientras el run corre.
  Future<void> _pararRun() async {
    final run = _run;
    if (run == null || !run.running) return;
    try {
      await ref.read(agentRepositoryProvider).stopAutopilot(run.runId);
      if (!mounted) return;
      // No se para el sondeo: el run sigue vivo hasta que el bucle acknowledge
      // el corte y devuelva `fin: "parado"`. Dejar de preguntar aquí dejaría la
      // traza congelada en "trabajando" para siempre.
      setState(() => _error = null);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = 'No pude parar el run: $e');
    }
  }

  /// Escribe una instrucción en el run que ya está corriendo.
  Future<void> _dirigir(String texto) async {
    final run = _run;
    if (run == null || !run.running) return;
    try {
      await ref.read(agentRepositoryProvider).steerAutopilot(run.runId, texto);
      if (!mounted) return;
      setState(() => _error = null);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = 'No pude dirigir el run: $e');
    }
  }

  /// Relanza el run con el token de un permiso que ya concediste.
  ///
  /// ## Por qué puede fallar y por qué no es un fallo
  /// El token valida **la llamada**, no el run (A-033): si el modelo vuelve a
  /// pedir la misma tool con otros argumentos, el puente lo dice y vuelve a
  /// preguntar. Eso está bien —un permiso no es un permiso para otra cosa— y por
  /// eso el motivo sale en la traza en vez de tragárselo.
  Future<void> _relanzarConPermiso(Aprobacion a) async {
    final token = a.token;
    if (token.isEmpty) return;
    if (_prompt.text.trim().isEmpty) {
      setState(() => _error =
          'Para relanzar hace falta el encargo: escríbelo arriba y vuelve a '
          'pulsar Relanzar. El permiso ya está concedido y su token te está '
          'esperando.');
      return;
    }
    await _lanzar(token: token, proyectoForzado: a.proyecto);
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 28),
      children: [
        const _Saludo(),
        const SizedBox(height: 10),
        const _EntradaClaves(),
        const SizedBox(height: 16),
        _Aprobaciones(onRelanzar: _relanzarConPermiso),
        const SizedBox(height: 16),
        _SelectorProyecto(
          seleccionado: ref.watch(selectedProjectProvider),
          onChanged: (a) =>
              ref.read(selectedProjectProvider.notifier).select(a),
        ),
        const SizedBox(height: 12),
        const _ComoTrabajar(),
        const SizedBox(height: 12),
        TextField(
          controller: _prompt,
          maxLines: 5,
          minLines: 3,
          textInputAction: TextInputAction.newline,
          decoration: const InputDecoration(
            hintText: '¿Qué quieres que haga?',
          ),
        ),
        if (_error != null) ...[
          const SizedBox(height: 10),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Icon(Icons.error_outline, size: 14, color: AegisPalette.danger),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  _error!,
                  style: const TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 12,
                    color: AegisPalette.danger,
                    height: 1.4,
                  ),
                ),
              ),
            ],
          ),
        ],
        const SizedBox(height: 14),
        SizedBox(
          width: double.infinity,
          child: FilledButton.icon(
            onPressed: _busy ? null : _lanzar,
            icon: _busy
                ? const SizedBox(
                    width: 14,
                    height: 14,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.arrow_forward_rounded, size: 18),
            label: Text(_busy ? 'Trabajando…' : 'Encargar'),
          ),
        ),
        if (_run != null) ...[
          const SizedBox(height: 16),
          _TrazaAutopilot(
            run: _run!,
            onParar: _pararRun,
            onDirigir: _dirigir,
          ),
        ],
      ],
    );
  }
}

/// Fijar un enfoque a mano, o no.
///
/// ## Por qué una línea y no un desplegable con opciones
/// Los enfoques los pide **Aegis**, con `usar_enfoque`, cuando su encargo no es
/// todavía ejecutable. Eso es lo que hace que sean suyos y no un menú que alguien
/// tiene que acertar. Lo único que queda aquí es **corregirlo** cuando se ha
/// equivocado —y para eso basta una línea.
///
/// Por defecto no hay nada fijado y pone «lo decide Aegis». Poner uno de salida
/// haría que Aegis trabajara con instrucciones que nadie ha comprobado que
/// apliquen, que es exactamente el gasto que A-016 midió.
///
/// ## Y por qué el texto de un enfoque **no** viene aquí
/// Son ~2000 caracteres por enfoque, y la app solo necesita saber que existen
/// para poder pintar esta línea. Bajárselos al móvil sería el mismo peaje de
/// prompt por el otro lado.
class _ComoTrabajar extends ConsumerWidget {
  const _ComoTrabajar();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final enfoques = ref.watch(enfoquesProvider);
    final fijado = ref.watch(enfoqueFijadoProvider);

    return enfoques.maybeWhen(
      orElse: () => const SizedBox.shrink(),
      loading: () => const SizedBox.shrink(),
      error: (e, _) => const SizedBox.shrink(),
      data: (lista) {
        if (lista.isEmpty) return const SizedBox.shrink();
        final activo = lista.where((e) => e.nombre == fijado);
        final texto = activo.isEmpty
            ? 'trabajando así: lo decide Aegis'
            : 'trabajando así: ${activo.first.titulo}';
        return InkWell(
          onTap: () => _abrir(context, ref, lista, fijado),
          borderRadius: BorderRadius.circular(4),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 7, horizontal: 2),
            child: Row(
              children: [
                Icon(Icons.tune,
                    size: 13,
                    color: fijado.isEmpty
                        ? AegisPalette.fgFaint
                        : AegisPalette.brand),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    texto,
                    style: TextStyle(
                      fontFamily: AegisPalette.mono,
                      fontSize: 10.5,
                      letterSpacing: 0.6,
                      color: fijado.isEmpty
                          ? AegisPalette.fgFaint
                          : AegisPalette.brand,
                    ),
                  ),
                ),
                const Icon(Icons.expand_more,
                    size: 14, color: AegisPalette.fgFaint),
              ],
            ),
          ),
        );
      },
    );
  }

  Future<void> _abrir(BuildContext context, WidgetRef ref,
      List<Enfoque> lista, String fijado) async {
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: AegisPalette.bg1,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(10)),
      ),
      builder: (ctx) => SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Aegis elige el enfoque según lo que le pidas. Esto solo es para '
                'corregirlo cuando se ha equivocado.',
                style: TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 11,
                    height: 1.5,
                    color: AegisPalette.fgDim),
              ),
              const SizedBox(height: 12),
              ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                selected: fijado.isEmpty,
                selectedTileColor: AegisPalette.bg2,
                onTap: () {
                  ref.read(enfoqueFijadoProvider.notifier).soltar();
                  Navigator.pop(ctx);
                },
                title: const Text('Lo decide Aegis',
                    style: TextStyle(
                        fontFamily: AegisPalette.mono, fontSize: 12.5)),
                subtitle: const Text('lo normal',
                    style: TextStyle(
                        fontFamily: AegisPalette.mono,
                        fontSize: 10,
                        color: AegisPalette.fgFaint)),
              ),
              for (final e in lista)
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  selected: e.nombre == fijado,
                  selectedTileColor: AegisPalette.bg2,
                  onTap: () {
                    ref.read(enfoqueFijadoProvider.notifier).alternar(e.nombre);
                    Navigator.pop(ctx);
                  },
                  title: Text(e.titulo,
                      style: const TextStyle(
                          fontFamily: AegisPalette.mono, fontSize: 12.5)),
                  subtitle: Text(
                    e.cierra == null
                        ? e.resumen
                        : '${e.resumen}\n${e.cierra}',
                    style: TextStyle(
                        fontFamily: AegisPalette.mono,
                        fontSize: 10,
                        height: 1.4,
                        color: e.cierra == null
                            ? AegisPalette.fgFaint
                            : AegisPalette.warn),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Dónde vas a trabajar.
///
/// ## Por qué una fila y no los ocho proyectos a la vista
/// Los chips ocupaban **tres filas** antes del campo de texto —el registro tiene
/// ocho proyectos, no cinco— y el segundo objetivo de la pantalla es que escribas
/// el encargo. Ocho proyectos con su color de ficha eran el dato más caro de la
/// pantalla y el que menos se releía: el color repetido ocho veces no dice más
/// que el del proyecto elegido.
///
/// Ahora sale **uno**: el que está activo, con su LED. Cambiarlo es un toque, y
/// entonces sí tiene sentido verlos todos —con buscador, porque `compra-unida` y
/// `recepcion-persa` no se distinguen a tres letras—.
///
/// ## Por qué el filtro es de escribibles y no de favoritos
/// «Solo escribibles» contesta la pregunta que de verdad se hace al elegir
/// proyecto: dónde va a poder trabajar Aegis. La respuesta viene del permiso que
/// ya se le dio en Ajustes, no de otra marca que mantener al día.
class _SelectorProyecto extends ConsumerWidget {
  const _SelectorProyecto({required this.seleccionado, required this.onChanged});

  final String seleccionado;
  final ValueChanged<String> onChanged;

  static Color _color(ProjectInfo p) {
    if (p.completa) return AegisPalette.ok;
    if (p.parcial) return AegisPalette.warn;
    return AegisPalette.danger;
  }

  static String _globo(ProjectInfo p) {
    if (p.completa) return 'Ficha completa · Aegis puede escribir aquí';
    if (p.sinFicha) return 'SIN FICHA · Aegis no puede escribir aquí';
    return 'Incompleta: faltan ${p.faltan.length} secciones';
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final proyectos = ref.watch(projectsProvider);
    return proyectos.when(
      loading: () => const Text('buscando proyectos…',
          style: TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 11,
              color: AegisPalette.fgFaint)),
      error: (e, _) => Text('no pude leer los proyectos: $e',
          style: const TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 11,
              color: AegisPalette.danger)),
      data: (lista) {
        if (lista.isEmpty) {
          return const Text('No hay proyectos registrados.',
              style: TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 11,
                  color: AegisPalette.warn));
        }
        final actual = lista.firstWhere(
          (p) => p.alias == seleccionado,
          orElse: () => lista.first,
        );
        final color = _color(actual);
        final sinProyecto = seleccionado.isEmpty;
        return InkWell(
          // La clave no es decoracion: ahora hay **dos** iconos de `expand_more`
          // en la pantalla —este y el de la linea «trabajando asi»—, y sin ella no
          // hay forma de decir cual de los dos se quiere pulsar. Un icono que hay
          // que adivinar es un icono que alguien pulsara el equivocado.
          key: const Key('aegis.proyecto'),
          onTap: () => _abrirHoja(context, ref, lista),
          borderRadius: BorderRadius.circular(4),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 2),
            child: Row(
              children: [
                // Sostener el proyecto abierto es fácil —una hoja— y soltarlo
                // es lo que se usa a diario. Por eso el propio control se
                // puede pulsar para dejarlo ir, sin abrir nada.
                if (!sinProyecto)
                  GestureDetector(
                    onTap: () => onChanged(nadaElegido),
                    child: const Padding(
                      padding: EdgeInsets.only(right: 6),
                      child: Icon(Icons.close,
                          size: 13, color: AegisPalette.fgFaint),
                    ),
                  ),
                StatusLed(color: sinProyecto ? AegisPalette.fgFaint : color,
                    size: 6),
                const SizedBox(width: 8),
                // En **columna**, no en fila. En fila el título y el texto largo
                // se pelean por el ancho y el título se parte a mitad de palabra
                // («Sin pr» / «oyecto»), que es el peor sitio posible para leer
                // el dato que decide dónde vas a trabajar.
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        // Sin proyecto se dice **sin proyecto**, y no se enseña
                        // el primero de la lista. Antes ponía `lista.first`
                        // cuando no había nada elegido, así que la app parecía
                        // siempre trabajando en `aegis` y el uso cotidiano
                        // quedaba invisible.
                        sinProyecto ? 'Sin proyecto' : seleccionado,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontFamily: AegisPalette.mono,
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                          color:
                              sinProyecto ? AegisPalette.fgDim : color,
                        ),
                      ),
                      const SizedBox(height: 1),
                      Text(
                        sinProyecto
                            ? 'Aegis también sirve para lo que no es un repo'
                            : _globo(actual),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            fontFamily: AegisPalette.mono,
                            fontSize: 10,
                            color: AegisPalette.fgFaint,
                            height: 1.4),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 6),
                const Icon(Icons.expand_more,
                    size: 16, color: AegisPalette.fgFaint),
              ],
            ),
          ),
        );
      },
    );
  }

  /// Lo que significa «no hay proyecto elegido». Es lo que hace `selectedProjectProvider`
  /// cuando nadie ha elegido, y es el estado **normal**: Aegis sirve para
  /// preguntas, notas y mirar cosas, sin repo de por medio.
  static const String nadaElegido = '';

  Future<void> _abrirHoja(
      BuildContext context, WidgetRef ref, List<ProjectInfo> lista) async {
    final elegido = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: AegisPalette.bg1,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(10)),
      ),
      builder: (ctx) => _HojaProyectos(
        proyectos: lista,
        seleccionado: seleccionado,
      ),
    );
    // `null` es "cerrada sin elegir". Sin esta comprobación, cancelar dejaría el
    // proyecto en `''`, que significa "sin proyecto", y no es lo mismo: un cierre
    // accidental no puede cambiar a dónde va a trabajar el siguiente encargo.
    if (elegido != null) onChanged(elegido);
  }
}

/// La hoja: buscador arriba, filtro de escribibles, y los proyectos.
///
/// Es una hoja y no un diálogo porque en un móvil alto la lista completa de
/// proyectos es más comoda de recorrer deslizando, y porque el buscador necesita el
/// teclado sin tapar el botón de cerrar.
class _HojaProyectos extends ConsumerStatefulWidget {
  const _HojaProyectos({
    required this.proyectos,
    required this.seleccionado,
  });

  final List<ProjectInfo> proyectos;
  final String seleccionado;

  @override
  ConsumerState<_HojaProyectos> createState() => _HojaProyectosState();
}

class _HojaProyectosState extends ConsumerState<_HojaProyectos> {
  final _buscar = TextEditingController();
  bool _soloEscribibles = false;

  @override
  void dispose() {
    _buscar.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // El permiso se lee del provider de autonomía, la única fuente. Guardarlo en
    // un campo sería una segunda copia del mismo dato que se puede desincronizar
    // de la de Ajustes.
    final autonomia = ref.watch(autonomiaProvider).value;
    final q = _buscar.text.trim().toLowerCase();
    // Se busca por alias, área y tipo, no por nombre: `ProjectInfo` no trae
    // nombre, trae lo que el registro declara. Con `compra-unida` y
    // `recepcion-persa` el área es lo que desambigua.
    final visibles = widget.proyectos.where((p) {
      if (_soloEscribibles && !(autonomia?.escribible(p.alias) ?? false)) {
        return false;
      }
      return q.isEmpty ||
          p.alias.toLowerCase().contains(q) ||
          p.area.toLowerCase().contains(q) ||
          p.kind.toLowerCase().contains(q);
    }).toList();

    return SafeArea(
      top: false,
      child: Padding(
        // El teclado tapa la mitad de la hoja; sin este padding el último
        // proyecto de la lista queda justo debajo del botón de enviar del
        // teclado, que es donde no se puede pulsar.
        padding:
            EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SizedBox(height: 10),
            Center(
              child: Container(
                width: 36,
                height: 3,
                decoration: BoxDecoration(
                  color: AegisPalette.line,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            const SizedBox(height: 12),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: TextField(
                controller: _buscar,
                onChanged: (_) => setState(() {}),
                style:
                    const TextStyle(fontFamily: AegisPalette.mono, fontSize: 13),
                decoration: const InputDecoration(
                  isDense: true,
                  hintText: 'Buscar proyecto…',
                  prefixIcon: Icon(Icons.search, size: 17),
                ),
              ),
            ),
            const SizedBox(height: 6),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Row(
                children: [
                  FilterChip(
                    label: const Text('solo escribibles'),
                    selected: _soloEscribibles,
                    onSelected: (v) => setState(() => _soloEscribibles = v),
                    labelStyle: TextStyle(
                      fontFamily: AegisPalette.mono,
                      fontSize: 10,
                      color:
                          _soloEscribibles ? AegisPalette.bg0 : AegisPalette.fgDim,
                    ),
                    selectedColor: AegisPalette.brand,
                    backgroundColor: AegisPalette.bg2,
                    showCheckmark: false,
                  ),
                  const SizedBox(width: 10),
                  Text('${visibles.length} de ${widget.proyectos.length}',
                      style: const TextStyle(
                          fontFamily: AegisPalette.mono,
                          fontSize: 10,
                          color: AegisPalette.fgFaint)),
                ],
              ),
            ),
            const SizedBox(height: 8),
            // «Sin proyecto» va **primero**, y no como un proyecto más. Es el
            // estado normal de un uso cotidiano, y esconderlo al final de una
            // lista de repositorios es lo que hace que Aegis parezca una herramienta
            // que solo sirve para trabajar en repos.
            // Con el filtro de escribibles, «sin proyecto» desaparece: no se
            // puede escribir en nada sin proyecto, así que sería una fila que
            // al pulsarla no cambia nada. Un botón que no hace nada es peor que
            // no tenerlo.
            if (!_soloEscribibles)
              ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                selected: widget.seleccionado.isEmpty,
                selectedTileColor: AegisPalette.bg2,
                onTap: () => Navigator.pop(context, _SelectorProyecto.nadaElegido),
                leading: const StatusLed(color: AegisPalette.fgFaint, size: 7),
                title: const Text('Sin proyecto',
                    style: TextStyle(
                        fontFamily: AegisPalette.mono,
                        fontSize: 12.5,
                        fontWeight: FontWeight.w700)),
                subtitle: const Text(
                    'preguntas, notas, mirar cosas. Aegis no necesita un repo '
                    'para eso.',
                    style: TextStyle(
                        fontFamily: AegisPalette.mono,
                        fontSize: 10,
                        height: 1.4,
                        color: AegisPalette.fgFaint)),
              ),
            Flexible(
              child: visibles.isEmpty
                  ? const Padding(
                      padding: EdgeInsets.fromLTRB(16, 18, 16, 18),
                      child: Text(
                        'Ningún proyecto coincide. Con el filtro de escribibles '
                        'puede que no hayas marcado ninguno todavía: se marcan en '
                        'Proyectos.',
                        style: TextStyle(
                            fontFamily: AegisPalette.mono,
                            fontSize: 11,
                            height: 1.5,
                            color: AegisPalette.warn),
                      ),
                    )
                  : ListView.builder(
                      shrinkWrap: true,
                      padding: const EdgeInsets.only(bottom: 12),
                      itemCount: visibles.length,
                      itemBuilder: (context, i) {
                        final p = visibles[i];
                        final activo = p.alias == widget.seleccionado;
                        final color = _SelectorProyecto._color(p);
                        final marcado = autonomia?.escribible(p.alias) ?? false;
                        return ListTile(
                          dense: true,
                          selected: activo,
                          selectedTileColor: color.withValues(alpha: .12),
                          onTap: () => Navigator.pop(context, p.alias),
                          leading: StatusLed(color: color, size: 7),
                          title: Text(p.alias,
                              style: TextStyle(
                                  fontFamily: AegisPalette.mono,
                                  fontSize: 12.5,
                                  fontWeight:
                                      activo ? FontWeight.w700 : FontWeight.w400,
                                  color: activo ? color : AegisPalette.fg)),
                          subtitle: Text(
                            '${_SelectorProyecto._globo(p)}'
                            '${marcado ? " · marcado para escribir" : ""}',
                            style: const TextStyle(
                                fontFamily: AegisPalette.mono,
                                fontSize: 10,
                                height: 1.4,
                                color: AegisPalette.fgFaint),
                          ),
                        );
                      },
                    ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Traza de un run de autopilot.
///
/// Muestra lo que el bridge **ejecutó**, no lo que el agente cuenta que hizo.
/// Un run sin ninguna tool en la traza se dice explícitamente: es la diferencia
/// entre "terminó" y "hizo algo".
class _TrazaAutopilot extends StatelessWidget {
  const _TrazaAutopilot({
    required this.run,
    required this.onParar,
    required this.onDirigir,
  });

  final AutopilotRun run;

  /// Parar el run y dirigirlo. Los dos solo existen mientras corre: fuera de
  /// entonces no hay nada que parar ni a quién decirle nada.
  final Future<void> Function() onParar;
  final Future<void> Function(String) onDirigir;

  @override
  Widget build(BuildContext context) {
    final ok = run.status != 'failed';
    return HudPanel(
      title: 'TRAZA · ${run.status.toUpperCase()}',
      accent: ok ? AegisPalette.ok : AegisPalette.danger,
      trailing: StatusLed(
        color: ok ? AegisPalette.ok : AegisPalette.danger,
        size: 8,
        pulse: run.running,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            run.executedAnything
                ? '${run.tools.length} herramienta(s) · ${run.steps} paso(s)'
                    '${run.fin != null ? ' · terminó por: ${run.fin}' : ''}'
                : 'Sin herramientas ejecutadas: respondió sin tocar nada.',
            style: TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 11,
              height: 1.5,
              color: run.executedAnything ? AegisPalette.fgDim : AegisPalette.warn,
            ),
          ),
          if (run.error != null) ...[
            const SizedBox(height: 6),
            Text(run.error!,
                style: const TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 11,
                    color: AegisPalette.danger,
                    height: 1.4)),
          ],
          if (run.running) ...[
            const SizedBox(height: 10),
            // El mando va **antes** de la traza, no al final: mientras corre hay
            // que poder parar sin tener que llegar al último paso con el pulgar, y
            // cuando termina desaparece, así que no ocupa nada entonces.
            Row(
              children: [
                Expanded(child: _Direccion(onEnviar: onDirigir)),
                const SizedBox(width: 8),
                OutlinedButton.icon(
                  onPressed: () => onParar(),
                  icon: const Icon(Icons.stop_rounded, size: 16),
                  label: const Text('Parar'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AegisPalette.danger,
                    side: BorderSide(
                        color: AegisPalette.danger.withValues(alpha: .55)),
                    padding: const EdgeInsets.symmetric(
                        horizontal: 12, vertical: 10),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              'Parar termina el paso que ya está corriendo y no empieza otro: '
              'la traza de abajo es exactamente lo que llegó a ejecutarse.',
              style: TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 9.5,
                height: 1.4,
                color: AegisPalette.fgFaint,
              ),
            ),
          ],
          for (final paso in run.trace) ...[
            const SizedBox(height: 8),
            // La narración va **encima** del marcador técnico, no debajo: lo que
            // Aegis dice es lo que se lee, y el nombre de la herramienta es el
            // dato que se comprueba. Al revés, la pantalla se lee como un log.
            if (paso.text != null && paso.text!.trim().isNotEmpty) ...[
              Text(paso.text!,
                  style: const TextStyle(
                      fontFamily: AegisPalette.mono,
                      fontSize: 12,
                      height: 1.5,
                      color: AegisPalette.fg)),
              const SizedBox(height: 3),
            ],
            Text('paso ${paso.step} · ${paso.summary}',
                style: TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 10.5,
                    height: 1.4,
                    color: paso.failed ? AegisPalette.danger : AegisPalette.ok)),
            if (paso.result != null)
              Padding(
                padding: const EdgeInsets.only(left: 10, top: 2),
                child: Text(
                  paso.result!.replaceAll('\n', '  '),
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                      fontFamily: AegisPalette.mono,
                      fontSize: 10,
                      color: AegisPalette.fgFaint,
                      height: 1.4),
                ),
              ),
          ],
          if (run.answer != null && run.answer!.isNotEmpty) ...[
            const SizedBox(height: 12),
            Container(height: 1, color: AegisPalette.line),
            const SizedBox(height: 10),
            Text(run.answer!,
                style: const TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 11.5,
                    color: AegisPalette.fgDim,
                    height: 1.55)),
          ],
          const SizedBox(height: 8),
          Text(
            run.running ? 'sigue trabajando…' : 'run ${run.runId}',
            style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 10,
                color: AegisPalette.fgFaint),
          ),
        ],
      ),
    );
  }
}

/// Escribir una instrucción en un run que ya está corriendo.
///
/// ## Por qué un controller propio
/// Podría haber reutilizado el del encargo, y sería un bug: enviar por aquí
/// **no** lanza un run nuevo, lo dirige. Si compartieran texto, corregir una
/// instrucción a media ejecución te dejaría el encargo del run anterior mezclado
/// en el campo del nuevo, y el botón de arriba volvería a encargar algo que ya
/// no es lo que querías.
class _Direccion extends StatefulWidget {
  const _Direccion({required this.onEnviar});

  final Future<void> Function(String) onEnviar;

  @override
  State<_Direccion> createState() => _DireccionState();
}

class _DireccionState extends State<_Direccion> {
  final _texto = TextEditingController();

  @override
  void dispose() {
    _texto.dispose();
    super.dispose();
  }

  Future<void> _enviar() async {
    final t = _texto.text.trim();
    if (t.isEmpty) return;
    await widget.onEnviar(t);
    if (!mounted) return;
    // Se limpia solo, no al devolver el run: lo que se mandó ya está en el
    // bucle, y dejarlo puesto invitaría a reenviarlo sin querer.
    _texto.clear();
  }

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: _texto,
      minLines: 1,
      maxLines: 2,
      textInputAction: TextInputAction.send,
      onSubmitted: (_) => _enviar(),
      style: const TextStyle(fontFamily: AegisPalette.mono, fontSize: 11.5),
      decoration: InputDecoration(
        isDense: true,
        hintText: 'Corregir en marcha…',
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
        suffixIcon: IconButton(
          icon: const Icon(Icons.send_rounded, size: 15),
          onPressed: _enviar,
          tooltip: 'Aplica en el siguiente paso',
        ),
      ),
    );
  }
}

/// Lo que Aegis dice al despertar.
///
/// ## Por qué sale de datos y no es un texto fijo
/// Un saludo con datos inventados es peor que no tener saludo: dice "ayer miré
/// tres proyectos" y no los miró. Aquí sale de lo que el bridge recuerda y de lo
/// que está esperando tu OK, y **si no hay nada que decir, no dice nada**.
///
/// ## Por qué no lo escribe un modelo
/// Porque sería una frase sobre datos que un 7B puede deformar sin que nadie se
/// entere. Es una frase sobre hechos que ya están en la respuesta del endpoint:
/// componerla es contar.
class _Saludo extends ConsumerWidget {
  const _Saludo();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final aprobaciones = ref.watch(aprobacionesProvider);
    final tareas = ref.watch(tareasProvider);

    final pendiente = switch (aprobaciones) {
      AsyncData(:final value) => value.length,
      _ => 0,
    };
    final vencidas = switch (tareas) {
      AsyncData(:final value) => value.where((t) => t.vencida).length,
      _ => 0,
    };

    final String texto;
    final Color color;
    if (pendiente > 0) {
      texto = 'Tengo $pendiente cosa'
          '${pendiente == 1 ? '' : 's'} que necesito que decidas antes de seguir.';
      color = AegisPalette.warn;
    } else if (vencidas > 0) {
      texto = '$vencidas tarea${vencidas == 1 ? '' : 's'} '
          '${vencidas == 1 ? 'ha' : 'han'} vencido.';
      color = AegisPalette.danger;
    } else {
      // Nada pendiente: se dice lo mínimo y se deja trabajar. Un saludo que
      // siempre dice algo es un saludo que acaba ignorándose.
      texto = 'Listo. Dime qué hago.';
      color = AegisPalette.fgDim;
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 11),
      decoration: BoxDecoration(
        color: AegisPalette.bg1,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: AegisPalette.line),
      ),
      child: Row(
        children: [
          AegisMark(size: 17),
          const SizedBox(width: 11),
          Expanded(
            child: Text(
              texto,
              style: TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 12,
                height: 1.45,
                color: color,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// La entrada a las claves.
///
/// ## Por qué va aquí y no como pestaña
/// La barra de secciones ya tiene seis, y `test/sections_test.dart` falla a
/// propósito por la séptima: con seis pestañas a 180 px cada una las etiquetas
/// se leen; con siete hay que encogerlas, y el propio test avisa de que la
/// solución no es el texto.
///
/// ## Por qué es un botón y no un icono suelto
/// Porque hay un estado que hay que ver desde fuera —«te quedan dos códigos de
/// recuperación»— y para eso hace falta sitio. Con un icono en la barra ese
/// aviso no cabe, y un aviso que no cabe no es un aviso.
///
/// ## Por qué cuenta las cuentas sin abrir la bóveda entera
/// Consulta el provider, que ya está en memoria. Descifrar el Keystore en cada
/// `build` de la pantalla principal sería de las pocas cosas que hacen que la
/// app arranque NotImplemented.
class _EntradaClaves extends ConsumerWidget {
  const _EntradaClaves();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final boveda = ref.watch(bovedaProvider);
    final cuentas = switch (boveda) {
      AsyncData(:final value) => value.cuentas,
      _ => const <Cuenta>[],
    };
    final sinRecuperacion = switch (boveda) {
      AsyncData(:final value) =>
        value.cuentas.where((c) => value.sinGastar(c.id) == 0).length,
      _ => 0,
    };

    return InkWell(
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => const ClavesPage()),
      ),
      borderRadius: BorderRadius.circular(6),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 11),
        decoration: BoxDecoration(
          color: AegisPalette.bg1,
          borderRadius: BorderRadius.circular(6),
          border: Border.all(
            color: sinRecuperacion > 0 ? AegisPalette.warn : AegisPalette.line,
          ),
        ),
        child: Row(
          children: [
            Icon(
              Icons.key_outlined,
              size: 16,
              color: sinRecuperacion > 0 ? AegisPalette.warn : AegisPalette.fgDim,
            ),
            const SizedBox(width: 11),
            Expanded(
              child: Text(
                switch (cuentas.length) {
                  0 => 'Claves de doble factor',
                  final n => '$n clave${n == 1 ? '' : 's'} de doble factor',
                },
                style: const TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 12,
                  color: AegisPalette.fgDim,
                ),
              ),
            ),
            if (sinRecuperacion > 0)
              Text(
                'sin recuperación',
                style: const TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 10,
                  color: AegisPalette.warn,
                ),
              )
            else
              const Icon(Icons.chevron_right, size: 15, color: AegisPalette.fgFaint),
          ],
        ),
      ),
    );
  }
}

/// La bandeja de permisos.
///
/// ## Por qué va aquí y no en Ajustes
/// Es lo único que **bloquea** a Aegis: un run está parado esperando. Una
/// decisión que bloquea el trabajo se pone delante de donde se empieza a
/// trabajar, no en un menú que hay que recordar abrir.
///
/// ## Por qué el motivo va entero
/// «Aprobar sin saber si la app se abre encima es justo lo que hay que
/// evitar». Por eso el texto de Aegis se muestra completo y el botón de denegar
/// **pide un motivo**: ese motivo es lo que Aegis leerá la próxima vez.
class _Aprobaciones extends ConsumerStatefulWidget {
  const _Aprobaciones({required this.onRelanzar});

  /// Relanza un permiso ya concedido. Lo pone la pantalla que tiene el
  /// encargo escrito, porque el relanzado es repetir ese encargo con un token.
  final Future<void> Function(Aprobacion) onRelanzar;

  @override
  ConsumerState<_Aprobaciones> createState() => _AprobacionesState();
}

class _AprobacionesState extends ConsumerState<_Aprobaciones> {
  /// Lo que salió de ejecutar lo aprobado, para que se vea y no se suponga.
  /// Sin esto, el botón dice "hecho" y no hay ni un texto que lo confirme: es
  /// un informe, y los informes llegan tarde y a veces mintiendo.
  String? _ejecutado;
  bool _ejecutando = false;
  bool _ok = false;

  Future<void> _ejecutar(Aprobacion a) async {
    setState(() {
      _ejecutando = true;
      _ejecutado = null;
    });
    try {
      final r = await ref
          .read(agentRepositoryProvider)
          .ejecutarAprobacion(a.id);
      if (!mounted) return;
      setState(() {
        // La ejecución va en segundo plano y el desenlace lo publica **el aviso**
        // (A-069). Aquí solo se dice lo que dijo el bridge al arrancar, y se dice
        // con sus palabras.
        //
        // Antes esta caja pintaba el resultado y el aviso pintaba el suyo, y se
        // desincronizaron dos veces: una dejó una caja **en blanco**, porque leía
        // un `ok` que ya no venía en la respuesta y pintaba un fallo sin motivo
        // detrás. Un `ok` que se supone falso es peor que no pintar nada.
        _ok = r.terminada;
        _ejecutado = r.terminada
            ? (r.ok ? r.resultado : r.error)
            : (r.detalle.isEmpty
                ? 'Aegis lo está haciendo. Te aviso con el aviso del móvil.'
                : r.detalle);
      });
      refrescarAsistente(ref);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _ok = false;
        _ejecutado = 'No pude ejecutarlo: $e';
      });
    } finally {
      if (mounted) setState(() => _ejecutando = false);
    }
  }

  Future<void> _denegar(Aprobacion a) async {
    final motivo = await showDialog<String>(
      context: context,
      builder: (context) => _DialogoMotivo(motivo: a.motivo),
    );
    if (motivo == null) return;
    await ref.read(agentRepositoryProvider).denegarConMotivo(
          a.id,
          motivo.isEmpty ? 'No me has dado un motivo.' : motivo,
        );
    refrescarAsistente(ref);
  }

  @override
  Widget build(BuildContext context) {
    final estado = ref.watch(aprobacionesProvider);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // El resultado va **fuera** de la tarjeta, y a propósito. Al ejecutar,
        // el permiso se gasta y la tarjeta desaparece de la cola: si el texto
        // viviera dentro, se iría con ella. Un botón que ejecuta y borra la
        // prueba de lo que ejecutó es un botón del que no puedes presumir.
        if (_ejecutado != null) ...[
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: (_ok ? AegisPalette.ok : AegisPalette.danger)
                  .withValues(alpha: .10),
              borderRadius: BorderRadius.circular(6),
              border: Border.all(
                  color: (_ok ? AegisPalette.ok : AegisPalette.danger)
                      .withValues(alpha: .6),
                  width: 1.5),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  _ok ? 'EJECUTADO' : 'NO SE HIZO',
                  style: TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 10.5,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 1.4,
                    color: _ok ? AegisPalette.ok : AegisPalette.danger,
                  ),
                ),
                const SizedBox(height: 7),
                Text(
                  _ejecutado!.replaceAll('**', ''),
                  style: const TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 10.5,
                    height: 1.5,
                    color: AegisPalette.fg,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
        ],
        ..._tarjetas(estado),
      ],
    );
  }

  /// Las tarjetas de la cola: las que te preguntan y las que puedes ejecutar.
  ///
  /// Sin fase, no hay nada que decidir y el resultado de lo anterior se queda
  /// solo: es lo último que pasó, no una cola que hay que atender.
  List<Widget> _tarjetas(AsyncValue<List<Aprobacion>> estado) {
    return estado.maybeWhen(
      orElse: () => const [],
      data: (lista) => [
            for (final a in lista)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: AegisPalette.warn.withValues(alpha: .10),
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(
                        color: AegisPalette.warn.withValues(alpha: .6), width: 1.5),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(
                            a.relanzable
                                ? Icons.check_circle_outline
                                : Icons.pan_tool_outlined,
                            size: 15,
                            color: a.relanzable ? AegisPalette.ok : AegisPalette.warn,
                          ),
                          const SizedBox(width: 8),
                          Text(
                            a.relanzable ? 'TE DIJE QUE SÍ' : 'ME HE PARADO',
                            style: TextStyle(
                              fontFamily: AegisPalette.mono,
                              fontSize: 11,
                              fontWeight: FontWeight.w700,
                              letterSpacing: 1.4,
                              color:
                                  a.relanzable ? AegisPalette.ok : AegisPalette.warn,
                            ),
                          ),
                          const Spacer(),
                          Text(
                            'paso ${a.paso}',
                            style: const TextStyle(
                              fontFamily: AegisPalette.mono,
                              fontSize: 10,
                              color: AegisPalette.fgFaint,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 10),
                      Text(
                        // El markdown del puente se quita aquí: en pantalla son
                        // asteriscos sueltos, y sin ellos la frase se entiende
                        // igual.
                        a.motivo.replaceAll('**', ''),
                        style: const TextStyle(
                          fontFamily: AegisPalette.mono,
                          fontSize: 12,
                          height: 1.55,
                          color: AegisPalette.fg,
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        a.relanzable
                            ? 'Concedido. Falta relanzar el run para que ocurra.'
                            : 'No he hecho nada todavía.',
                        style: TextStyle(
                          fontFamily: AegisPalette.mono,
                          fontSize: 10,
                          color: (a.relanzable ? AegisPalette.ok : AegisPalette.warn)
                              .withValues(alpha: .9),
                        ),
                      ),
                      const SizedBox(height: 14),
                      if (a.relanzable) ...[
                        // Lo principal es **ejecutar lo que aprobaste**, no
                        // relanzar: relanzar depende de que el modelo vuelva a
                        // emitir la misma llamada con los mismos argumentos, y
                        // medido casi nunca lo hace. El botón de relanzar queda
                        // al lado para cuando lo que quieres es que el run siga.
                        Row(
                          children: [
                            Expanded(
                              child: FilledButton.icon(
                                onPressed: _ejecutando ? null : () => _ejecutar(a),
                                icon: _ejecutando
                                    ? const SizedBox(
                                        width: 13,
                                        height: 13,
                                        child:
                                            CircularProgressIndicator(strokeWidth: 2),
                                      )
                                    : const Icon(Icons.play_arrow_rounded, size: 17),
                                label: const Text('Ejecutar'),
                                style: FilledButton.styleFrom(
                                    backgroundColor: AegisPalette.ok,
                                    foregroundColor: AegisPalette.bg0),
                              ),
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: OutlinedButton.icon(
                                onPressed: _ejecutando ? null : () => widget.onRelanzar(a),
                                icon: const Icon(Icons.refresh_rounded, size: 15),
                                label: const Text('Relanzar'),
                                style: OutlinedButton.styleFrom(
                                    foregroundColor: AegisPalette.ok,
                                    side: BorderSide(
                                        color: AegisPalette.ok.withValues(alpha: .6))),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        Text(
                          'Ejecutar hace justo lo que aprobaste. Relanzar vuelve a '
                          'lanzar el run, y depende de que Aegis repita la misma '
                          'llamada; si la repite distinta, te vuelve a preguntar.',
                          style: const TextStyle(
                            fontFamily: AegisPalette.mono,
                            fontSize: 9.5,
                            height: 1.45,
                            color: AegisPalette.fgFaint,
                          ),
                        ),
                      ] else
                        Row(
                        children: [
                          Expanded(
                            child: OutlinedButton(
                              onPressed: () => _denegar(a),
                              style: OutlinedButton.styleFrom(
                                foregroundColor: AegisPalette.danger,
                                side: BorderSide(
                                    color: AegisPalette.danger.withValues(alpha: .6)),
                              ),
                              child: const Text('No'),
                            ),
                          ),
                          const SizedBox(width: 8),
                          Expanded(
                            child: FilledButton(
                              onPressed: () async {
                                await ref
                                    .read(agentRepositoryProvider)
                                    .resolverAprobacion(a.id, aprobar: true);
                                refrescarAsistente(ref);
                              },
                              style: FilledButton.styleFrom(
                                  backgroundColor: AegisPalette.ok,
                                  foregroundColor: AegisPalette.bg0),
                              child: const Text('Sí, adelante'),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
          ],
    );
  }
}

/// El diálogo de "¿por qué no?".
///
/// ## Por qué tiene su propio `State`
/// Antes lo construía el método que lo abre, con un `TextEditingController`
/// creado ahí y destruido en cuanto `showDialog` devolvía. El diálogo tarda en
/// desmontarse, y mientras tanto su `TextField` sigue tocando el controller:
/// "A TextEditingController was used after being disposed". El fallo salía en
/// el test y habría salido en el móvil al cerrar el diálogo.
///
/// El dueño del controller es el widget que lo usa, y `dispose` lo hace quien
/// sabe cuándo: en el `State`, cuando el diálogo ya se va.
class _DialogoMotivo extends StatefulWidget {
  const _DialogoMotivo({required this.motivo});

  final String motivo;

  @override
  State<_DialogoMotivo> createState() => _DialogoMotivoState();
}

class _DialogoMotivoState extends State<_DialogoMotivo> {
  final _motivo = TextEditingController();

  @override
  void dispose() {
    _motivo.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: AegisPalette.bg1,
      title: const Text('¿Por qué no?',
          style: TextStyle(
              fontFamily: AegisPalette.display,
              fontSize: 17,
              letterSpacing: 2,
              color: AegisPalette.fg)),
      // Deslizable a propósito: el motivo de Aegis puede ser largo, y una
      // Column suelta en un `AlertDialog` se desborda en cuanto el texto no cabe,
      // que es justo cuando más falta hace leerlo entero.
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              widget.motivo,
              style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 11,
                height: 1.5,
                color: AegisPalette.fgDim,
              ),
            ),
            const SizedBox(height: 14),
            const Text(
              'Lo leo la próxima vez. Sin motivo, denegar es solo un "no" que no '
              'se puede aplicar a la siguiente situación parecida.',
              style: TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 10,
                height: 1.5,
                color: AegisPalette.fgFaint,
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _motivo,
              autofocus: true,
              maxLines: 3,
              decoration: const InputDecoration(hintText: 'Porque…'),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          style: FilledButton.styleFrom(
              backgroundColor: AegisPalette.danger,
              foregroundColor: AegisPalette.bg0),
          onPressed: () => Navigator.pop(context, _motivo.text.trim()),
          child: const Text('Decir que no'),
        ),
      ],
    );
  }
}
