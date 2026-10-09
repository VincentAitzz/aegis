/// La cámara, y solo mientras se está en esta pantalla.
///
/// ## Por qué la cámara no sale de aquí
/// `docs/vision.md` deja las cámaras para F4 y dice —con razón— que grabar
/// personas en tu casa es una decisión de privacidad, no de ingeniería. Esto no
/// es eso: es leer un código **en memoria y descartarlo**, sin escribir ninguna
/// imagen y sin enviarla a ninguna parte. Pero aun así es la primera vez que
/// Aegis pide la cámara, así que:
///
/// - El permiso se pide **en el momento**, al abrir esta pantalla, no al
///   instalar. Un permiso pedido en la instalación se concede sin leerlo.
/// - Se explica qué pasa con la imagen antes de que salga el diálogo del
///   sistema, porque el diálogo del sistema dice «permite que Aegis use la
///   cámara» y no dice para qué.
/// - El preview se para en cuanto la app va a segundo plano. Sin esto, la
///   cámara sigue abierta con la pantalla apagada, que es justo el fallo que
///   señala la propia documentación del paquete.
///
/// ## Por qué ML Kit empaquetado
/// Porque la alternativa descarga el modelo desde Play Services al primer uso,
/// y un autenticador que necesita red para leer un QR no funciona sin cobertura.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../../core/theme/aegis_palette.dart';
import '../../core/widgets/aegis_scaffold.dart';

class EscanerQrPage extends StatefulWidget {
  const EscanerQrPage({super.key});

  @override
  State<EscanerQrPage> createState() => _EscanerQrPageState();
}

/// Si el texto escaneado es un enlace de autenticación, y cuál es.
///
/// ## Por qué está fuera del widget
/// Porque la decisión «esto es o no un `otpauth://`» se puede equivocar, y
/// equivocándose de una forma **irreversible para la sesión**: si se marca el
/// escáner como resuelto con un QR ajeno, ya no vuelve a escuchar hasta que se
/// cierre la pantalla. Eso pasó, y no lo cazó ningún test porque la lógica
/// estaba dentro de un método de `State`, donde probarla exige montar la cámara.
///
/// Como función pura, el caso que rompió la app es un `expect` de tres líneas.
///
/// ## Por qué solo mira el prefijo
/// Porque este es un filtro de **candidatos**: decide si el QR se pasa al
/// parser, que es quien dice si la cuenta es válida y por qué. Si el filtro
/// fuera también un validador, un `otpauth://` raro no se vería nunca y la
/// pantalla se quedaría esperando un QR que el usuario tiene delante.
///
/// Devuelve `null` para todo lo que no sea, y el `null` **no** es un error:
/// el escáner sigue mirando.
String? valorDeQr(String? bruto) {
  if (bruto == null) return null;
  final valor = bruto.trim();
  if (valor.isEmpty) return null;
  if (!valor.toLowerCase().startsWith('otpauth://')) return null;
  return valor;
}

