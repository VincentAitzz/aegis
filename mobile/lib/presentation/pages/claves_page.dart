/// La bóveda: los códigos de tus cuentas.
///
/// ## Por qué vive en el móvil y no la calcula el bridge
/// Es `docs/decisiones/003`, resumido: una semilla en el bridge acaba en la
/// traza del autopilot, en el log de telemetría y en la memoria de Chroma, y
/// las tres son cosas que se pueden leer. Aquí no sale de este proceso.
///
/// ## Por qué esta pantalla funciona con el bridge caído
/// Porque es lo único que importa en un autenticador: si el código depende de
/// que la casa esté encendida, no sirve para el momento en que más lo necesitas,
/// que es cuando la wifi no va. El código se calcula entero en el móvil y no
/// hay una sola llamada a la red en este fichero.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth/boveda.dart';
import '../../core/auth/copia.dart';
import '../../core/auth/fichero_copia.dart';
import '../../core/auth/otpauth.dart';
import '../../core/theme/aegis_palette.dart';
import '../../core/widgets/aegis_scaffold.dart';
import '../providers/boveda_providers.dart';
import '../widgets/anillo_cuenta.dart';
import 'escaner_qr.dart';

/// Cuánto tarda el código copiado en desaparecer del portapapeles.
///
/// ## Por qué hay que hacerlo
/// Un código de TOTP vale durante 30 segundos y luego es basura. Copiado a un
/// portapapeles que nadie limpia, en cambio, **queda ahí para siempre**, y el
/// siguiente sitio donde se pega es una app de notas o un chat. No es un
/// riesgo teórico: es el comportamiento por defecto de todos los autenticadores
/// que no hacen esto.
const _datosEnPortapapeles = Duration(seconds: 30);

class ClavesPage extends ConsumerStatefulWidget {
  const ClavesPage({super.key});

  @override
  ConsumerState<ClavesPage> createState() => _ClavesPageState();
}

class _ClavesPageState extends ConsumerState<ClavesPage> {
  Timer? _limpiezaPortapapeles;

  @override
  void dispose() {
    _limpiezaPortapapeles?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final boveda = ref.watch(bovedaProvider);
    final ahora = ref.watch(relojUIProvider);

    return AegisScaffold(
      appBar: AppBar(
        title: const Text('Claves'),
        backgroundColor: Colors.transparent,
        // Sin cámara ni red en la app bar: añadir una cuenta se hace con el
        // botón de abajo, que es donde se espera encontrarlo y donde el motivo
        // («escanear un QR») tiene sitio para explicarse.
        actions: [
          IconButton(
            onPressed: () => _menu(),
            icon: const Icon(Icons.more_vert, size: 18),
            tooltip: 'Más',
          ),
        ],
      ),
      body: boveda.when(
        loading: () => const Center(
          child: CircularProgressIndicator(strokeWidth: 2),
        ),
        error: (e, _) => _BovedaRota(alReintentar: () {
          ref.invalidate(bovedaProvider);
        }),
        // La corrupción llega **dentro del valor**, no como excepción. Ver
        // `Boveda.corrupta`: tiene que ser un estado que sobreviva a cada
        // reconstrucción, o la pantalla volvería a pintarse como si no tuvieras
        // nada y un «añadir» por debajo se comería lo que queda.
        data: (b) => b.intocable
            ? _BovedaRota(
                demasiadoNueva: b.demasiadoNueva,
                alReintentar: () => ref.invalidate(bovedaProvider),
              )
            : _cuerpo(context, b, ahora),
      ),
    );
  }

