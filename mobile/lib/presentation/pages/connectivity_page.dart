/// Página de autodiagnóstico de la conexión al puente y la malla.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/agent_providers.dart';

class ConnectivityPage extends ConsumerWidget {
  const ConnectivityPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final host = ref.watch(appConfigProvider);
    final health = ref.watch(healthProvider);
    final models = ref.watch(modelsProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Conectividad')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _section(
            'Puente (host del backend)',
            host.apiHost,
            host.usesMeshHostname ? 'malla privada (Tailscale)' : 'loopback local',
            usingMesh: host.usesMeshHostname,
          ),
          const SizedBox(height: 12),
          health.when(
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (e, _) => _errorBox('No se alcanzó el bridge', '$e'),
            data: (h) => Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _section(
                  'Bridge (${h.host})',
                  h.ok ? 'saludable' : 'degradado',
                  'hermes=${h.hermesOk ? "ok" : "down"} · ollama=${h.ollamaOk ? "ok" : "down"}',
                  ok: h.ok,
                ),
                const SizedBox(height: 12),
                _section(
                  'Agentes disponibles',
                  h.agents.join(', '),
                  '',
                  ok: true,
                ),
                const SizedBox(height: 12),
                _section(
                  'Modelo Ollama',
                  models.when(
                    data: (m) => m.isEmpty ? 'sin modelos' : m.map((x) => x.split(":")[0]).join(', '),
                    loading: () => 'consultando…',
                    error: (e, _) => 'error',
                  ),
                  models.when(
                    data: (m) => m.isEmpty ? 'arranca ${host.apiHost}:11434' : 'vía bridge',
                    loading: () => '',
                    error: (e, _) => '$e',
                  ),
                  ok: health.hasValue && h.ollamaOk,
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),
          OutlinedButton.icon(
            onPressed: () => ref.invalidate(healthProvider),
            icon: const Icon(Icons.refresh),
            label: const Text('Repetir diagnóstico'),
          ),
        ],
      ),
    );
  }

  Widget _section(String title, String value, String subtitle, {bool? ok, bool usingMesh = false}) {
    final color = ok == null
        ? Colors.blueGrey
        : ok
            ? Colors.green
            : Colors.redAccent;
    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: color.withValues(alpha: .4)),
      ),
      child: ListTile(
        leading: Icon(
          ok == null ? Icons.rotate_right : (ok ? Icons.check_circle : Icons.error),
          color: color,
        ),
        title: Text(title),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SizedBox(height: 2),
            Text(value, style: const TextStyle(fontWeight: FontWeight.w600)),
            if (subtitle.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(subtitle, style: TextStyle(fontSize: 12, color: Colors.grey.shade600)),
              ),
            if (usingMesh)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: const Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.vpn_lock, size: 13, color: Colors.indigo),
                    SizedBox(width: 4),
                    Text('privada · MagicDNS', style: TextStyle(fontSize: 11, color: Colors.indigo)),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _errorBox(String title, String detail) {
    return Card(
      elevation: 0,
      color: Colors.red.shade50,
      child: ListTile(
        leading: const Icon(Icons.cloud_off, color: Colors.red),
        title: Text(title),
        subtitle: Text(detail, style: const TextStyle(fontSize: 12)),
      ),
    );
  }
}