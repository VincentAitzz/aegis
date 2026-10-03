/// Configuración de red de la app, resuelta en build-time.
///
/// El host de la API se inyecta con `--dart-define=API_HOST=...`:
///   - `localhost`           -> emulador con adb reverse / simulador iOS
///   - `aegis.<tailnet>.ts.net` -> nodo del bridge sobre la malla (MagicDNS)
///
/// Nunca se usa una IP estática. Si no se define API_HOST, se usa `localhost`
/// (entorno local del emulador/simulador).
library;

class AppConfig {
  const AppConfig({
    required this.apiHost,
    required this.usesMeshHostname,
  });

  /// Host tal cual viene del dart-define (o 'localhost' por defecto).
  final String apiHost;

  /// True cuando el host proviene de un dart-define explícito (malla/red privada virtual).
  final bool usesMeshHostname;

  static const _envHost = String.fromEnvironment('API_HOST');

  factory AppConfig.fromEnvironment() {
    final host = _envHost.isNotEmpty ? _envHost : 'localhost';
    return AppConfig(
      apiHost: host,
      usesMeshHostname: _envHost.isNotEmpty,
    );
  }

  /// Devuelve la base HTTP (sin barra final) split host/port cuando aplica.
  (String host, int port) get authority {
    final h = apiHost.toLowerCase();
    if (h.startsWith('http://') || h.startsWith('https://')) {
      throw StateError('API_HOST debe ser host o host:puerto, sin esquema.');
    }
    final idx = apiHost.lastIndexOf(':');
    if (idx > 0 && idx < apiHost.length - 1) {
      final port = int.tryParse(apiHost.substring(idx + 1));
      if (port != null) return (apiHost.substring(0, idx), port);
    }
    return (apiHost, 8000);
  }

  String get httpBase {
    final (h, p) = authority;
    return 'http://$h:$p';
  }

  String get wsBase {
    final (h, p) = authority;
    return 'ws://$h:$p/ws';
  }
}
