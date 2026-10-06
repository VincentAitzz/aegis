/// El alta de un proyecto: el formulario que hace falta para empezar un encargo.
///
/// ## Por qué aquí y no con un run de autopilot
/// Dar de alta un proyecto es enteramente determinista —una carpeta, un JSON y
/// dos ficheros de texto—, y hacerlo por el modelo significaba pagar una
/// inferencia y un aprobado de nivel 3 para escribir texto que ya estaba escrito.
/// Además el alta es una decisión de la persona, no del agente: es la línea.
/// `alta.alta()` decide dónde puede caer la carpeta y qué verifica, y aquí solo se
/// le pasan los datos.
///
/// ## Lo que se pide, y por qué está todo
/// - **alias**: minúsculas, dígitos, punto, guion y guion bajo. El mismo patrón
///   que valida `alta._ALIAS`, comprobado aquí para que el error salga antes de
///   gastar un viaje. El bridge lo vuelve a validar: si las dos copias
///   se desvían, manda el bridge.
/// - **área**: tres, porque solo hay tres.
/// - **tipo**: decide qué secciones hay que escribir, así que no se puede
///   adivinar.
/// - **verificador**: sin esto `POST /autonomy/{alias}` responde 409 y el
///   proyecto recién creado no puede marcado para escritura. O sea: sin este
///   campo el alta puede terminar en algo que Aegis no puede tocar.
///
/// ## Lo que no se pide
/// El precio y las fechas. Esos van en la ficha privada, y Aegis tiene prohibido
/// inventarlos.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/errores.dart';
import '../../core/theme/aegis_palette.dart';
import '../../data/models/asistente_models.dart';
import '../providers/agent_providers.dart';

/// El patrón de alias de `alta._ALIAS`, comprobado aquí para no gastar un viaje.
final RegExp _aliasValido = RegExp(r'^[a-z0-9][a-z0-9._-]{0,48}$');

class HojaAlta extends ConsumerStatefulWidget {
  const HojaAlta({super.key});

  @override
  ConsumerState<HojaAlta> createState() => HojaAltaState();
}

class HojaAltaState extends ConsumerState<HojaAlta> {
  final _alias = TextEditingController();
  final _nombre = TextEditingController();
  final _alcance = TextEditingController();
  final _verificador = TextEditingController();
  final _db = TextEditingController();

  String _area = kAreas.first.valor;
  String _tipo = kTiposProyecto.first.valor;
  bool _conBase = false;

  bool _enviando = false;
  String? _aviso;

  /// Lo que devolvió el alta, si se creó algo. Se pinta entero porque explica
  /// qué se creó y avisa de que sin verificador no habrá permiso.
  ProyectoAlta? _creado;

  @override
  void dispose() {
    for (final c in [_alias, _nombre, _alcance, _verificador, _db]) {
      c.dispose();
    }
    super.dispose();
  }

  String? get _errorAlias {
    final v = _alias.text.trim();
    if (v.isEmpty) return null;
    if (!_aliasValido.hasMatch(v)) {
      return 'minúsculas, dígitos, punto, guion y guion bajo, empezando por letra o dígito';
    }
    return null;
  }

  bool get _puedeEnviar => _alias.text.trim().isNotEmpty && _errorAlias == null;

