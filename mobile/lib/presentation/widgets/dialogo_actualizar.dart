/// Actualizar la app, desde la app.
///
/// ## Por qué esto se pide y no se hace solo
/// Dos razones, y las dos son de este repo. La primera es la que se ve: instalar
/// significa reemplazar el binario, y eso puede dejar la app sin arrancar; que
/// la decisión sea de una persona es lo que hace que un fallo sea reversible.
/// La segunda es que **no se puede** hacerlo solo: Android siempre muestra su
/// diálogo de confirmación. No hay ningún modo de instalarlo en silencio, ni
/// siendo device owner. Cualquier diseño que prometa actualización en segundo
/// plano está prometiendo algo que no existe.
///
/// ## Por qué un `HEAD` antes de nada
/// El APK son 50 MB. Preguntar «¿tengo la última?» pesa tres cabeceras, así que
/// no se baja nada hasta saber que hay algo nuevo. Al revés, la primera versión
/// de esto bajaba el fichero siempre, y en una línea de datos lentos eso son
/// 50 MB por una respuesta que era «no».
library;

import 'package:aegis_console/core/network/instalador_nativo.dart';
import 'package:aegis_console/core/theme/aegis_palette.dart';
import 'package:aegis_console/data/models/version_apk.dart';
import 'package:aegis_console/domain/repositories/agent_repository.dart';
import 'package:flutter/material.dart';

/// Qué está pasando, para que el diálogo pueda contarlo.
enum _Fase { buscando, bajando, listo, instalando, fallido }

class DialogoActualizar extends StatefulWidget {
  const DialogoActualizar({
    super.key,
    required this.repo,
    required this.nativo,
    this.instalado,
  });

  final AgentRepository repo;
  final InstaladorNativo nativo;

  /// El `versionCode` de lo instalado. Si no se pasa, se pregunta al canal. Sirve
  /// para el test, que no tiene canal de verdad.
  final int? instalado;

  @override
  State<DialogoActualizar> createState() => _DialogoActualizarState();
}

class _DialogoActualizarState extends State<DialogoActualizar> {
  _Fase _fase = _Fase.buscando;
  VersionApk _v = const VersionApk(versionCode: 0);
  String _motivo = '';
  String _ruta = '';
  int _recibidos = 0;
  int _total = 0;

  bool get _descargando => _fase == _Fase.bajando;

  @override
  void initState() {
    super.initState();
    _comenzar();
  }

  Future<void> _comenzar() async {
    final instalado = widget.instalado ?? await widget.nativo.versionCode();
    final permiso = await widget.nativo.puedeInstalar();
    final v = await widget.repo.versionApk(instalado: instalado, hayPermiso: permiso);
    if (!mounted) return;
    setState(() {
      _v = v;
      _fase = _Fase.buscando;
      _motivo = v.estado;
    });
  }

  Future<void> _bajar() async {
    setState(() {
      _fase = _Fase.bajando;
      _motivo = 'bajando…';
    });
    try {
      final destino = await widget.nativo.destino();
      final ruta = await widget.repo.descargarApk(
        destino: destino,
        onProgreso: (r, t) {
          // El `setState` dentro del progreso llega desde el hilo de red, y el
          // diálogo puede haberse cerrado mientras bajaba: sin el `mounted`,
          // esto revienta con «setState() called after dispose()».
          if (!mounted) return;
          setState(() {
            _recibidos = r;
            _total = t;
          });
        },
      );
      if (!mounted) return;
      setState(() {
        _ruta = ruta;
        _fase = _Fase.listo;
        _motivo = 'descargado. Listo para que lo instales.';
      });
    } on Object catch (e) {
      if (!mounted) return;
      setState(() {
        _fase = _Fase.fallido;
        _motivo = 'no se pudo descargar: $e';
      });
    }
  }

