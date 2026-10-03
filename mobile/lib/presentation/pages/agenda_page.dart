/// Agenda: lo que tienes que hacer, y lo que Aegis te recuerda.
///
/// ## Por qué sin fecha no vence nunca
/// Una tarea sin fecha significa "cuando pueda". Un planificador que tratara las
/// sin fecha como vencidas dispararía en cada pasada, y un recordatorio que
/// suena cada diez minutos es un recordatorio que se ignora. Por eso la fecha
/// es lo que convierte una tarea en recordatorio.
///
/// ## Por qué se escribe de persona al bridge
/// Sin pasar por el modelo, a propósito: una tarea con la fecha exacta y el
/// título literal no puede pasar por un 7B que reinterpretaría el texto. Es la
/// misma razón por la que las fichas van directas (A-019).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/aegis_palette.dart';
import '../../core/widgets/status_led.dart';
import '../../data/models/asistente_models.dart';
import '../providers/agent_providers.dart';

class AgendaPage extends ConsumerWidget {
  const AgendaPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tareas = ref.watch(tareasProvider);
    final notas = ref.watch(notasProvider);

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 28),
      children: [
        Row(
          children: [
            Expanded(
              child: FilledButton.icon(
                onPressed: () => _nuevaTarea(context, ref),
                icon: const Icon(Icons.add, size: 17),
                label: const Text('Tarea'),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: OutlinedButton.icon(
                onPressed: () => _nuevaNota(context, ref),
                icon: const Icon(Icons.sticky_note_2_outlined, size: 16),
                label: const Text('Nota'),
              ),
            ),
          ],
        ),
        const SizedBox(height: 18),
        Text(
          'Pendientes',
          style: const TextStyle(
            fontFamily: AegisPalette.mono,
            fontSize: 10.5,
            letterSpacing: 1,
            color: AegisPalette.fgFaint,
          ),
        ),
        const SizedBox(height: 10),
        tareas.when(
          loading: () => const Text('…',
              style: TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 12,
                  color: AegisPalette.fgFaint)),
          error: (e, _) => Text('$e',
              style: const TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 11.5,
                  color: AegisPalette.danger)),
          data: (lista) => lista.isEmpty
              ? const _Vacio(
                  icono: Icons.check_circle_outline,
                  titulo: 'Nada pendiente',
                  cuerpo: 'Cuando te anotes algo, aparece aquí.',
                )
              : Column(
                  children: [for (final t in lista) _TareaFila(tarea: t)],
                ),
        ),
        const SizedBox(height: 22),
        Text(
          'Notas',
          style: const TextStyle(
            fontFamily: AegisPalette.mono,
            fontSize: 10.5,
            letterSpacing: 1,
            color: AegisPalette.fgFaint,
          ),
        ),
        const SizedBox(height: 10),
        notas.when(
          loading: () => const Text('…',
              style: TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 12,
                  color: AegisPalette.fgFaint)),
          error: (e, _) => Text('$e',
              style: const TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 11.5,
                  color: AegisPalette.danger)),
          data: (lista) => lista.isEmpty
              ? const _Vacio(
                  icono: Icons.sticky_note_2_outlined,
                  titulo: 'Sin notas',
                  cuerpo: 'Las notas no vencen. Son para lo que quieres '
                      'acordarte y no se te puede meter en la cabeza.',
                )
              : Column(
                  children: [for (final n in lista) _NotaFila(nota: n)],
                ),
        ),
      ],
    );
  }

  Future<void> _nuevaTarea(BuildContext context, WidgetRef ref) async {
    final titulo = TextEditingController();
    final fecha = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: AegisPalette.bg1,
        title: const Text('Nueva tarea',
            style: TextStyle(
                fontFamily: AegisPalette.display,
                fontSize: 17,
                letterSpacing: 2,
                color: AegisPalette.fg)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: titulo,
              autofocus: true,
              decoration: const InputDecoration(hintText: '¿Qué hay que hacer?'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: fecha,
              decoration: const InputDecoration(
                hintText: 'Fecha (AAAA-MM-DD). Vacía = cuando puedas',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Guardar'),
          ),
        ],
      ),
    );
    final texto = titulo.text.trim();
    titulo.dispose();
    fecha.dispose();
    if (ok != true || texto.isEmpty) return;
    await ref.read(agentRepositoryProvider).crearTarea(
          titulo: texto,
          para: fecha.text.trim(),
        );
    refrescarAsistente(ref);
  }

  Future<void> _nuevaNota(BuildContext context, WidgetRef ref) async {
    final cuerpo = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: AegisPalette.bg1,
        title: const Text('Nueva nota',
            style: TextStyle(
                fontFamily: AegisPalette.display,
                fontSize: 17,
                letterSpacing: 2,
                color: AegisPalette.fg)),
        content: TextField(
          controller: cuerpo,
          autofocus: true,
          maxLines: 6,
          decoration: const InputDecoration(hintText: 'Escribe. El título es la primera línea.'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Guardar'),
          ),
        ],
      ),
    );
    final texto = cuerpo.text.trim();
    cuerpo.dispose();
    if (ok != true || texto.isEmpty) return;
    final primeraLinea = texto.split('\n').first.trim();
    await ref.read(agentRepositoryProvider).crearNota(
          titulo: primeraLinea.length > 60 ? '${primeraLinea.substring(0, 60)}…' : primeraLinea,
          cuerpo: texto,
        );
    refrescarAsistente(ref);
  }
}

