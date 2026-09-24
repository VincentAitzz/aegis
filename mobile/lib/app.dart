/// Raíz de la aplicación Aegis (tema DedSec + arranque + navegación).
library;

import 'package:flutter/material.dart';

import 'core/theme/aegis_theme.dart';
import 'core/widgets/boot_screen.dart';
import 'presentation/pages/home_page.dart';

class AegisApp extends StatelessWidget {
  const AegisApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Aegis Console',
      debugShowCheckedModeBanner: false,
      theme: AegisTheme.dark(),
      themeMode: ThemeMode.dark,
      home: const BootScreen(child: HomePage()),
    );
  }
}