  Widget _cuerpo(BuildContext context, Boveda b, DateTime ahora) {
    if (b.vacia) return _vacia(context);

    // La cuenta que toca a continuación, arriba: la que está más cerca de
    // caducar va primero, porque es la que se va a usar. Ordenar por caducidad
    // y no por orden de alta hace que la de arriba sea siempre la urgente.
    final cuentas = [...b.cuentas]
      ..sort((x, y) => x.segundosRestantes(ahora)
          .compareTo(y.segundosRestantes(ahora)));

    return Column(
      children: [
        Expanded(
          child: ListView.separated(
            padding: const EdgeInsets.fromLTRB(14, 8, 14, 14),
            itemCount: cuentas.length,
            separatorBuilder: (_, _) => const SizedBox(height: 8),
            itemBuilder: (_, i) => _FichaCuenta(
              cuenta: cuentas[i],
              ahora: ahora,
              sinGastar: b.sinGastar(cuentas[i].id),
              alCopiar: () => _copiar(cuentas[i]),
              alBorrar: () => _confirmarBorrar(cuentas[i]),
              alRenombrar: () => _renombrar(cuentas[i]),
              alCanjear: () => _canjear(),
            ),
          ),
        ),
        _BarraAcciones(
          alEscanear: () => _escanear,
          alTeclear: () => _teclar,
        ),
      ],
    );
  }

  Widget _vacia(BuildContext context) {
    return Column(
      children: [
        Expanded(
          child: Center(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 34),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.key_outlined,
                      size: 34, color: AegisPalette.fgFaint),
                  const SizedBox(height: 16),
                  const Text(
                    'No hay cuentas todavía.',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontFamily: AegisPalette.mono,
                      fontSize: 13,
                      color: AegisPalette.fgDim,
                    ),
                  ),
                  const SizedBox(height: 10),
                  const Text(
                    'Escanea el QR que te da un servicio, o teclea la clave a '
                    'mano. Lo que guardes se queda en este móvil.',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontFamily: AegisPalette.mono,
                      fontSize: 11.5,
                      height: 1.5,
                      color: AegisPalette.fgFaint,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
        _BarraAcciones(
          alEscanear: () => _escanear,
          alTeclear: () => _teclar,
        ),
      ],
    );
  }

  // -- copiar ---------------------------------------------------------------

