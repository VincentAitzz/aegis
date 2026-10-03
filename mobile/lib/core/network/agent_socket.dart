/// Cliente WebSocket con reconexión y backoff (canal bidireccional hacia el bridge).
library;

import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

typedef OnEvent = void Function(Map<String, dynamic> event);
typedef OnStatus = void Function(String status);

class AgentSocket {
  AgentSocket({
    required this.wsUrl,
    this.onEvent,
    this.onStatus,
    this.maxRetries = 8,
  });

  final String wsUrl;
  OnEvent? onEvent;
  OnStatus? onStatus;
  final int maxRetries;

  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _sub;
  bool _closed = false;
  int _retries = 0;
  final List<String> _pendingSubscriptions = [];

  Future<void> connect() async {
    _closed = false;
    await _openChannel();
  }

  Future<void> _openChannel() async {
    if (_closed) return;
    try {
      onStatus?.call(_retries == 0 ? 'connecting' : 'reconnecting');
      _channel = WebSocketChannel.connect(Uri.parse(wsUrl));
      _channel!.ready.then((_) {
        _retries = 0;
        onStatus?.call('connected');
      });
      _sub = _channel!.stream.listen(
        (raw) => _handleRaw(raw),
        onError: (_) => _scheduleReconnect(),
        onDone: _scheduleReconnect,
        cancelOnError: true,
      );
      // La reconexión re-suscribe automáticamente lo que pidió el cliente.
      for (final runId in _pendingSubscriptions) {
        _send({'type': 'subscribe', 'run_id': runId});
      }
    } catch (_) {
      _scheduleReconnect();
    }
  }

  void subscribe(String runId) {
    if (!_pendingSubscriptions.contains(runId)) {
      _pendingSubscriptions.add(runId);
    }
    _send({'type': 'subscribe', 'run_id': runId});
  }

  void approve(String runId, String decision, {String? comment}) {
    _send({
      'type': 'approve',
      'run_id': runId,
      'decision': decision,
      if (comment != null && comment.isNotEmpty) 'text': comment,
    });
  }

  void steer(String runId, String text) {
    _send({'type': 'steer', 'run_id': runId, 'text': text});
  }

  void stop(String runId) {
    _send({'type': 'stop', 'run_id': runId});
  }

  void _send(Object message) {
    _channel?.sink.add(jsonEncode(message));
  }

  void _handleRaw(dynamic raw) {
    if (raw is! String) return;
    try {
      onEvent?.call(jsonDecode(raw) as Map<String, dynamic>);
    } catch (_) {
      // trama inválida: se ignora
    }
  }

  void _scheduleReconnect() {
    if (_closed) {
      onStatus?.call('closed');
      return;
    }
    _retries++;
    if (_retries > maxRetries) {
      onStatus?.call('error');
      return;
    }
    final delay = Duration(seconds: (2 * _retries).clamp(2, 30));
    onStatus?.call('reconnecting');
    Timer(delay, _openChannel);
  }

  Future<void> close() async {
    _closed = true;
    await _sub?.cancel();
    await _channel?.sink.close();
  }

  bool get isClosed => _closed;
}
