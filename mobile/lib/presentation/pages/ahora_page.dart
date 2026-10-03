/// Pide una misión: qué proyecto, con qué motor, y qué hacer.
///
/// ## Por qué el motor se elige con una frase y no con un interruptor
/// La diferencia entre Hermes y Autopilot no es técnica, es de **qué puede
/// hacer**: uno razona y conversa, el otro ejecuta herramientas de verdad. Ese
/// es el dato que hace falta para elegir, y por eso está escrito encima del
/// campo y no escondido detrás de una etiqueta.
///
/// ## Por qué el proyecto va con su color de estado
/// Un proyecto sin ficha sale en rojo porque Aegis **no puede escribir** en él.
/// Saberlo antes de pedir la misión evita la sorpresa de que se niegue tres
/// pasos después, y el color es la forma más rápida de verlo sin leer nada.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/aegis_palette.dart';
import '../../core/widgets/aegis_mark.dart';
import '../../core/widgets/hud_panel.dart';
import '../../core/widgets/status_led.dart';
import '../../data/models/agent_models.dart';
import '../../data/models/asistente_models.dart';
import '../providers/agent_providers.dart';

class AhoraPage extends ConsumerStatefulWidget {
  const AhoraPage({super.key});

  @override
  ConsumerState<AhoraPage> createState() => _AhoraPageState();
}

class _AhoraPageState extends ConsumerState<AhoraPage> {
  final _prompt = TextEditingController();
  bool _busy = false;
  bool _autopilot = false;
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
      final fase = ref.read(faseElegidaProvider);
      if (_autopilot) {
        final runId = await ref.read(agentRepositoryProvider).startAutopilot(
              prompt: prompt,
              project: sinProyecto,
              maxSteps: 6,
              verify: false,
              token: token,
              fase: fase.isEmpty ? null : fase,
            );
        if (!mounted) return;
        setState(() => _run = null);
        _parar();
        await _seguir(runId);
        return;
      }
      final session = ref.read(taskSessionProvider.notifier);
      await session.createTask(
        agent: kAegisAgent,
        prompt: prompt,
        project: sinProyecto,
      );
      final task = ref.read(taskSessionProvider)?.task;
      if (task != null) {
        ref.read(recentTasksProvider.notifier).add(task.runId);
      }
    } catch (e) {
      setState(() => _error = 'No pude lanzar la tarea: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
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
        const SizedBox(height: 16),
        _Aprobaciones(onRelanzar: _relanzarConPermiso),
        const SizedBox(height: 16),
        _SelectorProyecto(
          seleccionado: ref.watch(selectedProjectProvider),
          onChanged: (a) =>
              ref.read(selectedProjectProvider.notifier).select(a),
        ),
        const SizedBox(height: 14),
        _Motor(
          autopilot: _autopilot,
          onChanged: (v) => setState(() => _autopilot = v),
        ),
        const SizedBox(height: 12),
        const _SelectorFase(),
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
          _TrazaAutopilot(run: _run!),
        ],
      ],
    );
  }
}

/// Aegis tiene un solo agente. Antes había un selector worker/orchestrator, pero
/// los dos acababan en el mismo modelo: era una elección que no elegía nada.
const String kAegisAgent = 'worker';

/// Elige el motor, y dice en una línea para qué sirve cada uno.
///
/// El texto va **debajo** del interruptor y no en un tooltip: en un móvil un
/// tooltip no se llega a ver, y esta es justo la decisión que hay que entender
/// la primera vez.
class _Motor extends StatelessWidget {
  const _Motor({required this.autopilot, required this.onChanged});

