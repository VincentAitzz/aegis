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

class _DialogoActualizarState extends State<DialogoActualizar> with WidgetsBindingObserver {
  _Fase _fase = _Fase.buscando;
  VersionApk _v = const VersionApk(versionCode: 0);
  String _motivo = '';
  String _ruta = '';
  int _recibidos = 0;
  int _total = 0;

  /// El `versionCode` de **lo que hay instalado en este móvil**.
  ///
  /// Antes no se guardaba: la línea «tienes» pintaba `_v.versionCode`, que es la
  /// versión **remota**. Con una 3 instalada y una 4 en el bridge, decía «tienes
  /// versión 4» —justo lo contrario de lo que pasa— y el diálogo era un espejo
  /// de la respuesta del servidor en lugar de una comparación.
  int? _instalado;

  /// Si la última consulta llegó a preguntarle al bridge.
  ///
  /// Distingue dos pantallas que antes se confundían en una sola: «el bridge no
  /// tiene APK» y «no se pudo preguntar». La segunda salía con la caja vacía y
  /// sin motivo, porque la excepción se comía el `setState` y el `await` nunca
  /// llegaba —el diálogo se quedaba en «preguntando» para siempre.
  bool _llego = false;

  /// Algo que pasó al intentar abrir Ajustes y que hay que contar.
  ///
  /// Vive aparte de [motivo] a propósito: `_motivo` es lo que dijo el bridge y
  /// se borra al volver a preguntar. Esto es «tu botón acaba de fallar», que
  /// sobrevive a esa repregunta porque si no, el fallo se iría por la ventana en
  /// cuanto `didChangeAppLifecycleState` preguntara otra vez.
  String _nota = '';

  bool get _descargando => _fase == _Fase.bajando;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _comenzar();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState estado) {
    // Volver de Ajustes es el momento en que el permiso puede haber cambiado, y
    // es el único momento en que se puede notar. Sin esto, el diálogo decía
    // «vuelve a pulsar» sin ningún botón que pulsar: había que cerrar y abrir a
    // mano, y un texto que pide algo que no existe es una calle sin salida.
    if (estado == AppLifecycleState.resumed) _comenzar();
  }

  Future<void> _comenzar() async {
    setState(() {
      _fase = _Fase.buscando;
      _motivo = 'preguntando al bridge…';
    });
    try {
      final instalado = widget.instalado ?? await widget.nativo.versionCode();
      final permiso = await widget.nativo.puedeInstalar();
      final v = await widget.repo.versionApk(instalado: instalado, hayPermiso: permiso);
      if (!mounted) return;
      setState(() {
        _instalado = instalado;
        _v = v;
        _llego = true;
        _fase = _Fase.buscando;
        _motivo = v.estado;
      });
    } on Object catch (e) {
      // Sin esto el diálogo se queda mudo: la excepción sube, el `setState` no
      // se llama, y la pantalla queda en «preguntando» sin ninguna pista. Un
      // fallo que no se enseña no se puede arreglar.
      if (!mounted) return;
      setState(() {
        _fase = _Fase.buscando;
        _motivo = 'no se pudo comprobar la actualización: $e';
      });
    }
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

  /// Lleva a la persona a donde se concede el permiso.
  ///
  /// ## Por qué aquí no se avisa «ya está» y se calla
  /// No se avisa porque al volver, `didChangeAppLifecycleState` vuelve a
  /// preguntar y el diálogo enseña el resultado solo. Si se escribiera «vuelve a
  /// pulsar» habría que inventarse un botón que no existe.
  ///
  /// Lo que sí hace falta es **tragarse el fallo**. Se dio de verdad: en un
  /// dispositivo sin pantalla de Ajustes el botón no hacía nada, y el motivo
  /// —«no hay ninguna pantalla donde concederlo»— se perdía en una excepción sin
  /// dueño que nadie iba a leer. Un botón que no hace nada es peor que un botón
  /// que dice que no puede.
  Future<void> _abrirPermiso() async {
    try {
      final motivo = await widget.nativo.abrirPermiso();
      if (motivo == null || motivo.isEmpty) return;
      if (!mounted) return;
      setState(() => _nota = motivo);
    } on Object catch (error) {
      if (!mounted) return;
      setState(() => _nota = 'no se pudo abrir Ajustes: $error');
    }
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
            _linea('tienes', _instalado == null || _instalado! <= 0
                ? 'lo que hay instalada'
                : 'versión $_instalado'),
            _linea('el bridge tiene',
                !_llego
                    ? '— sin respuesta'
                    : _v.versionCode > 0
                        ? '${_v.versionCode} (${_v.versionName})'
                        : 'nada que servir'),
            const SizedBox(height: 12),
            Text(_nota.isNotEmpty ? _nota : _motivo,
                style: TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 11.5,
                    // La nota se pinta distinta porque no es lo que dijo el
                    // bridge: es lo que pasó aquí. Del mismo color se leía como
                    // parte de la respuesta del servidor.
                    color: _nota.isNotEmpty ? AegisPalette.brand : AegisPalette.fgDim)),
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