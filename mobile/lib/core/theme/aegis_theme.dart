/// Tema oscuro DedSec: negro de base, magenta de marca, tipografía mono +
/// Oswald para títulos. Esquinas duras y bordes en vez de sombras.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'dedsec_colors.dart';

abstract final class AegisTheme {
  static TextStyle disp(double size, FontWeight weight, double lsp) =>
      TextStyle(
        fontFamily: DedsecColors.display,
        fontSize: size,
        fontWeight: weight,
        letterSpacing: lsp,
        height: 1.1,
        color: DedsecColors.fg,
      );

  static TextStyle mono(double size, [double lsp = 0.5]) => TextStyle(
        fontFamily: DedsecColors.mono,
        fontSize: size,
        letterSpacing: lsp,
        height: 1.5,
        color: DedsecColors.fg,
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
        primary: DedsecColors.brand,
        onPrimary: Color(0xFF07030A),
        secondary: DedsecColors.info,
        onSecondary: Color(0xFF03121A),
        surface: DedsecColors.bg2,
        onSurface: DedsecColors.fg,
        error: DedsecColors.danger,
        onError: Color(0xFF1A0603),
        secondaryContainer: DedsecColors.bg2,
        tertiaryContainer: DedsecColors.bg2,
        outline: DedsecColors.line,
      ),
      scaffoldBackgroundColor: DedsecColors.bg0,
      canvasColor: DedsecColors.bg0,
      splashFactory: NoSplash.splashFactory,
      highlightColor: Colors.transparent,
      visualDensity: VisualDensity.compact,
      fontFamily: DedsecColors.mono,
      textTheme: const TextTheme(
        displayLarge: TextStyle(fontFamily: DedsecColors.display, fontSize: 36, fontWeight: FontWeight.w700, letterSpacing: 6, height: 1.1, color: DedsecColors.fg),
        displayMedium: TextStyle(fontFamily: DedsecColors.display, fontSize: 30, fontWeight: FontWeight.w700, letterSpacing: 5, height: 1.1, color: DedsecColors.fg),
        displaySmall: TextStyle(fontFamily: DedsecColors.display, fontSize: 24, fontWeight: FontWeight.w700, letterSpacing: 4, height: 1.15, color: DedsecColors.fg),
        headlineMedium: TextStyle(fontFamily: DedsecColors.display, fontSize: 20, fontWeight: FontWeight.w600, letterSpacing: 4, height: 1.2, color: DedsecColors.fg),
        titleLarge: TextStyle(fontFamily: DedsecColors.display, fontSize: 18, fontWeight: FontWeight.w600, letterSpacing: 3, height: 1.25, color: DedsecColors.fg),
        titleMedium: TextStyle(fontFamily: DedsecColors.mono, fontSize: 14, fontWeight: FontWeight.w600, letterSpacing: 1, height: 1.4, color: DedsecColors.fg),
        titleSmall: TextStyle(fontFamily: DedsecColors.mono, fontSize: 12, fontWeight: FontWeight.w600, letterSpacing: 1, height: 1.4, color: DedsecColors.fgDim),
        bodyLarge: TextStyle(fontFamily: DedsecColors.mono, fontSize: 14, letterSpacing: 0.5, height: 1.5, color: DedsecColors.fg),
        bodyMedium: TextStyle(fontFamily: DedsecColors.mono, fontSize: 13, letterSpacing: 0.5, height: 1.45, color: DedsecColors.fg),
        bodySmall: TextStyle(fontFamily: DedsecColors.mono, fontSize: 11, letterSpacing: 0.5, height: 1.3, color: DedsecColors.fgDim),
        labelLarge: TextStyle(fontFamily: DedsecColors.mono, fontSize: 13, letterSpacing: 1.5, height: 1.4, color: DedsecColors.fg),
        labelMedium: TextStyle(fontFamily: DedsecColors.mono, fontSize: 11, letterSpacing: 1.5, height: 1.4, color: DedsecColors.fg),
        labelSmall: TextStyle(fontFamily: DedsecColors.mono, fontSize: 10, letterSpacing: 1.5, height: 1.4, color: DedsecColors.fgFaint),
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: DedsecColors.bg0,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(fontFamily: DedsecColors.display, fontSize: 19, fontWeight: FontWeight.w600, letterSpacing: 4, height: 1.2, color: DedsecColors.fg),
        iconTheme: IconThemeData(color: DedsecColors.fg),
        systemOverlayStyle: SystemUiOverlayStyle(
          statusBarColor: Colors.transparent,
          statusBarIconBrightness: Brightness.light,
          statusBarBrightness: Brightness.dark,
        ),
      ),
      cardTheme: const CardThemeData(
        color: DedsecColors.bg1,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.all(Radius.circular(8)),
          side: BorderSide(color: DedsecColors.line),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: DedsecColors.bg2,
        hintStyle: const TextStyle(fontFamily: DedsecColors.mono, fontSize: 13, color: DedsecColors.fgFaint),
        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
        border: _border(DedsecColors.line),
        enabledBorder: _border(DedsecColors.line),
        focusedBorder: _border(DedsecColors.brand, 1.4),
        errorBorder: _border(DedsecColors.danger),
        focusedErrorBorder: _border(DedsecColors.danger, 1.4),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: DedsecColors.brand,
          foregroundColor: const Color(0xFF07030A),
          disabledBackgroundColor: DedsecColors.line,
          disabledForegroundColor: DedsecColors.fgFaint,
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(4)),
          textStyle: const TextStyle(fontFamily: DedsecColors.display, fontSize: 14, fontWeight: FontWeight.w600, letterSpacing: 2.5),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: DedsecColors.brand,
          disabledForegroundColor: DedsecColors.fgFaint,
          side: const BorderSide(color: DedsecColors.line),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(4)),
          textStyle: const TextStyle(fontFamily: DedsecColors.mono, fontSize: 12, letterSpacing: 2, fontWeight: FontWeight.w600),
        ),
      ),
      segmentedButtonTheme: SegmentedButtonThemeData(
        style: ButtonStyle(
          backgroundColor: WidgetStateProperty.resolveWith(
            (states) => states.contains(WidgetState.selected)
                ? DedsecColors.brand.withValues(alpha: .14)
                : DedsecColors.bg2,
          ),
          foregroundColor: WidgetStateProperty.resolveWith(
            (states) => states.contains(WidgetState.selected)
                ? DedsecColors.brand
                : DedsecColors.fgDim,
          ),
          side: const WidgetStatePropertyAll(BorderSide(color: DedsecColors.line)),
          shape: WidgetStatePropertyAll(
            RoundedRectangleBorder(borderRadius: BorderRadius.circular(4)),
          ),
          textStyle: const WidgetStatePropertyAll(TextStyle(fontFamily: DedsecColors.mono, fontSize: 12, letterSpacing: 1.5, fontWeight: FontWeight.w600)),
          padding: const WidgetStatePropertyAll(EdgeInsets.symmetric(horizontal: 14, vertical: 10)),
        ),
      ),
      chipTheme: const ChipThemeData(
        backgroundColor: DedsecColors.bg2,
        side: BorderSide(color: DedsecColors.line),
        labelStyle: TextStyle(fontFamily: DedsecColors.mono, fontSize: 11, color: DedsecColors.fgDim),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(4))),
        padding: EdgeInsets.zero,
      ),
      snackBarTheme: const SnackBarThemeData(
        backgroundColor: DedsecColors.bg2,
        contentTextStyle: TextStyle(fontFamily: DedsecColors.mono, fontSize: 13, color: DedsecColors.fgDim),
        behavior: SnackBarBehavior.floating,
        elevation: 0,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(6)), side: BorderSide(color: DedsecColors.line)),
      ),
      dividerTheme: const DividerThemeData(color: DedsecColors.line, thickness: 1, space: 1),
      progressIndicatorTheme: const ProgressIndicatorThemeData(color: DedsecColors.brand, linearTrackColor: DedsecColors.bg2, circularTrackColor: DedsecColors.bg2),
      textSelectionTheme: const TextSelectionThemeData(
        cursorColor: DedsecColors.brand,
        selectionColor: Color(0x4D2EFFA0),
        selectionHandleColor: DedsecColors.brand,
      ),
      iconTheme: const IconThemeData(color: DedsecColors.fg),
    );
  }
}