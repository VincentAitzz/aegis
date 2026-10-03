/// Tema oscuro de Aegis: negro de base, ámbar de marca, tipografía mono +
/// Oswald para títulos. Esquinas duras y bordes en vez de sombras.
///
/// El borde en lugar de la sombra es una decisión, no una manía: sobre negro
/// una sombra no se ve, así que el separador tiene que ser un trazo. Y es lo que
/// sostiene la lectura de una traza larga, que es donde vive casi toda la
/// información de esta app.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'aegis_palette.dart';

abstract final class AegisTheme {
  static TextStyle disp(double size, FontWeight weight, double lsp) =>
      TextStyle(
        fontFamily: AegisPalette.display,
        fontSize: size,
        fontWeight: weight,
        letterSpacing: lsp,
        height: 1.1,
        color: AegisPalette.fg,
      );

  static TextStyle mono(double size, [double lsp = 0.5]) => TextStyle(
        fontFamily: AegisPalette.mono,
        fontSize: size,
        letterSpacing: lsp,
        height: 1.5,
        color: AegisPalette.fg,
      );

  static OutlineInputBorder _border(Color c, [double w = 1]) =>
      OutlineInputBorder(
        borderRadius: BorderRadius.circular(6),
        borderSide: BorderSide(color: c, width: w),
      );