  Future<void> _copiar(Cuenta cuenta) async {
    final codigo = cuenta.codigo(ref.read(relojProvider)());
    await Clipboard.setData(ClipboardData(text: codigo));

    // El código se va del portapapeles solo. Ver [_datosEnPortapapeles].
    _limpiezaPortapapeles?.cancel();
    _limpiezaPortapapeles = Timer(_datosEnPortapapeles, () async {
      // Se **comprueba** antes de limpiar, y no se limpia a lo bruto.
      //
      // Sin comprobar, un timer que se disparase después de que el usuario
      // copiara otra cosa —un párrafo, una dirección— **borraría lo que acaba de
      // copiar**. Ese es el fallo de no mirar antes de escribir.
      //
      // Y se escribe vacío a propósito: en Android, un portapapeles vacío **no
      // se anuncia**, así que el código de hace 30 s desaparece del panel en vez
      // de quedarse como un hueco. El texto anterior decía lo contrario de lo
      // que hace el código, y un comentario que miente sobre su propia función
      // es peor que no tenerlo: hace que la línea de abajo parezca justificada.
      try {
        final actual = await Clipboard.getData(Clipboard.kTextPlain);
        if (actual?.text == codigo) {
          await Clipboard.setData(const ClipboardData(text: ''));
        }
      } on PlatformException {
        // Sin portapapeles no hay nada que limpiar. No es un fallo.
      }
    });

    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(
        'Código copiado. Se borra del portapapeles en 30 s.',
        style: const TextStyle(fontFamily: AegisPalette.mono, fontSize: 11.5),
      ),
      backgroundColor: AegisPalette.bg2,
      duration: const Duration(seconds: 3),
    ));
  }

  // -- añadir ---------------------------------------------------------------

  /// Lo común a escanear y teclear: **enseñar lo que se va a guardar** y
  /// pedir confirmación.
  ///
  /// ## Por qué se enseña antes de guardar
  /// Un QR mal leído —una cuenta del servicio equivocado, una etiqueta
  /// partida— se guarda y no se ve hasta que hace falta. Y guardar es lo
  /// irreversible: borrar después funciona, pero mientras tanto la cuenta
  /// buena está en un sitio que no es el suyo.
  Future<void> _confirmarAlta(CuentaQr qr) async {
    final codigos = await ref.read(bovedaProvider.notifier).anadir(qr);
    if (!mounted) return;

    if (codigos == null) {
      _error('No se ha guardado nada: la bóveda está dañada.');
      return;
    }
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      builder: (_) => _DialogoCodigosRecuperacion(
        titulo: qr.titulo,
        codigos: codigos,
      ),
    );
  }

  Future<void> _escanear() async {
    final uri = await Navigator.of(context).push<String>(
      MaterialPageRoute(builder: (_) => const EscanerQrPage()),
    );
    if (uri == null || !mounted) return;
    final qr = await _parsear(uri);
    if (qr != null) await _confirmarAlta(qr);
  }

  Future<void> _teclar() async {
    final uri = await showDialog<String>(
      context: context,
      builder: (_) => const DialogoTeclaManual(),
    );
    if (uri == null || !mounted) return;
    final qr = await _parsear(uri);
    if (qr != null) await _confirmarAlta(qr);
  }

  /// Convierte el texto en una cuenta, o explica por qué no puede.
  Future<CuentaQr?> _parsear(String uri) async {
    try {
      return leerOtpauth(uri);
    } on ErrorOtpauth catch (e) {
      _error(e.motivo);
      return null;
    }
  }

  // -- canjear --------------------------------------------------------------

  Future<void> _canjear() async {
    final codigo = await showDialog<String>(
      context: context,
      builder: (_) => const DialogoCanje(),
    );
    if (codigo == null || !mounted) return;

    final id = await ref.read(bovedaProvider.notifier).canjear(codigo);
    if (!mounted) return;

    final boveda = _bovedaActual(ref);
    final cuenta = boveda?.cuentas.where((c) => c.id == id).firstOrNull;

    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(
        id == null
            ? 'Ese código no vale para ninguna cuenta.'
            : 'Codigo canjeado en ${cuenta?.titulo ?? id}.',
        style: const TextStyle(fontFamily: AegisPalette.mono, fontSize: 11.5),
      ),
      backgroundColor: AegisPalette.bg2,
    ));
  }

  // -- renombrar y borrar ----------------------------------------------------

  Future<void> _renombrar(Cuenta cuenta) async {
    final controlador = TextEditingController(text: cuenta.etiqueta);
    final nuevo = await showDialog<String>(
      context: context,
      builder: (_) => _DialogoTexto(
        titulo: 'Cambiar el nombre',
        etiqueta: 'Lo que ves en la lista',
        controlador: controlador,
      ),
    );
    controlador.dispose();
    if (nuevo == null || nuevo.trim().isEmpty || !mounted) return;
    await ref.read(bovedaProvider.notifier).renombrar(cuenta.id, nuevo);
  }

  Future<void> _confirmarBorrar(Cuenta cuenta) async {
    // Pide confirmación y **dice qué se pierde**. Un «¿Seguro?» a secas deja
    // sin saber si además se van los códigos de recuperación.
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AegisPalette.bg2,
        title: const Text('¿Borrar la cuenta?',
            style: TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 15,
                color: AegisPalette.fg)),
        content: Text(
          'Se borra «${cuenta.titulo}» y sus códigos de recuperación.\n\n'
          'Si el servicio no tiene otro acceso, con esto ya no entras.',
          style: const TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 11.5,
              height: 1.5,
              color: AegisPalette.fgDim),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancelar'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            style: TextButton.styleFrom(foregroundColor: AegisPalette.danger),
            child: const Text('Borrar'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    await ref.read(bovedaProvider.notifier).borrar(cuenta.id);
  }

  // -- copia de seguridad ----------------------------------------------------

  Future<void> _menu() async {
    final accion = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: AegisPalette.bg1,
      builder: (_) => const _HojaMenu(),
    );
    if (!mounted) return;
    switch (accion) {
      case 'exportar':
        await _exportar();
      case 'importar':
        await _importar();
      case 'canjear':
        await _canjear();
    }
  }

  Future<void> _exportar() async {
    final boveda = _bovedaActual(ref);
    if (boveda == null || boveda.vacia) return;

    final contrasena = await showDialog<String>(
      context: context,
      builder: (_) => const DialogoContrasena(
        titulo: 'Contraseña de la copia',
        explicacion: 'Cifra el fichero. Sin ella no se puede abrir, ni '
            'siquiera desde Aegis. No se guarda en ningún sitio.\n\n'
            'Después Aegis te deja elegir **la carpeta**: ahí decides dónde '
            'queda, y Aegis no lo sube a ningún sitio por su cuenta.',
      ),
    );
    if (contrasena == null || contrasena.isEmpty || !mounted) return;

    final b = _bovedaActual(ref);
    if (b == null) return;
    final contenido = await cifrarBoveda(b, contrasena);
    if (!mounted) return;

    // Primero una copia local, que es lo que salva si la bóveda se daña **en
    // este móvil**. Silenciosa: no pide nada y no sale de aquí.
    await guardarCopia(contenido);
    if (!mounted) return;

    // Y luego la que sale, que es la que salva si pierdes el móvil. Con SAF,
    // porque la persona elige dónde y Android 11 no deja tocar `Android/data/`
    // desde fuera: antes el fichero se escribía donde nadie podía llegar, que
    // es una función de exportar que parece funcionar y no sirve para nada.
    final motivo = await ref
        .read(copiaNativaProvider)
        .exportar(contenido, nombreCopiaConFecha());
    if (!mounted) return;

    if (motivo != null) {
      _error('No se ha guardado la copia: $motivo');
      return;
    }
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text(
          'Copiada donde elegiste. Aegis no la ha subido a ningún sitio.',
          style: TextStyle(fontFamily: AegisPalette.mono, fontSize: 11.5),
        ),
        backgroundColor: AegisPalette.bg2,
      ),
    );
  }

  Future<void> _importar() async {
    // Con SAF primero: es donde está la copia que alguien se llevó. La local
    // de este móvil es el segundo intento, y solo si la primera se cancela.
    var contenido = await ref.read(copiaNativaProvider).importar();
    contenido ??= await leerCopia();
    if (contenido == null || !mounted) return;

    final contrasena = await showDialog<String>(
      context: context,
      builder: (_) => const DialogoContrasena(
        titulo: 'Contraseña de la copia',
        explicacion: 'Para descifrarla. No se guarda.',
      ),
    );
    if (contrasena == null || !mounted) return;

    Boveda importada;
    try {
      importada = await abrirCopia(contenido, contrasena);
    } on ErrorCopia catch (e) {
      if (mounted) _error(e.motivo);
      return;
    }

    // Importar **reemplaza**: no fusiona. Fusionar dejaría cuentas con el mismo
    // id en dos sitios y no se sabría cuál está bien.
    if (!mounted) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AegisPalette.bg2,
        title: const Text('¿Reemplazar la bóveda?',
            style: TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 15,
                color: AegisPalette.fg)),
        content: Text(
          'La copia tiene ${importada.cuentas.length} cuenta'
          '${importada.cuentas.length == 1 ? '' : 's'}.\n\n'
          'Se sustituye lo que hay ahora. Si no has exportado antes, esto es '
          'irrecuperable.',
          style: const TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 11.5,
              height: 1.5,
              color: AegisPalette.fgDim),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancelar')),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            style: TextButton.styleFrom(foregroundColor: AegisPalette.danger),
            child: const Text('Reemplazar'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;

    await ref.read(almacenBovedaProvider).escribir(importada);
    await ref.read(bovedaProvider.notifier).recargar();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text('Importadas ${importada.cuentas.length} cuentas',
          style: const TextStyle(
              fontFamily: AegisPalette.mono, fontSize: 11.5)),
      backgroundColor: AegisPalette.bg2,
    ));
  }

  /// La bóveda ya cargada, o `null` si todavía no está.
  ///
  /// `valueOrNull` no existe en Riverpod 3, y `requireValue` sobre un estado
  /// en carga lanza. El switch es lo que dice «si la tengo, úsala».
  static Boveda? _bovedaActual(WidgetRef ref) => switch (ref.read(bovedaProvider)) {
        AsyncData(:final value) => value,
        _ => null,
      };

  void _error(String mensaje) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(mensaje,
          style: const TextStyle(
              fontFamily: AegisPalette.mono, fontSize: 11.5)),
      backgroundColor: AegisPalette.bg2,
    ));
  }
}