  Future<void> _enviar() async {
    setState(() {
      _enviando = true;
      _aviso = null;
    });
    try {
      final r = await ref.read(agentRepositoryProvider).crearProyecto(
            alias: _alias.text.trim(),
            area: _area,
            kind: _tipo,
            nombre: _nombre.text.trim(),
            alcance: _alcance.text.trim(),
            verificar: _verificador.text.trim(),
            db: _conBase ? _db.text.trim() : '',
            carpeta: '',
            yaExiste: false,
          );
      if (!mounted) return;
      setState(() {
        _enviando = false;
        _creado = r;
      });
      refrescarAsistente(ref);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _enviando = false;
        _aviso = mensajeDeError(e);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 20),
          child: _creado != null ? _resumen() : _formulario(),
        ),
      ),
    );
  }

  Widget _formulario() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text(
          'NUEVO PROYECTO',
          style: TextStyle(
            fontFamily: AegisPalette.display,
            fontSize: 12,
            letterSpacing: 2,
            color: AegisPalette.fgFaint,
          ),
        ),
        const SizedBox(height: 4),
        const Text(
          'Se crea la carpeta, el registro, la ficha técnica y la ficha del '
          'cliente. La técnica la rellenas después, sección a sección.',
          style: TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 10.5,
              height: 1.5,
              color: AegisPalette.fgFaint),
        ),
        const SizedBox(height: 14),
        _Campo(
          etiqueta: 'alias',
          ayuda: 'Con minúsculas. Es el nombre corto que usa Aegis.',
          controller: _alias,
          error: _errorAlias,
          onChanged: () => setState(() {}),
        ),
        const SizedBox(height: 12),
        _Eleccion<String>(
          etiqueta: 'área',
          ayuda: 'Dónde vive la carpeta dentro del workspace.',
          opciones: kAreas,
          valor: _area,
          onCambio: (v) => setState(() => _area = v),
        ),
        const SizedBox(height: 12),
        _Eleccion<String>(
          etiqueta: 'tipo',
          ayuda: 'Decide qué secciones habrá que escribir. No se puede adivinar.',
          opciones: kTiposProyecto,
          valor: _tipo,
          onCambio: (v) => setState(() => _tipo = v),
        ),
        const SizedBox(height: 12),
        _Campo(
          etiqueta: 'nombre',
          ayuda: 'Cómo se llama. Opcional.',
          controller: _nombre,
        ),
        const SizedBox(height: 12),
        _Campo(
          etiqueta: 'alcance',
          ayuda: 'Una frase de lo que entra. Se escribe en «Alcance dentro».',
          controller: _alcance,
          lineas: 3,
        ),
        const SizedBox(height: 12),
        _Campo(
          etiqueta: 'verificador',
          ayuda: 'Los comandos que comprueban que el trabajo quedó bien. '
              'Sin esto Aegis no puede escribir en el proyecto: no hay contra '
              'qué comprobar que salió bien.',
          controller: _verificador,
          lineas: 2,
          pista: '{"check": ["tsc --noEmit"], "test": ["vitest run"]}',
        ),
        const SizedBox(height: 12),
        _ConBase(
          valor: _conBase,
          controller: _db,
          onCambio: (v) => setState(() => _conBase = v),
        ),
        if (_aviso != null) ...[
          const SizedBox(height: 12),
          Text(_aviso!,
              style: const TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 11,
                  height: 1.5,
                  color: AegisPalette.danger)),
        ],
        const SizedBox(height: 16),
        FilledButton(
          onPressed: !_puedeEnviar || _enviando ? null : _enviar,
          style: FilledButton.styleFrom(
            backgroundColor: AegisPalette.ok,
            foregroundColor: AegisPalette.bg0,
          ),
          child: Text(_enviando ? 'Creando…' : 'Crear el proyecto'),
        ),
      ],
    );
  }

  Widget _resumen() {
    final c = _creado!;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text(
          'PROYECTO CREADO',
          style: TextStyle(
            fontFamily: AegisPalette.display,
            fontSize: 12,
            letterSpacing: 2,
            color: AegisPalette.ok,
          ),
        ),
        const SizedBox(height: 10),
        Container(
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            border: Border.all(color: AegisPalette.line),
            color: AegisPalette.bg2,
          ),
          child: Text(
            c.mensaje,
            style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 10.5,
                height: 1.6,
                color: AegisPalette.fg),
          ),
        ),
        if (c.faltan.isNotEmpty) ...[
          const SizedBox(height: 12),
          const Text(
            'Falta escribir en la ficha:',
            style: TextStyle(
                fontFamily: AegisPalette.mono, fontSize: 11, color: AegisPalette.warn),
          ),
          const SizedBox(height: 4),
          for (final f in c.faltan)
            Text('· $f',
                style: const TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 10.5,
                    color: AegisPalette.fgFaint)),
        ],
        const SizedBox(height: 16),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(true),
          style: FilledButton.styleFrom(
            backgroundColor: AegisPalette.bg2,
            foregroundColor: AegisPalette.fg,
          ),
          child: const Text('Ir a rellenarla'),
        ),
      ],
    );
  }
}