  Future<void> _instalar() async {
    setState(() => _motivo = 'abriendo el instalador…');
    final error = await widget.nativo.instalar(_ruta);
    if (!mounted) return;
    setState(() {
      if (error == null) {
        _fase = _Fase.instalando;
        _motivo = 'te toca confirmar en la pantalla de Android. El resultado '
            'lo verás al volver a abrir Aegis.';
      } else {
        _fase = _Fase.fallido;
        _motivo = error == 'sin_instalador'
            // Distinguir los dos fallos no es por el detalle: es que con uno se
            // puede arreglar y con el otro no, y un mensaje igual para los dos
            // hace que se pruebe lo que no toca.
            ? 'este móvil no tiene un instalador de APKs declarado. No es algo '
                'que se pueda arreglar desde aquí.'
            : 'no se pudo abrir el instalador: $error';
      }
    });
  }

  Future<void> _abrirPermiso() async {
    await widget.nativo.abrirPermiso();
    if (!mounted) return;
    setState(() => _motivo = 'cuando lo hayas concedido, vuelve a pulsar');
  }

  @override
  Widget build(BuildContext context) {
    final hayNueva = _v.disponible;
    final ocupado = _descargando;

    return AlertDialog(
      backgroundColor: AegisPalette.hueso,
      title: const Text('Actualizar Aegis',
          style: TextStyle(fontFamily: AegisPalette.mono, fontSize: 15, color: AegisPalette.fg)),
      content: SizedBox(
        width: 380,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _linea('tienes', _v.versionCode > 0 ? 'versión ${_v.versionCode}' : 'la que hay instalada'),
            _linea('el bridge tiene',
                _v.versionCode > 0 ? '${_v.versionCode} (${_v.versionName})' : 'nada que servir'),
            const SizedBox(height: 12),
            Text(_motivo,
                style: const TextStyle(
                    fontFamily: AegisPalette.mono, fontSize: 11.5, color: AegisPalette.fgDim)),
            if (ocupado) ...[
              const SizedBox(height: 14),
              LinearProgressIndicator(
                // Un total de 0 o menos significa que el servidor no lo mandó.
                // Sin este `null`, la barra dibuja un valor de 0/0 y Dart lanza;
                // con `null` se muestra indeterminado, que es la forma honesta de
                // decir «no lo sé y sigue bajando».
                value: (_total > 0) ? _recibidos / _total : null,
                backgroundColor: AegisPalette.line,
                valueColor: const AlwaysStoppedAnimation(AegisPalette.brand),
              ),
              const SizedBox(height: 6),
              Text(
                _total > 0
                    ? '${(_recibidos / 1048576).toStringAsFixed(1)} de '
                        '${(_total / 1048576).toStringAsFixed(1)} MB'
                    : '${(_recibidos / 1048576).toStringAsFixed(1)} MB',
                style: const TextStyle(
                    fontFamily: AegisPalette.mono, fontSize: 10.5, color: AegisPalette.fgFaint),
              ),
            ],
            if (hayNueva && !_v.puedeInstalar && !ocupado) ...[
              const SizedBox(height: 14),
              // Sin permiso el botón de instalar queda deshabilitado y
              // este es el que sí hace algo. Un botón que no hace nada es peor
              // que no tenerlo: parece un fallo.
              OutlinedButton.icon(
                onPressed: _abrirPermiso,
                icon: const Icon(Icons.lock_open, size: 15),
                label: const Text('Ir al permiso en Ajustes'),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: ocupado ? null : () => Navigator.of(context).pop(),
          child: const Text('Cerrar'),
        ),
        if (_fase == _Fase.listo && _v.puedeInstalar)
          FilledButton.icon(
            onPressed: _instalar,
            icon: const Icon(Icons.install_mobile, size: 15),
            label: const Text('Instalar'),
          )
        else if (hayNueva && _v.puedeInstalar)
          FilledButton.icon(
            onPressed: ocupado ? null : _bajar,
            icon: const Icon(Icons.download, size: 15),
            label: Text(ocupado ? 'Bajando…' : 'Bajar la nueva'),
          ),
      ],
    );
  }

  Widget _linea(String que, String valor) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(
          children: [
            SizedBox(
              width: 96,
              child: Text(que,
                  style: const TextStyle(
                      fontFamily: AegisPalette.mono, fontSize: 11, color: AegisPalette.fgFaint)),
            ),
            Text(valor,
                style: const TextStyle(
                    fontFamily: AegisPalette.mono, fontSize: 11.5, color: AegisPalette.fg)),
          ],
        ),
      );
}