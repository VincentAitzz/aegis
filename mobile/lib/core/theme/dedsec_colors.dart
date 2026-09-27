/// Paleta DedSec, extraída del análisis de píxeles de las referencias reales
/// (logo DedSec PNG y wallpaper "DedSec White").
library;

import 'package:flutter/material.dart';

abstract final class DedsecColors {
  static const bg0 = Color(0xFF060708);
  static const bg1 = Color(0xFF0C0F11);
  static const bg2 = Color(0xFF161A1D);
  static const line = Color(0xFF252B30);

  static const Color brand = Color(0xFF2EFFA0);

  static const ok = Color(0xFF2EFFA0);
  static const info = Color(0xFF35C7FF);
  static const warn = Color(0xFFFFB000);
  static const danger = Color(0xFFFF4D3E);

  static const fg = Color(0xFFEAECEF);
  static const fgDim = Color(0xFF9AA3AC);
  static const fgFaint = Color(0xFF5C666E);

  static const mono = 'ShareTechMono';
  static const display = 'Oswald';
}