class _Campo extends StatelessWidget {
  const _Campo({
    required this.etiqueta,
    required this.ayuda,
    required this.controller,
    this.lineas = 1,
    this.error,
    this.onChanged,
    this.pista = '',
  });

  final String etiqueta;
  final String ayuda;
  final TextEditingController controller;
  final int lineas;
  final String? error;
  final VoidCallback? onChanged;
  final String pista;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(etiqueta,
            style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 11,
                letterSpacing: 0.5,
                color: AegisPalette.fg)),
        const SizedBox(height: 2),
        Text(ayuda,
            style: TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 10,
                height: 1.5,
                color: error == null ? AegisPalette.fgFaint : AegisPalette.danger)),
        const SizedBox(height: 5),
        TextField(
          controller: controller,
          maxLines: lineas,
          minLines: 1,
          style: const TextStyle(
              fontFamily: AegisPalette.mono, fontSize: 12, color: AegisPalette.fg),
          decoration: InputDecoration(
            isDense: true,
            hintText: pista.isEmpty ? null : pista,
            errorText: error,
          ),
          onChanged: onChanged == null ? null : (_) => onChanged!(),
        ),
      ],
    );
  }
}

class _Eleccion<T> extends StatelessWidget {
  const _Eleccion({
    required this.etiqueta,
    required this.ayuda,
    required this.opciones,
    required this.valor,
    required this.onCambio,
  });

  final String etiqueta;
  final String ayuda;
  final List<({String valor, String etiqueta})> opciones;
  final String valor;
  final void Function(String) onCambio;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(etiqueta,
            style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 11,
                color: AegisPalette.fg)),
        const SizedBox(height: 2),
        Text(ayuda,
            style: const TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 10,
                height: 1.5,
                color: AegisPalette.fgFaint)),
        const SizedBox(height: 6),
        Wrap(
          spacing: 6,
          children: [
            for (final o in opciones)
              ChoiceChip(
                label: Text(o.etiqueta,
                    style: const TextStyle(
                        fontFamily: AegisPalette.mono, fontSize: 10.5)),
                selected: valor == o.valor,
                onSelected: (_) => onCambio(o.valor),
              ),
          ],
        ),
      ],
    );
  }
}

class _ConBase extends StatelessWidget {
  const _ConBase({
    required this.valor,
    required this.controller,
    required this.onCambio,
  });

  final bool valor;
  final TextEditingController controller;
  final void Function(bool) onCambio;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            const Expanded(
              child: Text('¿Tiene base de datos?',
                  style: TextStyle(
                      fontFamily: AegisPalette.mono,
                      fontSize: 11,
                      color: AegisPalette.fg)),
            ),
            Switch(value: valor, onChanged: onCambio),
          ],
        ),
        Text(
          valor
              ? 'La base se declara aquí; las credenciales nunca van en el registro.'
              : 'Di que no si no la tiene. No es lo mismo que «no lo sé», y el '
                  'registro distingue los dos casos.',
          style: const TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 10,
              height: 1.5,
              color: AegisPalette.fgFaint),
        ),
        if (valor) ...[
          const SizedBox(height: 6),
          TextField(
            controller: controller,
            style: const TextStyle(
                fontFamily: AegisPalette.mono, fontSize: 12, color: AegisPalette.fg),
            decoration: const InputDecoration(
              isDense: true,
              hintText: 'proveedor: neon, postgres…',
            ),
          ),
        ],
      ],
    );
  }
}