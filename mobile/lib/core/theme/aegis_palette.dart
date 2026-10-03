/// Paleta de Aegis: negro de base, ámbar de marca, cian de información.
///
/// ## Por qué ámbar y no verde
/// El verde fosforito sobre negro era el acento de otra marca, y con él Aegis
/// parecía prestado. El ámbar mantiene el mismo contraste —alto, pensado para
/// trazas largas en una pantalla de móvil— pero es de Aegis.
///
/// ## Por qué `ok` ya no es el color de marca
/// Antes `ok` y `brand` eran el mismo verde, así que *todo* era verde: un
/// despliegue aprobado, una comprobación en verde y un texto de marca. Ahora
/// `brand` es ámbar (la identidad) y `ok` es verde (el veredicto). Un color que
/// significa dos cosas solo significa una, y es la que se abre primero.
library;

import 'package:flutter/material.dart';

abstract final class AegisPalette {
  // -- superficies ----------------------------------------------------------
  /// Fondo de la app. Negro con un punto de azul, no gris neutro: a pantalla
  /// completa un gris puro vibra y cansa, y este es el color que mas superficie
  /// tiene.
  static const bg0 = Color(0xFF07080B);
  static const bg1 = Color(0xFF0E1015);
  static const bg2 = Color(0xFF171A21);
  static const line = Color(0xFF272C36);

  // -- marca ----------------------------------------------------------------
  /// El acento de Aegis. Ámbar: cálido, legible sobre negro, y tomado de ninguna
  /// otra familia de producto del entorno.
  static const brand = Color(0xFFFFB020);
  static const info = Color(0xFF4CC9F0);

  // -- veredictos -----------------------------------------------------------
  static const ok = Color(0xFF3DDC84);
  static const warn = Color(0xFFFFC94C);
  static const danger = Color(0xFFFF5C5C);

  // -- texto ----------------------------------------------------------------
  static const fg = Color(0xFFECEEF3);
  static const fgDim = Color(0xFF9BA3B0);
  static const fgFaint = Color(0xFF626B79);

  // -- tipografía -----------------------------------------------------------
  static const mono = 'ShareTechMono';
  static const display = 'Oswald';
}
