/// Raíz de la aplicación Aegis (tema + navegación).
library;

import 'package:flutter/material.dart';

import 'presentation/pages/home_page.dart';

class AegisApp extends StatelessWidget {
  const AegisApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Aegis Console',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF0F766E)),
      ),
      home: const HomePage(),
    );
  }
}