class _TareaFila extends ConsumerStatefulWidget {
  const _TareaFila({required this.tarea});

  final Tarea tarea;

  @override
  ConsumerState<_TareaFila> createState() => _TareaFilaState();
}

class _TareaFilaState extends ConsumerState<_TareaFila> {
  bool _ocupado = false;

  Future<void> _hacer() async {
    setState(() => _ocupado = true);
    try {
      await ref.read(agentRepositoryProvider).actualizarTarea(
            widget.tarea.id,
            estado: 'hecha',
          );
      refrescarAsistente(ref);
    } finally {
      if (mounted) setState(() => _ocupado = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = widget.tarea;
    final vencida = t.vencida;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Container(
        padding: const EdgeInsets.fromLTRB(6, 6, 12, 6),
        decoration: BoxDecoration(
          color: vencida ? AegisPalette.danger.withValues(alpha: .08) : AegisPalette.bg1,
          borderRadius: BorderRadius.circular(6),
          border: Border.all(
              color: vencida
                  ? AegisPalette.danger.withValues(alpha: .5)
                  : AegisPalette.line),
        ),
        child: Row(
          children: [
            IconButton(
              onPressed: _ocupado ? null : _hacer,
              iconSize: 18,
              icon: Icon(
                Icons.check_box_outline_blank,
                color: vencida ? AegisPalette.danger : AegisPalette.fgFaint,
              ),
              tooltip: 'Marcar como hecha',
            ),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    t.titulo,
                    style: const TextStyle(
                      fontFamily: AegisPalette.mono,
                      fontSize: 12.5,
                      color: AegisPalette.fg,
                    ),
                  ),
                  if (t.para.isNotEmpty) ...[
                    const SizedBox(height: 3),
                    Row(
                      children: [
                        StatusLed(
                          color: vencida ? AegisPalette.danger : AegisPalette.brand,
                          size: 5,
                        ),
                        const SizedBox(width: 6),
                        Text(
                          vencida ? 'venció el ${t.para}' : t.para,
                          style: TextStyle(
                            fontFamily: AegisPalette.mono,
                            fontSize: 10,
                            color: vencida ? AegisPalette.danger : AegisPalette.fgFaint,
                          ),
                        ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _NotaFila extends ConsumerStatefulWidget {
  const _NotaFila({required this.nota});

  final Nota nota;

  @override
  ConsumerState<_NotaFila> createState() => _NotaFilaState();
}

class _NotaFilaState extends ConsumerState<_NotaFila> {
  bool _ocupado = false;

  Future<void> _borrar() async {
    final seguro = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: AegisPalette.bg1,
        title: const Text('¿Borrarla?',
            style: TextStyle(
                fontFamily: AegisPalette.display,
                fontSize: 17,
                letterSpacing: 2,
                color: AegisPalette.fg)),
        content: const Text(
          'Se borra de verdad. No hay copia ni se puede recuperar.',
          style: TextStyle(
            fontFamily: AegisPalette.mono,
            fontSize: 12,
            height: 1.5,
            color: AegisPalette.fgDim,
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Dejar'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
                backgroundColor: AegisPalette.danger,
                foregroundColor: AegisPalette.bg0),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Borrar'),
          ),
        ],
      ),
    );
    if (seguro != true) return;
    setState(() => _ocupado = true);
    try {
      await ref.read(agentRepositoryProvider).borrarNota(widget.nota.id);
      refrescarAsistente(ref);
    } finally {
      if (mounted) setState(() => _ocupado = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final n = widget.nota;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 10, 4, 10),
        decoration: BoxDecoration(
          color: AegisPalette.bg1,
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: AegisPalette.line),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Padding(
              padding: EdgeInsets.only(top: 2),
              child: Icon(Icons.sticky_note_2_outlined,
                  size: 13, color: AegisPalette.fgFaint),
            ),
            const SizedBox(width: 9),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (n.titulo.isNotEmpty)
                    Text(
                      n.titulo,
                      style: const TextStyle(
                        fontFamily: AegisPalette.mono,
                        fontSize: 12.5,
                        color: AegisPalette.fg,
                      ),
                    ),
                  if (n.cuerpo.isNotEmpty)
                    Text(
                      n.cuerpo,
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontFamily: AegisPalette.mono,
                        fontSize: 10.5,
                        height: 1.5,
                        color: AegisPalette.fgDim,
                      ),
                    ),
                ],
              ),
            ),
            IconButton(
              onPressed: _ocupado ? null : _borrar,
              iconSize: 15,
              icon: const Icon(Icons.delete_outline, color: AegisPalette.fgFaint),
              tooltip: 'Borrar la nota',
            ),
          ],
        ),
      ),
    );
  }
}

class _Vacio extends StatelessWidget {
  const _Vacio({required this.icono, required this.titulo, required this.cuerpo});

  final IconData icono;
  final String titulo;
  final String cuerpo;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 22, horizontal: 12),
      child: Column(
        children: [
          Icon(icono, size: 26, color: AegisPalette.fgFaint),
          const SizedBox(height: 12),
          Text(
            titulo,
            style: const TextStyle(
              fontFamily: AegisPalette.display,
              fontSize: 15,
              fontWeight: FontWeight.w600,
              letterSpacing: 2,
              color: AegisPalette.fg,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            cuerpo,
            textAlign: TextAlign.center,
            style: const TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 11,
              height: 1.6,
              color: AegisPalette.fgFaint,
            ),
          ),
        ],
      ),
    );
  }
}