// -- ficha de una cuenta ------------------------------------------------------

class _FichaCuenta extends StatelessWidget {
  const _FichaCuenta({
    required this.cuenta,
    required this.ahora,
    required this.sinGastar,
    required this.alCopiar,
    required this.alBorrar,
    required this.alRenombrar,
    required this.alCanjear,
  });

  final Cuenta cuenta;
  final DateTime ahora;
  final int sinGastar;
  final VoidCallback alCopiar;
  final VoidCallback alBorrar;
  final VoidCallback alRenombrar;
  final VoidCallback alCanjear;

  @override
  Widget build(BuildContext context) {
    final fraccion = cuenta.fraccionRestante(ahora);
    final codigo = cuenta.codigo(ahora);

    return InkWell(
      onTap: alCopiar,
      borderRadius: BorderRadius.circular(7),
      child: Container(
        padding: const EdgeInsets.fromLTRB(13, 12, 13, 12),
        decoration: BoxDecoration(
          color: AegisPalette.bg1,
          borderRadius: BorderRadius.circular(7),
          border: Border.all(color: AegisPalette.line),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        cuenta.emisor.isEmpty ? cuenta.etiqueta : cuenta.emisor,
                        style: const TextStyle(
                          fontFamily: AegisPalette.display,
                          fontSize: 13,
                          letterSpacing: 0.6,
                          color: AegisPalette.fg,
                        ),
                      ),
                      if (cuenta.etiqueta.isNotEmpty &&
                          cuenta.emisor.isNotEmpty)
                        Text(
                          cuenta.etiqueta,
                          style: const TextStyle(
                            fontFamily: AegisPalette.mono,
                            fontSize: 10.5,
                            color: AegisPalette.fgFaint,
                          ),
                        ),
                    ],
                  ),
                ),
                AnilloCuentaAtras(
                  fraccion: fraccion,
                  // El periodo va desde la cuenta: una de 60 segundos no puede
                  // enseñar «30» en el centro, y el widget no puede saberlo.
                  periodo: cuenta.periodo,
                  color: AnilloCuentaAtras.colorPara(fraccion),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  child: CodigoGrande(codigo: codigo, tamanio: 30),
                ),
                _Icono(
                  icono: Icons.content_copy_rounded,
                  onTap: alCopiar,
                  tooltip: 'Copiar',
                ),
                const SizedBox(width: 4),
                _Icono(
                  icono: Icons.edit_outlined,
                  onTap: alRenombrar,
                  tooltip: 'Cambiar el nombre',
                ),
                const SizedBox(width: 4),
                _Icono(
                  icono: Icons.delete_outline,
                  onTap: alBorrar,
                  tooltip: 'Borrar',
                  color: AegisPalette.danger,
                ),
              ],
            ),
            if (sinGastar < 10) ...[
              const SizedBox(height: 9),
              Row(
                children: [
                  Icon(
                    sinGastar == 0
                        ? Icons.error_outline
                        : Icons.info_outline,
                    size: 12,
                    color: sinGastar == 0
                        ? AegisPalette.danger
                        : AegisPalette.warn,
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      sinGastar == 0
                          ? 'No te queda ningún código de recuperación.'
                          : 'Te quedan $sinGastar códigos de recuperación.',
                      style: TextStyle(
                        fontFamily: AegisPalette.mono,
                        fontSize: 10,
                        color: sinGastar == 0
                            ? AegisPalette.danger
                            : AegisPalette.warn,
                      ),
                    ),
                  ),
                  if (sinGastar > 0)
                    GestureDetector(
                      onTap: alCanjear,
                      child: const Text(
                        'usar',
                        style: TextStyle(
                          fontFamily: AegisPalette.mono,
                          fontSize: 10,
                          decoration: TextDecoration.underline,
                          color: AegisPalette.warn,
                        ),
                      ),
                    ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _Icono extends StatelessWidget {
  const _Icono({
    required this.icono,
    required this.onTap,
    required this.tooltip,
    this.color,
  });

  final IconData icono;
  final VoidCallback onTap;
  final String tooltip;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(5),
        child: Padding(
          padding: const EdgeInsets.all(5),
          child: Icon(icono, size: 15, color: color ?? AegisPalette.fgDim),
        ),
      ),
    );
  }
}