  final bool autopilot;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SegmentedButton<bool>(
          segments: const [
            ButtonSegment(value: false, label: Text('HERMES')),
            ButtonSegment(value: true, label: Text('AUTOPILOT')),
          ],
          selected: {autopilot},
          onSelectionChanged: (s) => onChanged(s.first),
        ),
        const SizedBox(height: 7),
        Row(
          children: [
            StatusLed(
              color: autopilot ? AegisPalette.voz : AegisPalette.brand,
              size: 7,
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                autopilot
                    ? 'Ejecuta herramientas de verdad, una a una, dejando traza de cada una.'
                    : 'Razona y conversa. Para tocar archivos, usa AUTOPILOT.',
                style: const TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 10.5,
                  height: 1.45,
                  color: AegisPalette.fgDim,
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

/// Qué fase de trabajo lleva el encargo.
///
/// Solo aparece si el puente ofrece alguna, y el texto explica para qué sirve:
/// una fase cambia lo que Aegis se permite hacer, así que no es un adorno que
/// se pueda dejar sin leer.
class _SelectorFase extends ConsumerWidget {
  const _SelectorFase();

  static String _ayuda(String fase) => switch (fase) {
        'idea' => 'Aterriza el problema y sus alternativas. No escribe código.',
        'arquitectura' =>
          'Decide cómo se construye, con alternativas y coste de cambio.',
        _ => '',
      };

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final fases = ref.watch(fasesProvider);
    final elegida = ref.watch(faseElegidaProvider);
    return fases.maybeWhen(
      orElse: () => const SizedBox.shrink(),
      data: (lista) {
        if (lista.isEmpty) return const SizedBox.shrink();
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 7,
              runSpacing: 7,
              children: [
                for (final f in lista)
                  ChoiceChip(
                    label: Text(f.toUpperCase()),
                    selected: f == elegida,
                    onSelected: (_) => ref.read(faseElegidaProvider.notifier).alternar(f),
                    labelStyle: TextStyle(
                      fontFamily: AegisPalette.mono,
                      fontSize: 10,
                      letterSpacing: 1,
                      color: f == elegida ? AegisPalette.bg0 : AegisPalette.fgDim,
                    ),
                    selectedColor: AegisPalette.brand,
                    backgroundColor: AegisPalette.bg1,
                    side: BorderSide(
                      color: f == elegida
                          ? AegisPalette.brand
                          : AegisPalette.bg1.withValues(alpha: 1),
                    ),
                    showCheckmark: false,
                  ),
              ],
            ),
            if (_ayuda(elegida).isNotEmpty) ...[
              const SizedBox(height: 7),
              Text(
                _ayuda(elegida),
                style: const TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 10.5,
                  height: 1.45,
                  color: AegisPalette.fgDim,
                ),
              ),
            ],
          ],
        );
      },
    );
  }
}

/// Selector de proyecto del workspace, coloreado por el estado de su ficha.
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
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final p in lista)
                  _pastilla(p, seleccionado == p.alias, () => onChanged(p.alias)),
              ],
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                StatusLed(color: _color(actual), size: 6),
                const SizedBox(width: 7),
                Expanded(
                  child: Text(
                    seleccionado.isEmpty
                        ? 'Sin proyecto: razono sin saber de qué se trata.'
                        : '${actual.alias} · ${_globo(actual)}',
                    style: const TextStyle(
                        fontFamily: AegisPalette.mono,
                        fontSize: 10,
                        color: AegisPalette.fgFaint,
                        height: 1.4),
                  ),
                ),
              ],
            ),
          ],
        );
      },
    );
  }

  Widget _pastilla(ProjectInfo p, bool activo, VoidCallback tap) {
    final color = _color(p);
    return GestureDetector(
      onTap: tap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
        decoration: BoxDecoration(
          color: color.withValues(alpha: activo ? .20 : .07),
          borderRadius: BorderRadius.circular(4),
          border: Border.all(
              color: color.withValues(alpha: activo ? 1 : .45),
              width: activo ? 1.5 : 1),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
                width: 6,
                height: 6,
                decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
            const SizedBox(width: 7),
            Text(
              p.alias,
              style: TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 11.5,
                  fontWeight: activo ? FontWeight.w700 : FontWeight.w400,
                  color: color),
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
  const _TrazaAutopilot({required this.run});

  final AutopilotRun run;

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
        _ok = r.ok;
        _ejecutado = r.ok ? r.resultado : r.error;
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