class _EscanerQrPageState extends State<EscanerQrPage>
    with WidgetsBindingObserver {
  final MobileScannerController _controlador = MobileScannerController(
    detectionSpeed: DetectionSpeed.normal,
    // Un QR de autenticación es un QR, no un código de barras: se formatea
    // `formats: [BarcodeFormat.qrCode]` para no intentar decodificar los
    // códigos de barras de un producto que alguien tiene delante.
    formats: const [BarcodeFormat.qrCode],
  );

  StreamSubscription<BarcodeCapture>? _suscripcion;
  bool _resuelto = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _suscripcion = _controlador.barcodes.listen(_alDetectar);
  }

  @override
  void dispose() {
    // Las tres cosas van, y en este orden: quitar el observer antes de que
    // Flutter lo llame a un `dispose` que ya no tiene sentido, y parar el
    // preview explícitamente porque `dispose` del controlador es asíncrono y
    // la app puede ir a segundo plano antes de que termine.
    WidgetsBinding.instance.removeObserver(this);
    _suscripcion?.cancel();
    unawaited(_controlador.dispose());
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState estado) {
    // Sin esto la cámara sigue abierta en segundo plano. Es el fallo que la
    // documentación del paquete dice explícitamente que no hay que cometer.
    if (!_controlador.value.hasCameraPermission) return;
    switch (estado) {
      case AppLifecycleState.resumed:
        _suscripcion ??= _controlador.barcodes.listen(_alDetectar);
        unawaited(_controlador.start());
      case AppLifecycleState.inactive:
      case AppLifecycleState.paused:
      case AppLifecycleState.hidden:
      case AppLifecycleState.detached:
        unawaited(_suscripcion?.cancel());
        _suscripcion = null;
        unawaited(_controlador.stop());
    }
  }

  void _alDetectar(BarcodeCapture captura) {
    if (_resuelto) return;
    for (final barcode in captura.barcodes) {
      final valor = valorDeQr(barcode.rawValue);
      if (valor == null) continue;
      // **Aquí** se marca como resuelto, y no antes. Marcarlo antes hacía que un
      // QR que no era de autenticación —un producto, una URL— dejara el escáner
      // **permanentemente sordo**: el flag quedaba puesto, el `continue` salía
      // del bucle y el `if (_resuelto) return` de arriba descartaba todos los
      // detections siguientes. Un solo QR ajeno y había que cerrar y reabrir la
      // pantalla.
      //
      // El bug era posible porque la decisión estaba metida en un método de
      // widget, donde no hay forma de probarla. Ahora está en
      // [valorDeQr], que es pura y tiene test.
      _resuelto = true;
      unawaited(_controlador.stop());
      if (mounted) Navigator.pop(context, valor);
      return;
    }
  }

  Future<void> _pegar() async {
    final datos = await Clipboard.getData(Clipboard.kTextPlain);
    // La **misma** función que decide lo del escáner. Tener las dos decisiones
    // por separado es como acaban discrepando: una acepta algo que la otra
    // rechaza, y el usuario no entiende por qué pegar funciona y escanear no.
    final texto = valorDeQr(datos?.text);
    if (texto == null) {
      _error('Eso no es un enlace otpauth://.');
      return;
    }
    if (!mounted) return;
    Navigator.pop(context, texto);
  }

  void _error(String mensaje) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(mensaje,
          style: const TextStyle(
              fontFamily: AegisPalette.mono, fontSize: 11.5)),
      backgroundColor: AegisPalette.bg2,
    ));
  }

  @override
  Widget build(BuildContext context) {
    return AegisScaffold(
      appBar: AppBar(
        title: const Text('Escanear'),
        backgroundColor: Colors.transparent,
        actions: [
          IconButton(
            onPressed: () => unawaited(_controlador.toggleTorch()),
            icon: const Icon(Icons.flashlight_on_outlined, size: 18),
            tooltip: 'Linterna',
          ),
        ],
      ),
      body: Stack(
        children: [
          MobileScanner(
            controller: _controlador,
            errorBuilder: (context, error) => _SinCamara(error: error),
          ),
          const _CuadroApuntado(),
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: Container(
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 26),
              decoration: const BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [Color(0x0007080B), Color(0xE607080B)],
                ),
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Text(
                    'La imagen no se guarda ni sale del móvil.',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontFamily: AegisPalette.mono,
                      fontSize: 10.5,
                      color: AegisPalette.fgDim,
                    ),
                  ),
                  const SizedBox(height: 12),
                  OutlinedButton.icon(
                    onPressed: _pegar,
                    icon: const Icon(Icons.content_paste_outlined, size: 15),
                    label: const Text('Pegar el enlace'),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// El marco, para saber dónde apuntar.
class _CuadroApuntado extends StatelessWidget {
  const _CuadroApuntado();

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: Center(
        child: Container(
          width: 230,
          height: 230,
          decoration: BoxDecoration(
            border: Border.all(color: AegisPalette.brand, width: 1.5),
            borderRadius: BorderRadius.circular(10),
          ),
        ),
      ),
    );
  }
}

/// Sin permiso, o sin cámara.
///
/// ## Por qué es una pantalla y no un snackbar
/// Un permiso denegado es una decisión del usuario que hay que poder cambiar,
/// y para eso hay que ir a Ajustes. Un «cámara no disponible» que desaparece en
/// tres segundos no deja hacer nada con esa información.
class _SinCamara extends StatelessWidget {
  const _SinCamara({required this.error});

  final MobileScannerException error;

  @override
  Widget build(BuildContext context) {
    final sinPermiso = error.errorCode ==
        MobileScannerErrorCode.permissionDenied;

    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 30),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              sinPermiso ? Icons.no_photography_outlined : Icons.videocam_off_outlined,
              size: 30,
              color: AegisPalette.fgFaint,
            ),
            const SizedBox(height: 14),
            Text(
              sinPermiso
                  ? 'Sin permiso para la cámara.'
                  : 'La cámara no está disponible.',
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 13,
                color: AegisPalette.fgDim,
              ),
            ),
            const SizedBox(height: 10),
            Text(
              sinPermiso
                  ? 'Se puede en Ajustes → Apps → Aegis → Permisos. O pega el '
                      'enlace desde la pantalla anterior.'
                  : 'Puedes pegar el enlace otpauth:// a mano.',
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 11,
                height: 1.5,
                color: AegisPalette.fgFaint,
              ),
            ),
          ],
        ),
      ),
    );
  }
}