class _BarraAcciones extends StatelessWidget {
  const _BarraAcciones({required this.alEscanear, required this.alTeclear});

  final VoidCallback alEscanear;
  final VoidCallback alTeclear;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 10, 14, 16),
      decoration: const BoxDecoration(
        border: Border(top: BorderSide(color: AegisPalette.line)),
      ),
      child: Row(
        children: [
          Expanded(
            child: FilledButton.icon(
              onPressed: alEscanear,
              icon: const Icon(Icons.qr_code_scanner_rounded, size: 16),
              label: const Text('Escanear'),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: OutlinedButton.icon(
              onPressed: alTeclear,
              icon: const Icon(Icons.keyboard_alt_outlined, size: 15),
              label: const Text('Teclear'),
            ),
          ),
        ],
      ),
    );
  }
}

/// La bóveda guardada no se puede leer.
///
/// ## Por qué esta pantalla y no un SnackBar
/// Un snackbar se va solo y se tapa. Si la bóveda está corrupta, alguien puede
/// tocar cualquier cosa y sobrescribirla con una lista vacía, y entonces ya no
/// hay ni copia ni aviso. Esta pantalla no se va sola y dice qué hacer.
class _BovedaRota extends StatelessWidget {
  const _BovedaRota({required this.alReintentar, this.demasiadoNueva = false});

