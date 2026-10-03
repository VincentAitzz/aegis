/// Cómo es una sección de Aegis.
///
/// ## Por qué un descriptor y no una pantalla por pestaña
/// Antes no había shell: `app.dart` iba directo a `HomePage`, que eran 626 líneas
/// con tres widgets privados dentro. Añadir un apartado significaba editar ese
/// fichero, y cuando por fin hay cuatro apartados, nadie recuerda qué había en
/// la línea 300.
///
/// Con un descriptor, **un apartado nuevo es una entrada en una lista**. No toca
/// el shell, ni la barra de navegación, ni el estado: se declara y aparece. Que
/// sea fácil meter el quinto es exactamente el motivo de que esto exista —
/// Aegis va a crecer, y lo que hay que evitar es que crecer cueste.
///
/// ## Por qué `requierePuente`
/// La mitad de las secciones son inútiles sin bridge, y una pestaña que no puede
/// hacer nada y **no explica por qué** parece un fallo. Con este campo, la
/// sección dice lo que le pasa en vez de quedarse en blanco.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../pages/ajustes_page.dart';
import '../pages/ahora_page.dart';
import '../pages/misiones_page.dart';
import '../providers/agent_providers.dart';

/// Un apartado de la app.
@immutable
class AegisSection {
  const AegisSection({
    required this.alias,
    required this.label,
    required this.icon,
    required this.iconActivo,
    required this.pantalla,
    this.requierePuente = true,
    this.globo,
  });

  /// Identificador estable. Va en el log y en los tests: si cambia, se pierde el
  /// historial de qué sección se estaba usando.
  final String alias;

  /// Lo que se ve en la barra. **Sin mayúsculas**: la barra va en `labelSmall`,
  /// y en mayúsculas a 11 px las palabras se salen de la mitad de las pantallas.
  final String label;

  final IconData icon;
  final IconData iconActivo;

  /// Se construye una vez al entrar. No es un `Widget`: si lo fuera, se
  /// reconstruiría en cada `build` del shell y perdería su estado.
  final WidgetBuilder pantalla;

  /// Si necesita el bridge. Con el bridge caído, la pestaña explica en vez de
  /// quedarse muda.
  final bool requierePuente;

  /// Texto de la descripción de la pestaña.
  final String? globo;

  }

/// El registro de secciones.
///
/// Añadir un apartado es añadir una línea a esta lista. Es el único sitio que
/// hay que tocar, y está aquí para que se vea.
final List<AegisSection> kSecciones = [
  AegisSection(
    alias: 'ahora',
    label: 'Ahora',
    icon: Icons.shield_outlined,
    iconActivo: Icons.shield,
    pantalla: (_) => const AhoraPage(),
  ),
  AegisSection(
    alias: 'misiones',
    label: 'Misiones',
    icon: Icons.playlist_add_check_outlined,
    iconActivo: Icons.playlist_add_check,
    pantalla: (_) => const MisionesPage(),
  ),
  AegisSection(
    alias: 'ajustes',
    label: 'Ajustes',
    icon: Icons.tune_outlined,
    iconActivo: Icons.tune,
    requierePuente: false,
    pantalla: (_) => const AjustesPage(),
  ),
];

/// Qué sección está abierta.
final seccionActualProvider =
    NotifierProvider<SeccionController, String>(SeccionController.new);

class SeccionController extends Notifier<String> {
  @override
  String build() => kSecciones.first.alias;

  void abrir(String alias) => state = alias;
}

/// Si el bridge está vivo. Lo consumen el shell y las secciones que lo necesitan.
final puenteVivoProvider = Provider<bool>((ref) {
  final health = ref.watch(healthProvider);
  return health.when(data: (h) => h.ok, loading: () => true, error: (_, _) => false);
});