  static ThemeData dark() {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: const ColorScheme.dark(
        primary: AegisPalette.brand,
        onPrimary: Color(0xFF1A1206),
        secondary: AegisPalette.info,
        onSecondary: Color(0xFF03121A),
        surface: AegisPalette.bg2,
        onSurface: AegisPalette.fg,
        error: AegisPalette.danger,
        onError: Color(0xFF1A0603),
        secondaryContainer: AegisPalette.bg2,
        tertiaryContainer: AegisPalette.bg2,
        outline: AegisPalette.line,
      ),
      scaffoldBackgroundColor: AegisPalette.bg0,
      canvasColor: AegisPalette.bg0,
      splashFactory: NoSplash.splashFactory,
      highlightColor: Colors.transparent,
      visualDensity: VisualDensity.compact,
      fontFamily: AegisPalette.mono,
      textTheme: const TextTheme(
        displayLarge: TextStyle(fontFamily: AegisPalette.display, fontSize: 36, fontWeight: FontWeight.w700, letterSpacing: 6, height: 1.1, color: AegisPalette.fg),
        displayMedium: TextStyle(fontFamily: AegisPalette.display, fontSize: 30, fontWeight: FontWeight.w700, letterSpacing: 5, height: 1.1, color: AegisPalette.fg),
        displaySmall: TextStyle(fontFamily: AegisPalette.display, fontSize: 24, fontWeight: FontWeight.w700, letterSpacing: 4, height: 1.15, color: AegisPalette.fg),
        headlineMedium: TextStyle(fontFamily: AegisPalette.display, fontSize: 20, fontWeight: FontWeight.w600, letterSpacing: 4, height: 1.2, color: AegisPalette.fg),
        titleLarge: TextStyle(fontFamily: AegisPalette.display, fontSize: 18, fontWeight: FontWeight.w600, letterSpacing: 3, height: 1.25, color: AegisPalette.fg),
        titleMedium: TextStyle(fontFamily: AegisPalette.mono, fontSize: 14, fontWeight: FontWeight.w600, letterSpacing: 1, height: 1.4, color: AegisPalette.fg),
        titleSmall: TextStyle(fontFamily: AegisPalette.mono, fontSize: 12, fontWeight: FontWeight.w600, letterSpacing: 1, height: 1.4, color: AegisPalette.fgDim),
        bodyLarge: TextStyle(fontFamily: AegisPalette.mono, fontSize: 14, letterSpacing: 0.5, height: 1.5, color: AegisPalette.fg),
        bodyMedium: TextStyle(fontFamily: AegisPalette.mono, fontSize: 13, letterSpacing: 0.5, height: 1.45, color: AegisPalette.fg),
        bodySmall: TextStyle(fontFamily: AegisPalette.mono, fontSize: 11, letterSpacing: 0.5, height: 1.3, color: AegisPalette.fgDim),
        labelLarge: TextStyle(fontFamily: AegisPalette.mono, fontSize: 13, letterSpacing: 1.5, height: 1.4, color: AegisPalette.fg),
        labelMedium: TextStyle(fontFamily: AegisPalette.mono, fontSize: 11, letterSpacing: 1.5, height: 1.4, color: AegisPalette.fg),
        labelSmall: TextStyle(fontFamily: AegisPalette.mono, fontSize: 10, letterSpacing: 1.5, height: 1.4, color: AegisPalette.fgFaint),
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: AegisPalette.bg0,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(fontFamily: AegisPalette.display, fontSize: 19, fontWeight: FontWeight.w600, letterSpacing: 4, height: 1.2, color: AegisPalette.fg),
        iconTheme: IconThemeData(color: AegisPalette.fg),
        systemOverlayStyle: SystemUiOverlayStyle(
          statusBarColor: Colors.transparent,
          statusBarIconBrightness: Brightness.light,
          statusBarBrightness: Brightness.dark,
        ),
      ),
      cardTheme: const CardThemeData(
        color: AegisPalette.bg1,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.all(Radius.circular(8)),
          side: BorderSide(color: AegisPalette.line),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AegisPalette.bg2,
        hintStyle: const TextStyle(fontFamily: AegisPalette.mono, fontSize: 13, color: AegisPalette.fgFaint),
        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
        border: _border(AegisPalette.line),
        enabledBorder: _border(AegisPalette.line),
        focusedBorder: _border(AegisPalette.brand, 1.4),
        errorBorder: _border(AegisPalette.danger),
        focusedErrorBorder: _border(AegisPalette.danger, 1.4),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: AegisPalette.brand,
          foregroundColor: const Color(0xFF1A1206),
          disabledBackgroundColor: AegisPalette.line,
          disabledForegroundColor: AegisPalette.fgFaint,
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(4)),
          textStyle: const TextStyle(fontFamily: AegisPalette.display, fontSize: 14, fontWeight: FontWeight.w600, letterSpacing: 2.5),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: AegisPalette.brand,
          disabledForegroundColor: AegisPalette.fgFaint,
          side: const BorderSide(color: AegisPalette.line),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(4)),
          textStyle: const TextStyle(fontFamily: AegisPalette.mono, fontSize: 12, letterSpacing: 2, fontWeight: FontWeight.w600),
        ),
      ),
      segmentedButtonTheme: SegmentedButtonThemeData(
        style: ButtonStyle(
          backgroundColor: WidgetStateProperty.resolveWith(
            (states) => states.contains(WidgetState.selected)
                ? AegisPalette.brand.withValues(alpha: .14)
                : AegisPalette.bg2,
          ),
          foregroundColor: WidgetStateProperty.resolveWith(
            (states) => states.contains(WidgetState.selected)
                ? AegisPalette.brand
                : AegisPalette.fgDim,
          ),
          side: const WidgetStatePropertyAll(BorderSide(color: AegisPalette.line)),
          shape: WidgetStatePropertyAll(
            RoundedRectangleBorder(borderRadius: BorderRadius.circular(4)),
          ),
          textStyle: const WidgetStatePropertyAll(TextStyle(fontFamily: AegisPalette.mono, fontSize: 12, letterSpacing: 1.5, fontWeight: FontWeight.w600)),
          padding: const WidgetStatePropertyAll(EdgeInsets.symmetric(horizontal: 14, vertical: 10)),
        ),
      ),
      chipTheme: const ChipThemeData(
        backgroundColor: AegisPalette.bg2,
        side: BorderSide(color: AegisPalette.line),
        labelStyle: TextStyle(fontFamily: AegisPalette.mono, fontSize: 11, color: AegisPalette.fgDim),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(4))),
        padding: EdgeInsets.zero,
      ),
      snackBarTheme: const SnackBarThemeData(
        backgroundColor: AegisPalette.bg2,
        contentTextStyle: TextStyle(fontFamily: AegisPalette.mono, fontSize: 13, color: AegisPalette.fgDim),
        behavior: SnackBarBehavior.floating,
        elevation: 0,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(6)), side: BorderSide(color: AegisPalette.line)),
      ),
      dividerTheme: const DividerThemeData(color: AegisPalette.line, thickness: 1, space: 1),
      progressIndicatorTheme: const ProgressIndicatorThemeData(color: AegisPalette.brand, linearTrackColor: AegisPalette.bg2, circularTrackColor: AegisPalette.bg2),
      textSelectionTheme: const TextSelectionThemeData(
        cursorColor: AegisPalette.brand,
        selectionColor: Color(0x4DFFB020),
        selectionHandleColor: AegisPalette.brand,
      ),
      iconTheme: const IconThemeData(color: AegisPalette.fg),
    );
  }
}