  final VoidCallback alReintentar;

  /// Lo guardado es más nuevo que la app. El consejo es el contrario: aquí no
  /// hay que.iterator, hay que **actualizar**.
  final bool demasiadoNueva;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 30),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.lock_outline,
                size: 32, color: AegisPalette.danger),
            const SizedBox(height: 16),
            Text(
              demasiadoNueva
                  ? 'Lo guardado es más nuevo que esta app.'
                  : 'La bóveda no se puede leer.',
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 13,
                color: AegisPalette.fg,
              ),
            ),
            const SizedBox(height: 10),
            Text(
              demasiadoNueva
                  ? 'No se ha tocado nada y no hay que tocar nada. Aegis está '
                      'viejo para lo que tienes guardado: actualízalo y se '
                      'leerá solo.'
                  : 'No se ha tocado nada. Si importaste una copia, vuelve a '
                      'importarla; y no añadas cuentas hasta que esto se '
                      'resuelva, porque eso sobrescribiría lo que queda.',
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 11.5,
                height: 1.5,
                color: AegisPalette.fgDim,
              ),
            ),
            const SizedBox(height: 18),
            OutlinedButton.icon(
              onPressed: alReintentar,
              icon: const Icon(Icons.refresh, size: 15),
              label: const Text('Reintentar'),
            ),
          ],
        ),
      ),
    );
  }
}

class _HojaMenu extends StatelessWidget {
  const _HojaMenu();

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          _Item(
            icono: Icons.file_upload_outlined,
            texto: 'Exportar copia cifrada',
            onTap: () => Navigator.pop(context, 'exportar'),
          ),
          _Item(
            icono: Icons.file_download_outlined,
            texto: 'Importar copia',
            onTap: () => Navigator.pop(context, 'importar'),
          ),
          _Item(
            icono: Icons.vpn_key_outlined,
            texto: 'Usar un código de recuperación',
            onTap: () => Navigator.pop(context, 'canjear'),
          ),
          const SizedBox(height: 8),
        ],
      ),
    );
  }
}

class _Item extends StatelessWidget {
  const _Item({required this.icono, required this.texto, required this.onTap});

  final IconData icono;
  final String texto;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: Icon(icono, size: 18, color: AegisPalette.fgDim),
      title: Text(texto,
          style: const TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 12,
              color: AegisPalette.fg)),
      onTap: onTap,
      dense: true,
    );
  }
}

