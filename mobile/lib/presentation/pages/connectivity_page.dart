/// Diagnóstico: qué está vivo y qué no.
///
/// ## Por qué vive en su propia pantalla y no en Ajustes
/// En Ajustes está el resumen que se mira de reojo. Esto es para cuando algo
/// **no funciona** y hay que saber por qué: los tres nodos por separado, los
/// modelos que hay de verdad. El resumen de Ajustes puede mentir por
/// simplificación; esto es lo que se comprueba.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/aegis_palette.dart';
import '../../core/widgets/aegis_scaffold.dart';
import '../../core/widgets/hud_panel.dart';
import '../../core/widgets/status_led.dart';
import '../providers/agent_providers.dart';

class ConnectivityPage extends ConsumerWidget {
  const ConnectivityPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final host = ref.watch(appConfigProvider);
    final health = ref.watch(healthProvider);
    final models = ref.watch(modelsProvider);

    return AegisScaffold(
      appBar: AppBar(title: const Text('DIAGNÓSTICO')),
      // Sin superposición: es la pantalla con más texto técnico pequeño de la
      // app, y la textura solo le resta legibilidad.
      superposicion: false,
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          HudPanel(
            title: 'PUENTE',
            accent: AegisPalette.ok,
            trailing: const StatusLed(color: AegisPalette.ok, size: 9),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  host.apiHost,
                  style: const TextStyle(fontFamily: AegisPalette.mono, fontSize: 13.5, color: AegisPalette.fg),
                ),
                const SizedBox(height: 2),
                Row(
                  children: [
                    if (host.usesMeshHostname) ...[
                      const Text(
                        '▲',
                        style: TextStyle(fontFamily: AegisPalette.mono, fontSize: 11, color: AegisPalette.brand),
                      ),
                      const SizedBox(width: 5),
                      const Text(
                        'privada · MagicDNS',
                        style: TextStyle(fontFamily: AegisPalette.mono, fontSize: 11, color: AegisPalette.brand),
                      ),
                    ] else ...[
                      const Text(
                        '●',
                        style: TextStyle(fontFamily: AegisPalette.mono, fontSize: 11, color: AegisPalette.fgFaint),
                      ),
                      const SizedBox(width: 5),
                      const Text(
                        'loopback local',
                        style: TextStyle(fontFamily: AegisPalette.mono, fontSize: 11, color: AegisPalette.fgFaint),
                      ),
                    ],
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          health.when(
            loading: () => const HudPanel(
              title: 'ESTADO',
              trailing: StatusLed(color: AegisPalette.warn, size: 9, pulse: true),
              child: Text(
                '// sondeando nodos…',
                style: TextStyle(fontFamily: AegisPalette.mono, fontSize: 12, color: AegisPalette.fgDim),
              ),
            ),
            error: (e, _) => HudPanel(
              title: 'SIN VÍA',
              accent: AegisPalette.danger,
              trailing: const StatusLed(color: AegisPalette.danger, size: 9),
              child: Text(
                '// no se alcanzó el bridge\n$e',
                style: const TextStyle(fontFamily: AegisPalette.mono, fontSize: 12, color: AegisPalette.danger),
              ),
            ),
            data: (h) => Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _node(
                  title: 'BRIDGE (${h.host})',
                  value: h.ok ? 'saludable' : 'degradado',
                  sub: 'hermes=${h.hermesOk ? 'ok' : 'down'} · ollama=${h.ollamaOk ? 'ok' : 'down'}',
                  ok: h.ok,
                ),
                const SizedBox(height: 12),
                _node(
                  title: 'AGENTES',
                  value: h.agents.isEmpty ? '// ninguno' : h.agents.join(' · '),
                  sub: '',
                  ok: h.agents.isNotEmpty,
                ),
                const SizedBox(height: 12),
                _node(
                  title: 'MODELO OLLAMA',
                  value: models.when(
                    data: (m) => m.isEmpty ? 'sin modelos' : m.map((x) => x.split(':')[0]).join(', '),
                    loading: () => 'consultando…',
                    error: (e, _) => 'error',
                  ),
                  sub: models.when(
                    data: (m) => m.isEmpty ? 'arranca ${host.apiHost}:11434' : 'vía bridge',
                    loading: () => '',
                    error: (e, _) => '$e',
                  ),
                  ok: health.hasValue && h.ollamaOk,
                ),
                const SizedBox(height: 12),
                HudPanel(
                  title: 'LOG',
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '[health] host=${h.host} hermes=${h.hermesOk ? 'ok' : 'down'} ollama=${h.ollamaOk ? 'ok' : 'down'}',
                          style: const TextStyle(fontFamily: AegisPalette.mono, fontSize: 10.5, color: AegisPalette.fgDim),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          '[agents] ${h.agents.join(' ')}',
                          style: const TextStyle(fontFamily: AegisPalette.mono, fontSize: 10.5, color: AegisPalette.fgDim),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          OutlinedButton.icon(
            onPressed: () => ref.invalidate(healthProvider),
            icon: const Icon(Icons.refresh, size: 16),
            label: const Text('Releer'),
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }

  Widget _node({
    required String title,
    required String value,
    required String sub,
    required bool ok,
  }) {
    final color = ok ? AegisPalette.ok : AegisPalette.danger;
    return HudPanel(
      title: title,
      accent: color,
      trailing: StatusLed(color: color, size: 9),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            value,
            style: const TextStyle(fontFamily: AegisPalette.mono, fontSize: 13, color: AegisPalette.fg),
          ),
          if (sub.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              sub,
              style: const TextStyle(fontFamily: AegisPalette.mono, fontSize: 11, color: AegisPalette.fgFaint),
            ),
          ],
        ],
      ),
    );
  }
}
