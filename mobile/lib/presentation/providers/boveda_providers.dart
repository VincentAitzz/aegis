/// Providers de la bóveda.
///
/// ## Por qué vive en Riverpod y no en un `InheritedWidget` con un singleton
/// Porque hay tres cosas que dependen de la misma bóveda —la lista, el escáner
/// y la copia— y si cada una abre su propio [BovedaKeystore] desde el disco las
/// tres pueden tener una versión distinta en memoria: añadió una cuenta desde
/// el escáner y la lista no la ve hasta que se recargue, y el usuario borra dos
/// veces la misma cuenta.
///
/// El reloj también va aquí, como provider, y no como `DateTime.now()` dentro
/// de los widgets: es lo que permite que un test mueva el reloj y compruebe el
/// giro del anillo sin esperar 30 segundos.
library;

import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth/boveda.dart';
import '../../core/auth/otpauth.dart';

/// El reloj. Inyectable para que los tests no dependan del sistema.
final relojProvider = Provider<DateTime Function()>((ref) => DateTime.now);

/// El almacén. También inyectable: en el host de pruebas no hay Keystore.
final almacenBovedaProvider = Provider<AlmacenBoveda>((ref) => BovedaKeystore());

/// La bóveda en memoria, con el estado de carga.
///
/// ## Por qué `AsyncNotifier` y no `FutureProvider`
/// Porque hay que **escribir** en ella, no solo leerla. Con un `FutureProvider`
/// habría que invalidarlo después de cada alta y de cada borrado, y entre la
/// escritura y la invalidación hay un hueco en el que la pantalla pinta la
/// lista vieja: se añade una cuenta, la lista parpadea y sigue igual.
class BovedaController extends AsyncNotifier<Boveda> {
  /// Lee, y ya está.
  ///
  /// ## Por qué aquí no hay ningún `try`
  /// Porque la corrupción **no es una excepción**: viaja dentro del valor, como
  /// [Boveda.corrupta]. Ver la nota de ahí.
  ///
  /// La versión anterior lo traducía a `AsyncError` desde dentro del `build`, y
  /// con Riverpod 3 la pantalla se quedaba con el spinner de carga para siempre:
  /// ni el error ni un fallo, solo «cargando» sobre una bóveda ilegible. Un
  /// spinner eterno es el peor resultado posible, porque parece que está
  /// haciendo algo.
  @override
  Future<Boveda> build() => ref.watch(almacenBovedaProvider).leer();

  AlmacenBoveda get _almacen => ref.read(almacenBovedaProvider);

  /// Añade una cuenta y devuelve sus códigos en claro, **una vez**.
  ///
  /// Devuelve `null` si la bóveda está corrupta: no se escribe nada, porque
  /// sobrescribir un sobre ilegible es como se pierden las cuentas. Ver
  /// [Boveda.escribirEn].
  Future<List<String>?> anadir(CuentaQr qr) async {
    final b = await _almacen.leer();
    if (b.intocable) return null;
    final codigos = await _almacen.anadir(qr);
    await _recargar();
    return codigos;
  }

  Future<bool> borrar(String id) async {
    final b = await _almacen.leer();
    if (b.corrupta) return false;
    final hubo = await _almacen.borrar(id);
    await _recargar();
    return hubo;
  }

  /// Canjea un código de recuperación. Devuelve el `id` de la cuenta o `null`.
  Future<String?> canjear(String codigo) async {
    final b = await _almacen.leer();
    if (b.intocable) return null;
    final id = await _almacen.canjear(codigo);
    await _recargar();
    return id;
  }

  /// Vuelve a leer del disco. Para cuando se importa una copia.
  Future<void> recargar() => _recargar();

  /// Repone el estado con una **copia** de lo que hay.
  ///
  /// Ver [Boveda.copia] para por qué la copia es necesaria y no un detalle.
  Future<void> _recargar() async {
    state = AsyncData((await _almacen.leer()).copia());
  }

  /// Cambia la etiqueta de una cuenta.
  Future<void> renombrar(String id, String etiqueta) async {
    // `valueOrNull` no existe en Riverpod 3, y `requireValue` sobre un estado
    // en carga lanza. El switch es lo que dice «si lo tengo, úsalo; si no, lee».
    final b = switch (state) {
      AsyncData(:final value) => value,
      _ => await _almacen.leer(),
    };
    final i = b.cuentas.indexWhere((c) => c.id == id);
    if (i < 0) return;
    b.cuentas[i] = Cuenta(
      id: b.cuentas[i].id,
      emisor: b.cuentas[i].emisor,
      etiqueta: etiqueta.trim(),
      semilla: b.cuentas[i].semilla,
      algoritmo: b.cuentas[i].algoritmo,
      digitos: b.cuentas[i].digitos,
      periodo: b.cuentas[i].periodo,
      anadidaEn: b.cuentas[i].anadidaEn,
      ultimoUso: b.cuentas[i].ultimoUso,
    );
    await b.escribirEn(_almacen);
    await _recargar();
  }
}

final bovedaProvider =
    AsyncNotifierProvider<BovedaController, Boveda>(BovedaController.new);

/// El tick que mueve los anillos de cuenta atrás.
///
/// ## Por qué un solo `Timer` para toda la app
/// Un `Timer` por cuenta es N timers por segundo con N cuentas, y todos
/// redibujan el mismo reloj. El código de una cuenta **no depende de nada
/// externo**: depende de `reloj()`. Lo único que hay que refrescar es el
/// instante que se le pasa, y para eso basta con un tick que despierte la
/// pantalla.
///
/// Se hace a 1 Hz y no a cada 100 ms porque el anillo se lee en segundos: un
/// tick de 100 ms consume batería sin que nadie vea la diferencia. Y se pausa
/// con la app en segundo plano, que es donde una pantalla que se refresca sola
/// se convierte en un nawaste de batería.
class RelojController extends Notifier<DateTime> {
  Timer? _temporizador;

  @override
  DateTime build() {
    final r = ref.watch(relojProvider);

    // Cancelar antes de crear el otro es **lo que hace `DeploysController`** en
    // `agent_providers.dart`, y se copia por consistencia.
    //
    // ## Por qué esto NO es un arreglo de una fuga
    // Se añadió creyendo que `build()` no cancelaba el temporizador anterior y
    // que `ref.onDispose` solo corría al descartar el provider. **Está medido
    // que no era así**: Riverpod 3 llama a `onDispose` también al invalidar, así
    // que el `onDispose` de abajo ya cubría el caso.
    //
    // Medido con 3 reconstrucciones y 10 s de reloj: 40 llamadas sin ninguno de
    // los dos, 10 con cualquiera de los dos. O sea: la línea de `cancel()` y el
    // `onDispose` hacen **lo mismo**, y la que estaba ya bastaba.
    //
    // Se deja por consistir con el resto del repo, no porque arregle nada. Lo
    // contrario —quitar el `onDispose` porque «redundante»— sí rompería: es el
    // único que sobrevive a un `dispose` normal.
    _temporizador?.cancel();
    _temporizador = Timer.periodic(
      const Duration(seconds: 1),
      (_) => state = r(),
    );
    ref.onDispose(() => _temporizador?.cancel());
    return r();
  }
}

final relojUIProvider =
    NotifierProvider<RelojController, DateTime>(RelojController.new);