/// Los códigos de recuperación, la **única** vez que se ven.
///
/// ## Por qué un diálogo que no se cierra solo
/// Porque si se cierra y después los necesitas, ya no están: se guardaron
/// hasheados, que es lo que se decidió. Nadie va a leer un texto de 10 códigos
/// la primera vez que aparece, y por eso el botón de «los he guardado» está
/// debajo y dice lo que ha pasado.
class _DialogoCodigosRecuperacion extends StatelessWidget {
  const _DialogoCodigosRecuperacion({required this.titulo, required this.codigos});

  final String titulo;
  final List<String> codigos;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: AegisPalette.bg2,
      title: Text('Códigos de recuperación',
          style: const TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 15,
              color: AegisPalette.fg)),
      content: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            // ## Por qué el texto dice lo que dice, y no lo que se querria
            //
            // Antes aquí ponía «son lo único que queda si pierdes este móvil»,
            // y es **falso**: canjear un código marca el hash como gastado y ya.
            // No devuelve el acceso a nada, no reabre la cuenta y no restaura
            // nada. Es una manera de llevar la cuenta de cuántos códigos quedan
            // sin usar, que es otra cosa.
            //
            // Es peor que no prometer: alguien que pierde el móvil lee esto,
            // lo toma por la red de seguridad, **no guarda los códigos de
            // GitHub** —que son los que sí devuelven el acceso— y descubre el
            // problema cuando ya no hay nada que hacer.
            //
            // Así que el texto dice las tres cosas que importan: que son de
            // Aegis, que no devuelven el acceso al servicio, y que para eso
            // hacen falta los del propio servicio.
            Text(
              'Estos son de Aegis, de «$titulo». Cuentan cuántos te quedan, '
              'pero **no** devuelven el acceso a nada: canjear uno solo lo marca '
              'como gastado.\n\n'
              'Si pierdes este móvil, lo que te deja entrar en el servicio son '
              'los códigos de recuperación que te dio **él**. Guárdalos antes '
              'de que Aegis sea tu único sitio.\n\n'
              'Aegis solo guarda la huella de estos. Escríbelos si los quieres, '
              'pero no cuentan como red de seguridad.',
              style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 11,
                height: 1.5,
                color: AegisPalette.fgDim,
              ),
            ),
            const SizedBox(height: 14),
            Container(
              padding: const EdgeInsets.all(11),
              decoration: BoxDecoration(
                color: AegisPalette.bg0,
                borderRadius: BorderRadius.circular(5),
                border: Border.all(color: AegisPalette.line),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  for (final c in codigos)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 2),
                      child: Text(c,
                          style: const TextStyle(
                            fontFamily: AegisPalette.mono,
                            fontSize: 13,
                            letterSpacing: 1.2,
                            color: AegisPalette.fg,
                          )),
                    ),
                ],
              ),
            ),
            const SizedBox(height: 12),
            const Text(
              'No se pueden volver a enseñar.',
              style: TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 10.5,
                color: AegisPalette.warn,
              ),
            ),
          ],
        ),
      ),
      actions: [
        FilledButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Los he guardado'),
        ),
      ],
    );
  }
}

/// Teclear el enlace o la clave a mano.
///
/// ## Por qué acepta las dos cosas
/// Porque hay servicios que no dan QR —algunos de correo, casi todos los
/// bancos por teléfono— y para esos la clave se teclea. Y porque la cámara
/// falla, o no la hay, o no la quieres.
class DialogoTeclaManual extends StatefulWidget {
  const DialogoTeclaManual({super.key});

  @override
  State<DialogoTeclaManual> createState() => _DialogoTeclaManualState();
}

class _DialogoTeclaManualState extends State<DialogoTeclaManual> {
  final _controlador = TextEditingController();

