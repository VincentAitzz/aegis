/// Paleta de Aegis: negro de base, celeste de identidad, magenta de voz.
///
/// ## Por qué celeste, y por qué el ámbar se fue
///
/// El ámbar (`#FFB020`) fue la identidad durante el rebranding: sustituyó al verde
/// fosforito, que era de otra marca, y durante un tiempo todo fue
/// ámbar. Después Aegis cambió de identidad otra vez, y esta vez **hacia dentro**:
///
/// - **En reposo es celeste** (`#4CC9F0`). Es un color frío, de instrumento de
///   medida, y encaja con lo que esto es: un aparato que vigila, no un cartel.
/// - **Hablando es magenta rojizo** (`#FF3D7E`). No es el magenta de la marca
///   anterior —este es más caliente y más saturado— porque ese significaba otra
///   cosa y `build_apk` todavía lo vigila como centinela.
///
/// El ámbar no se ha mudado de sitio: se ha **ido**. Sigue siendo `warn`, que es
/// lo que siempre pretendió ser, y ha dejado de pintar botones.
///
/// ## El principio, que es el que manda
///
/// *Un color que significa dos cosas solo significa una, y es la que se abre
/// primero.* Por eso en Aegis:
///
/// | color | una sola cosa |
/// |---|---|
/// | celeste | la identidad, y «estoy vivo» |
/// | magenta | está hablando ahora mismo |
/// | verde / amarillo / rojo | veredictos: ok, aviso, peligro |
/// | hueso | estructura y lo que se puede tocar |
///
/// Y el botón de acción es **hueso**, no celeste, a propósito: si el celeste
/// fuera también «púlsame», un color estaría trabajando en dos turnos y el
/// glifo dejaría de decir cuándo está vivo.
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

  // -- estructura -----------------------------------------------------------
  /// Lo que se puede tocar: botones, pestañas activas, texto fuerte.
  ///
  /// ## Por qué hueso y no un color
  /// Un botón tiene que ser el blanco de la pantalla, no un color: si el botón
  /// dice «esto es lo que puedes hacer» y el glifo dice «esto es que estoy
  /// vivo», son dos preguntas distintas y necesitan dos cosas distintas. Hueso
  /// es lo que no significa nada y por tanto no compite con nada.
  static const hueso = Color(0xFFE8E4DA);
  static const huesoDim = Color(0xFFB8B3A8);

  // -- marca y estado -------------------------------------------------------
  /// La identidad de Aegis en reposo. También el acento de «vivo».
  static const brand = Color(0xFF4CC9F0);

  /// Está hablando: acaba de llegar texto. Un magenta **rojizo**, no el violeta
  /// de la marca anterior, que significaba otra cosa.
  static const voz = Color(0xFFFF3D7E);

  /// Sin puente. Gris y frío a propósito: no es un error, es una ausencia, y un
  /// rojo aquí sería mentir sobre lo grave que es.
  static const apagado = Color(0xFF5A6270);

  // -- veredictos -----------------------------------------------------------
  static const ok = Color(0xFF3DDC84);
  static const warn = Color(0xFFFFC94C);
  static const danger = Color(0xFFFF5C5C);

  // -- texto ----------------------------------------------------------------
  static const fg = Color(0xFFECEEF3);
  static const fgDim = Color(0xFF9BA3B0);
  static const fgFaint = Color(0xFF626B79);

  // -- tipografía -----------------------------------------------------------
  /// La UI. Monoespaciada de palo seco, para trazas largas en pantalla estrecha.
  static const mono = 'ShareTechMono';

  /// La VGA, **solo para el arte ASCII** y los adornos de caja. Un ASCII art con
  /// una monoespaciada moderna no se ve como VGA: el interlineado no es 8x16 y
  /// los caracteres no tienen el peso de un mapa de bits.
  static const vga = 'Px437VGA';

  /// Los títulos. Mayúsculas estrechas, del mismo tono que la consola.
  static const display = 'Oswald';
}
