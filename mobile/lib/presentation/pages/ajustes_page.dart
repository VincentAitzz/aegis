/// Ajustes: qué es esto, cómo funciona, y la puerta de despliegue.
///
/// ## Por qué "qué es esto" vive aquí y no en un onboarding
/// Un recorrido guiado obliga a leerlo una vez y luego estorba. Aquí se abre
/// cuando hace falta, que es justo cuando Aegis todavía no ha hecho nada y las
/// palabras `HERMES` y `AUTOPILOT` no significan nada.
///
/// ## Por qué aquí la puerta y no en Ahora
/// La puerta de despliegue **interrumpe**: deja el móvil esperando una decisión.
/// Cosas que interrumpen van en un sitio al que se va a propósito, no en la
/// pantalla desde la que se trabaja.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/aegis_palette.dart';
import '../../core/widgets/hud_panel.dart';
import '../../core/widgets/status_led.dart';
import '../../data/models/agent_models.dart';
import '../providers/agent_providers.dart';
import 'connectivity_page.dart';

class AjustesPage extends ConsumerWidget {
  const AjustesPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final host = ref.watch(appConfigProvider);
    final health = ref.watch(healthProvider);

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 28),
      children: [
        _EstadoPuente(health: health, host: host.apiHost),
        const SizedBox(height: 14),
        const _QueEsEsto(),
        const SizedBox(height: 14),
        _Despliegues(),
        const SizedBox(height: 14),
        _MarcaInfo(),
        const SizedBox(height: 14),
        OutlinedButton.icon(
          onPressed: () => Navigator.of(context).push(
            MaterialPageRoute<void>(builder: (_) => const ConnectivityPage()),
          ),
          icon: const Icon(Icons.insights_outlined, size: 15),
          label: const Text('Diagnóstico completo'),
        ),
      ],
    );
  }
}

class _EstadoPuente extends StatelessWidget {
  const _EstadoPuente({required this.health, required this.host});

  final AsyncValue<BridgeHealth> health;
  final String host;

  @override
  Widget build(BuildContext context) {
    return health.when(
      loading: () => HudPanel(
        title: 'PUENTE',
        trailing: const StatusLed(color: AegisPalette.warn, size: 8, pulse: true),
        child: const Text('preguntando…',
            style: TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 12,
                color: AegisPalette.fgDim)),
      ),
      error: (e, _) => HudPanel(
        title: 'PUENTE',
        accent: AegisPalette.danger,
        trailing: const StatusLed(color: AegisPalette.danger, size: 8),
        child: Text('no pude preguntarle: $e',
            style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 12,
                color: AegisPalette.danger,
                height: 1.5)),
      ),
      data: (h) => HudPanel(
        title: 'PUENTE',
        accent: h.ok ? AegisPalette.ok : AegisPalette.danger,
        trailing: StatusLed(
            color: h.ok ? AegisPalette.ok : AegisPalette.danger, size: 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(host,
                style: const TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 13,
                    color: AegisPalette.fg)),
            const SizedBox(height: 10),
            _Fila('Puente', h.ok, h.ok ? 'contesto' : 'no contesta'),
            _Fila('Hermes', h.hermesOk, h.hermesOk ? 'arrancado' : 'caído'),
            _Fila('Ollama', h.ollamaOk, h.ollamaOk ? 'arrancado' : 'caído'),
            const SizedBox(height: 8),
            Text(
              h.models.isEmpty ? 'sin modelos' : h.models.join(', '),
              style: const TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 10.5,
                  color: AegisPalette.fgFaint,
                  height: 1.5),
            ),
          ],
        ),
      ),
    );
  }
}

class _Fila extends StatelessWidget {
  const _Fila(this.que, this.ok, this.como);

  final String que;
  final bool ok;
  final String como;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        children: [
          SizedBox(
            width: 74,
            child: Text(que,
                style: const TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 11.5,
                    color: AegisPalette.fgDim)),
          ),
          StatusLed(color: ok ? AegisPalette.ok : AegisPalette.danger, size: 6),
          const SizedBox(width: 8),
          Text(como,
              style: TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 11.5,
                  color: ok ? AegisPalette.fg : AegisPalette.danger)),
        ],
      ),
    );
  }
}

/// Lo que Aegis es y qué puede hacer. Colapsado porque interesa una vez.
class _QueEsEsto extends StatelessWidget {
  const _QueEsEsto();