  @override
  void dispose() {
    _controlador.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: AegisPalette.bg2,
      title: const Text('Añadir a mano',
          style: TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 15,
              color: AegisPalette.fg)),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Pega el enlace otpauth:// entero, o solo la clave si el servicio '
            'solo te dio la clave.',
            style: TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 11,
              height: 1.5,
              color: AegisPalette.fgDim,
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _controlador,
            autofocus: true,
            maxLines: 3,
            minLines: 1,
            style: const TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 12,
              color: AegisPalette.fg,
            ),
            decoration: InputDecoration(
              isDense: true,
              hintText: 'otpauth://totp/…',
              hintStyle: const TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 12,
                  color: AegisPalette.fgFaint),
              border: const OutlineInputBorder(),
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancelar')),
        FilledButton(
          onPressed: () {
            final texto = _controlador.text.trim();
            if (texto.isNotEmpty) Navigator.pop(context, texto);
          },
          child: const Text('Añadir'),
        ),
      ],
    );
  }
}

class DialogoCanje extends StatefulWidget {
  const DialogoCanje({super.key});

  @override
  State<DialogoCanje> createState() => _DialogoCanjeState();
}

class _DialogoCanjeState extends State<DialogoCanje> {
  final _controlador = TextEditingController();

  @override
  void dispose() {
    _controlador.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: AegisPalette.bg2,
      title: const Text('Código de recuperación',
          style: TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 15,
              color: AegisPalette.fg)),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Uno de los que guardaste al añadir la cuenta. Se gasta al usarlo.',
            style: TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 11,
              height: 1.5,
              color: AegisPalette.fgDim,
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _controlador,
            autofocus: true,
            textCapitalization: TextCapitalization.characters,
            style: const TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 15,
              letterSpacing: 1.2,
              color: AegisPalette.fg,
            ),
            decoration: const InputDecoration(
              isDense: true,
              hintText: 'XXXX-XXXX-XXXX',
              border: OutlineInputBorder(),
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancelar')),
        FilledButton(
          onPressed: () {
            final texto = _controlador.text.trim();
            if (texto.isNotEmpty) Navigator.pop(context, texto);
          },
          child: const Text('Canjear'),
        ),
      ],
    );
  }
}

class DialogoContrasena extends StatefulWidget {
  const DialogoContrasena({
    super.key,
    required this.titulo,
    required this.explicacion,
  });

  final String titulo;
  final String explicacion;

  @override
  State<DialogoContrasena> createState() => _DialogoContrasenaState();
}

class _DialogoContrasenaState extends State<DialogoContrasena> {
  final _controlador = TextEditingController();
  bool _visible = false;

  @override
  void dispose() {
    _controlador.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: AegisPalette.bg2,
      title: Text(widget.titulo,
          style: const TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 15,
              color: AegisPalette.fg)),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            widget.explicacion,
            style: const TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 11,
              height: 1.5,
              color: AegisPalette.fgDim,
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _controlador,
            autofocus: true,
            obscureText: !_visible,
            style: const TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 13,
              color: AegisPalette.fg,
            ),
            decoration: InputDecoration(
              isDense: true,
              suffixIcon: IconButton(
                onPressed: () => setState(() => _visible = !_visible),
                icon: Icon(
                  _visible ? Icons.visibility_off_outlined : Icons.visibility_outlined,
                  size: 16,
                ),
              ),
              border: const OutlineInputBorder(),
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancelar')),
        FilledButton(
          onPressed: () {
            final texto = _controlador.text;
            if (texto.isNotEmpty) Navigator.pop(context, texto);
          },
          child: const Text('Continuar'),
        ),
      ],
    );
  }
}

class _DialogoTexto extends StatelessWidget {
  const _DialogoTexto({
    required this.titulo,
    required this.etiqueta,
    required this.controlador,
  });

  final String titulo;
  final String etiqueta;
  final TextEditingController controlador;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: AegisPalette.bg2,
      title: Text(titulo,
          style: const TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 15,
              color: AegisPalette.fg)),
      content: TextField(
        controller: controlador,
        autofocus: true,
        style: const TextStyle(
          fontFamily: AegisPalette.mono,
          fontSize: 13,
          color: AegisPalette.fg,
        ),
        decoration: InputDecoration(
          isDense: true,
          labelText: etiqueta,
          labelStyle: const TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 11,
              color: AegisPalette.fgFaint),
          border: const OutlineInputBorder(),
        ),
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancelar')),
        FilledButton(
          onPressed: () => Navigator.pop(context, controlador.text),
          child: const Text('Guardar'),
        ),
      ],
    );
  }
}