  @override
  Widget build(BuildContext context) {
    return HudPanel(
      title: 'QUÉ ES ESTO',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Soy Aegis. Vivo en tu portátil y esta app es el mando. '
            'Si el portátil está apagado, no puedo hacer nada — eso es a propósito: '
            'no quiero depender de un servidor que pueda caerse.',
            style: TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 11.5,
                height: 1.6,
                color: AegisPalette.fgDim),
          ),
          const SizedBox(height: 12),
          const _Concepto(
            titulo: 'Hermes',
            cuerpo: 'Para pensar y hablar. Lee, razona, te responde. '
                'No toca tus archivos.',
          ),
          const _Concepto(
            titulo: 'Autopilot',
            cuerpo: 'Para hacer cosas. Ejecuta herramientas de verdad sobre tus '
                'proyectos y deja un rastro de cada paso que puedes revisar.',
          ),
          const _Concepto(
            titulo: 'Proyectos',
            cuerpo: 'Cada uno tiene una ficha que me dice qué es y qué no '
                'toca. Sin ficha, no escribo: no sé qué estoy tocanto.',
          ),
          const SizedBox(height: 10),
          const Text(
            'Nada sale a internet. Todo va por tu red privada.',
            style: TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 10.5,
                color: AegisPalette.fgFaint,
                height: 1.5),
          ),
        ],
      ),
    );
  }
}

class _Concepto extends StatelessWidget {
  const _Concepto({required this.titulo, required this.cuerpo});

  final String titulo;
  final String cuerpo;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 72,
            child: Text(
              titulo,
              style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 11,
                fontWeight: FontWeight.w700,
                color: AegisPalette.brand,
              ),
            ),
          ),
          Expanded(
            child: Text(
              cuerpo,
              style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 11,
                height: 1.55,
                color: AegisPalette.fgDim,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// La puerta de despliegue.
///
/// Va aquí porque **interrumpe**: mientras esté visible, Aegis está parado
/// esperando tu OK. Decir exactamente qué va a pasar al aprobar es justo lo que
/// evita aprobar a ciegas.
class _Despliegues extends ConsumerStatefulWidget {
  @override
  ConsumerState<_Despliegues> createState() => _DesplieguesState();
}

class _DesplieguesState extends ConsumerState<_Despliegues> {
  bool _ocupado = false;

  Future<void> _decidir(DeployRequest d, bool aprobar) async {
    setState(() => _ocupado = true);
    try {
      await ref.read(agentRepositoryProvider).decideDeploy(d.id, aprobar: aprobar);
      ref.read(deploysProvider.notifier).refrescar();
    } finally {
      if (mounted) setState(() => _ocupado = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(deploysProvider);
    if (state == null || !state.hayPendientes) return const SizedBox.shrink();

    return HudPanel(
      title: 'ESPERANDO TU OK',
      accent: AegisPalette.warn,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final d in state.pendientes) ...[
            Text(
              d.razon.isEmpty ? 'Sin detalle' : d.razon,
              style: const TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 11.5,
                  color: AegisPalette.fgDim,
                  height: 1.5),
            ),
            const SizedBox(height: 6),
            Text(
              d.quePasa,
              style: const TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 11,
                  color: AegisPalette.fg,
                  height: 1.5),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: FilledButton(
                    onPressed: _ocupado ? null : () => _decidir(d, true),
                    style: FilledButton.styleFrom(
                      backgroundColor: AegisPalette.ok,
                      foregroundColor: AegisPalette.bg0,
                    ),
                    child: const Text('APROBAR UNA VEZ'),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton(
                    onPressed: _ocupado ? null : () => _decidir(d, false),
                    child: const Text('NO'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            const Text(
              'Aprobar es de un solo uso: sirve para esta instalación y se gasta.',
              style: TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 9.5,
                  color: AegisPalette.fgFaint,
                  height: 1.5),
            ),
          ],
        ],
      ),
    );
  }
}

class _MarcaInfo extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return HudPanel(
      title: 'LA MARCA',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Glifo y color están en el código, no en imágenes: '
            'assets/brand/derivados/ es para el ícono del lanzador y '
            'assets/brand/inbox/ es tu almacén de referencias.',
            style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 10.5,
                height: 1.6,
                color: AegisPalette.fgDim),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              _Muestra('marca', AegisPalette.brand),
              _Muestra('info', AegisPalette.brand),
              _Muestra('ok', AegisPalette.ok),
              _Muestra('aviso', AegisPalette.warn),
              _Muestra('error', AegisPalette.danger),
            ],
          ),
        ],
      ),
    );
  }
}

class _Muestra extends StatelessWidget {
  const _Muestra(this.que, this.color);

  final String que;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(right: 14),
      child: Row(
        children: [
          Container(width: 9, height: 9, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
          const SizedBox(width: 5),
          Text(que,
              style: const TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 9.5,
                  color: AegisPalette.fgFaint)),
        ],
      ),
    );
  }
}
