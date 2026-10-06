/// La hoja de la ficha: pestañas, acordeón, y el botón de «que Aegis lo cree».
///
/// ## Por qué el formulario genera el markdown
/// Porque a un modelo pequeño copiando un texto literal se le comen los `---` del
/// frontmatter (A-016), y el `---` es lo que declara el `kind`: sin él la puerta
/// rechaza la ficha y no dice por qué. Aquí el documento lo arma `generador.dart`,
/// que es determinista y además idempotente —guardar dos veces da el mismo texto,
/// así que nadie pierde contenido por pulsar de más.
///
/// ## Por qué la caja de markdown respeta lo que escribas
/// Si el generador reescribiera el documento entero desde cero, cualquier cosa
/// que no estuviera en un campo desaparecería en el siguiente guardado. No es un
/// detalle: es lo que hace que puedas escribir aquí lo que el formulario no te
/// pregunta. La regla es explícita —si tocas la caja, el generador deja de pisar
/// tus ediciones y el botón lo dice en vez de perderlo en silencio—.
///
/// ## Las dos pestañas
/// **Ficha** es lo técnico y se versiona. **Cliente** es lo comercial y no se
/// versiona (`fichas-privadas/`, fuera de git), porque es información de un
/// tercero. Van separadas no por comodidad: mezclarlas acaba metiendo un nombre y
/// un teléfono en un fichero que va a `git push`.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/fichas/generador.dart';
import '../../core/network/errores.dart';
import '../../core/theme/aegis_palette.dart';
import '../../data/models/asistente_models.dart';
import '../providers/agent_providers.dart';
import '../shell/aegis_section.dart';
import '../widgets/acordeon_secciones.dart';

/// La ayuda de cada sección, escrita para ti y no para el bridge.
///
/// El texto viene del bridge en el caso de **qué** secciones hay; esto es **qué
/// se espera** en cada una. Viven separados a propósito: las secciones cambian con
/// la plantilla, y estas con el oficio. Ponerlo junto lo haría cambiar de sitio.
const Map<String, String> _ayudaPublica = {
  'Qué problema resuelve': 'En las palabras de quien lo tiene. Si lo escribes tú\n'
      'con tus términos, Aegis deja de traducir mal el encargo.',
  'Para qué se usa': 'La acción concreta que alguien hace con esto. "Se usa" no es\n'
      '"existe": una pantalla puede existir sin que nadie la toque.',
  'Quién lo usa': 'Roles y cantidad. "El equipo" no dice quién ni cuántos.',
  'Criterio de aceptación': 'Cómo se sabrá que funcionó, observable. Sin esto el\n'
      'trabajo está hecho cuando a ti te parezca.',
  'Alcance dentro': 'Lo que sí entra.',
  'Alcance fuera': 'Lo que no entra, explícito. Un alcance sin exclusiones es una promesa.',
  'Alternativas consideradas': 'Cada opción, y por qué se descartó. Si no se miró\n'
      'ninguna, eso es un hallazgo.',
  'Cómo se verifica': 'Los comandos, y qué deben dar. Sin esto el proyecto no puede\n'
      'tener permiso de escritura: no hay contra qué comprobar que salió bien.',
  'Qué es': 'Una frase.',
  'Para quién': 'Los usuarios reales.',
  'Dónde estamos': 'Estado actual, sin adornos.',
  'Próximo paso': 'Una sola cosa concreta y verificable.',
  'Invariantes': 'Lo que no puede romperse.',
  'Qué no toca': 'Lo que deliberadamente no hace, y por qué.',
  'Por qué existe': 'Qué problema propio resuelve.',
};

/// La ayuda de cada sección comercial. Las que no aparecen aquí se muestran sin
/// texto, porque no todas necesitan explicación.
const Map<String, String> _ayudaPrivada = {
  'Cliente y contacto': 'Nombre, a quién se le habla y cómo se le avisa.',
  'El encargo, en sus palabras': 'El problema con sus frases, no con las tuyas.',
  'Presupuesto y pagos': 'Montos, forma de pago, condiciones, y cuándo se paga cada parte.',
  'Fechas y plazos': 'Solo fechas que tú hayas acordado. Si no hay ninguna, escribe\n'
      '«sin fecha comprometida» en vez de dejar que Aegis la suponga.',
  'Hitos y facturación': 'Qué se entrega en cada hito y qué se factura con él.',
  'Horas extra o trabajos fuera de alcance': 'Qué cuenta como extra, a qué tarifa, y quién lo aprueba antes.',
  'Canal y reuniones': 'Dónde se habla, con qué periodicidad, y quién asiste por tu lado.',
  'Garantía y soporte': 'Qué se cubre, por cuánto tiempo, y qué se considera fuera.',
  'Lo prometido': 'Todo lo que dijiste que ibas a hacer, con su plazo. Lo que está\n'
      'aquí es un compromiso tuyo; lo que no está, no existe.',
  'Riesgos y qué lo haría pelota': 'Lo que aún no está claro, lo que el cliente espera y no dijo,\n'
      'y qué tendría que pasar para que el encargo se caiga.',
  'Lo que hay que tener cuidado de decir': 'Frases que con este cliente no funcionan, o datos que no\n'
      'deben salir en ninguna respuesta de Aegis.',
};

/// Qué secciones tiene sentido preguntar para cada modelo de cobro.
///
/// ## Por qué esto está y no en el puente
/// Porque es una decisión de **interfaz**, no de formato: el fichero admite que
/// escribas «modelo: por horas» y «hitos: no aplica» en la misma hoja. Ocultar las
/// secciones que no aplican es lo que hace cómodo rellenarlo, y el puente no
/// debería saber cómo se ve una pantalla.
const Map<ModeloDeCobro, List<String>> _seccionesPorCobro = {
  ModeloDeCobro.precioCerrado: ['Presupuesto y pagos', 'Hitos y facturación'],
  ModeloDeCobro.porHitos: ['Presupuesto y pagos', 'Hitos y facturación', 'Fechas y plazos'],
  ModeloDeCobro.porHoras: ['Presupuesto y pagos', 'Horas extra o trabajos fuera de alcance'],
  ModeloDeCobro.aPartes: ['Presupuesto y pagos', 'Hitos y facturación', 'Horas extra o trabajos fuera de alcance'],
  ModeloDeCobro.sinCobro: [],
  ModeloDeCobro.otro: ['Presupuesto y pagos'],
};

/// La hoja. [ficha] ya viene cargada: la leyó quien la abrió.
class HojaFicha extends ConsumerStatefulWidget {
  const HojaFicha({super.key, required this.alias, required this.ficha});

  final String alias;
  final FichaTexto ficha;

  @override
  ConsumerState<HojaFicha> createState() => HojaFichaState();
}

/// Las dos pestañas, con nombre en vez de 0 y 1.
const int _pestanaFicha = 0;
const int _pestanaCliente = 1;

class HojaFichaState extends ConsumerState<HojaFicha> {
  /// Qué pestaña está abierta.
  int _pestana = _pestanaFicha;

  /// Los valores de cada sección de la ficha pública, indexados por título.
  late final Map<String, TextEditingController> _camposPublica = {
    for (final e in widget.ficha.secciones.entries) e.key: TextEditingController(text: e.value),
  };

  /// Los de la privada, que llegan con la plantilla parseada aunque no exista el
  /// fichero: es lo que permite abrir el formulario justo después del alta.
  Map<String, TextEditingController> _camposPrivada = {};

  /// El modelo de cobro elegido. `null` es «todavía no lo has dicho», que es un
  /// estado distinto de «sin cobro».
  ModeloDeCobro? _cobro;

  /// La ficha privada tal como está. Se relee al cambiar de pestaña.
  FichaPrivada _privada = const FichaPrivada(alias: '');

  /// La sección abierta.
  ///
  /// ## Por qué va con `_abiertaFijada`
  /// Porque el valor «la primera que falta» **cambia** cuando llegan las
  /// secciones del bridge, y `initState` corre antes de que el provider resuelva:
  /// calcularlo una vez ahí daba dos fallos según el camino. Con una ficha
  /// completa no se abría nada —correcto— pero con una ficha recién creada se
  /// abría por el camino del plan B, que es el que se_it[] vacío.
  ///
  /// Así: mientras nadie ha tocado nada, sigue a la primera que falta aunque
  /// lleguen tarde; en cuanto tocas una, esa manda. Un `??` al pintarlo
  /// resolvería el primero pero rompería el segundo: cerrar una sección la
  /// volvería a abrir sola.
  String? _abierta;
  bool _abiertaFijada = false;

  /// Si el markdown se ha tocado a mano. A partir de ahí el generador **deja de
  /// pisarlo**, y el botón lo dice en pantalla.
  bool _markdownTocado = false;

  String _markdown = '';

  bool _guardando = false;

  /// El botón del scaffold está ocupado. Distinto de [_guardando] porque son dos
  /// acciones y pueden llegar a la vez: se está guardando una sección mientras
  /// corre el run del scaffold.
  bool _lanzando = false;

  String? _aviso;

  @override
  void initState() {
    super.initState();
    _reconstruirMarkdown();
    _cargarPrivada();
  }

  @override
  void dispose() {
    for (final c in _camposPublica.values) {
      c.dispose();
    }
    for (final c in _camposPrivada.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _cargarPrivada() async {
    try {
      final p = await ref.read(agentRepositoryProvider).readFichaPrivada(widget.alias);
      if (!mounted) return;
      final cobro = _cobroDe(p.secciones['Modelo de cobro']);
      setState(() {
        _privada = p;
        _cobro = cobro;
        _camposPrivada = {
          for (final e in p.secciones.entries) e.key: TextEditingController(text: e.value),
        };
        if (p.existe) {
          _markdown = p.texto;
          _markdownTocado = true;
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _aviso = 'No pude leer la ficha del cliente: ${mensajeDeError(e)}');
    }
  }

  /// Lee el modelo de cobro de un texto ya escrito, para no perderlo al abrir.
  ///
  /// Se busca la etiqueta exacta y no la primera línea: una persona puede haber
  /// escrito «precio cerrado, en dos pagos», que no es el valor del enum.
  ModeloDeCobro? _cobroDe(String? texto) {
    if (texto == null) return null;
    for (final m in ModeloDeCobro.values) {
      if (texto.contains(m.etiqueta)) return m;
    }
    return null;
  }

  /// La sección que está abierta ahora, o null si no hay ninguna.
  ///
  /// Mientras nadie ha tocado nada, es la primera que falte; después, la que se
  /// eligió. Ver la nota de [_abierta].
  ///
  /// Se calcula con [_siguientePendiente] y **no** con la lista de
  /// `SeccionAcordeon`: esa lista pregunta por esta getter para pintarse, así que
  /// llamarla desde aquí es recursión infinita.
  String? get _abiertaAhora {
    if (_abiertaFijada) return _abierta;
    return _siguientePendiente();
  }

  List<SeccionAcordeon> _seccionesPublica() => [
        for (final s in _seccionesDe(_pestanaFicha))
          SeccionAcordeon(
            titulo: s,
            abierta: s == _abiertaAhora,
            escrita: (_camposPublica[s]?.text ?? '').trim().isNotEmpty,
            ayuda: _ayudaPublica[s] ?? '',
          ),
      ];

  List<SeccionAcordeon> _seccionesPrivadas() => [
        for (final s in _seccionesDe(_pestanaCliente))
          SeccionAcordeon(
            titulo: s,
            abierta: s == _abiertaAhora,
            escrita: (_camposPrivada[s]?.text ?? '').trim().isNotEmpty,
            ayuda: _ayudaPrivada[s] ?? '',
            requerida: false,
          ),
      ];

  /// Las secciones que se preguntan, según la pestaña y el modelo de cobro.
  ///
  /// Ojo con `0` y `1`: en Dart son `int`, no `bool`. Pasarlos a un `int`
  /// funciona, pero escribirlos así es pedir que alguien los lea como banderas.
  List<String> _seccionesDe(int pestana) {
    final plantillas = ref.read(plantillasFichasProvider).value;
    if (pestana == _pestanaFicha) {
      final delBridge = plantillas?.de(widget.ficha.kind) ?? const <String>[];
      if (delBridge.isNotEmpty) {
        return delBridge;
      }
      // Plan B: sin la lista del bridge, se preguntan las que la puerta dice que
      // faltan. No debería verse nunca —la pantalla no monta hasta que la llamada
      // responde—, pero un `[]` haría un formulario vacío sin explicación.
      return widget.ficha.faltan;
    }
    final todas = plantillas?.privada ?? const <String>[];
    final visibles = todas.where(_aplicaConCobro).toList();
    return visibles.isEmpty ? todas : visibles;
  }

  /// Una sección se muestra si no depende del modelo de cobro, o si ese modelo
  /// la necesita. El propio campo del modelo siempre se muestra.
  bool _aplicaConCobro(String seccion) {
    if (seccion == 'Modelo de cobro') return true;
    final c = _cobro;
    if (c == null) {
      // Sin modelo elegido se muestran todas: ocultar secciones antes de saber
      // cómo se cobra esconde justo lo que hace falta para decidir.
      return true;
    }
    final propias = _seccionesPorCobro[c] ?? const [];
    if (propias.contains(seccion)) return true;
    return !const [
      'Presupuesto y pagos',
      'Hitos y facturación',
      'Fechas y plazos',
      'Horas extra o trabajos fuera de alcance',
    ].contains(seccion);
  }

  /// El documento entero, regenerado desde los campos.
  ///
  /// No lo hace si alguien tocó la caja de markdown: se respeta lo escrito.
  void _reconstruirMarkdown() {
    if (_markdownTocado) return;
    final valores = {
      for (final e in _camposPublica.entries) e.key: e.value.text,
      if (_pestana == 1)
        for (final e in _camposPrivada.entries) e.key: e.value.text,
    };
    setState(() {
      _markdown = _pestana == _pestanaFicha
          ? fichaPublica(
              kind: widget.ficha.kind,
              secciones: _seccionesDe(_pestanaFicha),
              valores: valores,
            )
          : fichaPrivada(
              secciones: _seccionesDe(_pestanaCliente), valores: valores);
    });
  }

  /// Guarda la sección abierta y abre la siguiente que falte.
  ///
  /// Devuelve si tuvo éxito porque el acordeón lo usa para decidir si avanza: si
  /// el bridge rechazó el contenido, avanzar a la siguiente sería Peer deja al
  /// usuario creyendo que se guardó.
  Future<bool> _guardarSeccion() async {
    setState(() {
      _guardando = true;
      _aviso = null;
    });
    final repo = ref.read(agentRepositoryProvider);
    try {
      if (_pestana == _pestanaFicha) {
        await repo.writeFicha(alias: widget.alias, contenido: _markdown);
      } else {
        await repo.writeFichaPrivada(alias: widget.alias, contenido: _markdownPrivada());
      }
      if (!mounted) return false;
      // Se relee para que el estado de «escrita» venga del bridge y no de este
      // archivo: el puente es quien aplica la regla de «escrito», y decidirlo
      // aquí sería una segunda copia.
      final FichaTexto leidaPublica;
      final FichaPrivada leidaPrivada;
      if (_pestana == _pestanaFicha) {
        leidaPublica = await repo.readFicha(widget.alias);
        leidaPrivada = const FichaPrivada(alias: '');
      } else {
        leidaPrivada = await repo.readFichaPrivada(widget.alias);
        leidaPublica = const FichaTexto(alias: '');
      }
      if (!mounted) return false;
      setState(() {
        _guardando = false;
        // Los controladores se reemplazan por los del bridge. No se puede
        // mutar el `text` de los viejos en un `setState`: al cambiar el mapa
        // entero, los widgets del accordón se reconstruyen con los nuevos y el
        // campo que estaba abierto sigue teniendo su cursor.
        final esFicha = _pestana == _pestanaFicha;
        final Map<String, TextEditingController> destino =
            esFicha ? _camposPublica : _camposPrivada;
        final Map<String, String> releidas =
            esFicha ? leidaPublica.secciones : leidaPrivada.secciones;
        for (final e in destino.entries) {
          e.value.dispose();
        }
        destino
          ..clear()
          ..addAll({
            for (final e in releidas.entries)
              e.key: TextEditingController(text: e.value),
          });
        _abierta = _siguientePendiente();
        _abiertaFijada = true;
      });
      refrescarAsistente(ref);
      return true;
    } catch (e) {
      if (!mounted) return false;
      setState(() {
        _guardando = false;
        _aviso = mensajeDeError(e);
      });
      return false;
    }
  }

  /// La siguiente sección sin escribir de la pestaña actual, o null si ya están
  /// todas. Abre la siguiente **de la lista visible**, que con un modelo de cobro
  /// elegido es solo el subconjunto que aplica.
  String? _siguientePendiente() {
    for (final s in _seccionesDe(_pestana)) {
      final c = _pestana == _pestanaFicha ? _camposPublica[s] : _camposPrivada[s];
      if ((c?.text ?? '').trim().isEmpty) return s;
    }
    return null;
  }

  String _markdownPrivada() {
    final conCobro = {
      ...{
        for (final e in _camposPrivada.entries)
          if (e.key != 'Modelo de cobro') e.key: e.value.text,
      },
      if (_cobro != null) 'Modelo de cobro': _cobro!.etiqueta,
    };
    return fichaPrivada(
        secciones: _seccionesDe(_pestanaCliente), valores: conCobro);
  }

  void _alternar(String titulo, bool abierta) {
    setState(() {
      _abierta = abierta ? titulo : null;
      _abiertaFijada = true;
    });
  }

  @override
  Widget build(BuildContext context) {
    final plantillas = ref.watch(plantillasFichasProvider);
    return SafeArea(
      child: Padding(
        // El teclado tapa el botón de guardar si no se suma el inset: ya se
        // perdía medio guardado en la hoja anterior.
        padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            _Pestanas(
              indice: _pestana,
              privadaVacia: _privada.sinRellenar,
              onCambiar: _cambiarPestana,
            ),
            Flexible(
              child: plantillas.when(
                loading: () => const Padding(
                  padding: EdgeInsets.all(24),
                  child: Text('Preguntando qué secciones tiene esta ficha…',
                      style: TextStyle(
                          fontFamily: AegisPalette.mono,
                          fontSize: 11,
                          color: AegisPalette.fgFaint)),
                ),
                error: (e, _) => Padding(
                  padding: const EdgeInsets.all(24),
                  child: Text('No pude preguntar qué secciones hay: ${mensajeDeError(e)}',
                      style: const TextStyle(
                          fontFamily: AegisPalette.mono,
                          fontSize: 11,
                          color: AegisPalette.danger)),
                ),
                data: (_) => _contenido(),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _contenido() {
    final secciones =
        _pestana == _pestanaFicha ? _seccionesPublica() : _seccionesPrivadas();
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
      children: [
        if (_pestana == _pestanaFicha)
          _Titulo(alias: widget.alias, kind: widget.ficha.kind)
        else
          const _AvisoPrivada(),
        if (_pestana == _pestanaCliente && _cobro == null) ...[
          _SelectorCobro(
            elegido: _cobro,
            onElegir: (m) => setState(() {
              _cobro = m;
              _abierta = 'Modelo de cobro';
              _abiertaFijada = true;
            }),
          ),
          const SizedBox(height: 10),
        ],
        AcordeonSecciones(
          secciones: secciones,
          guardando: _guardando,
          onAlternar: _alternar,
          onGuardar: _guardarSeccion,
          campoDe: (titulo) => _campo(titulo),
        ),
        const SizedBox(height: 14),
        _CajaMarkdown(
          valor: _markdown,
          tocado: _markdownTocado,
          onCambiado: (v) => setState(() {
            _markdown = v;
            _markdownTocado = true;
          }),
        ),
        if (_aviso != null) ...[
          const SizedBox(height: 8),
          Text(_aviso!,
              style: const TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 11,
                  color: AegisPalette.danger)),
        ],
        if (_pestana == _pestanaFicha) ...[
          const SizedBox(height: 16),
          _BotonScaffold(
            completa: _fichaCompleta,
            ocupado: _lanzando,
            onLanzar: _queAegisLoCree,
          ),
        ],
      ],
    );
  }

  /// Si la ficha tiene todo lo que la puerta exige.
  ///
  /// Se calcula con la lista de secciones del bridge, no con `faltan`: tras un
  /// guardado el bridge ya no manda `faltan`, y quedarse con el valor viejo
  /// dejaría el botón apagado con la ficha ya completa.
  bool get _fichaCompleta {
    final secciones = _seccionesDe(_pestanaFicha);
    if (secciones.isEmpty) return false;
    return _siguientePendienteEn(_pestanaFicha) == null;
  }

  String? _siguientePendienteEn(int pestana) {
    for (final s in _seccionesDe(pestana)) {
      final c = pestana == _pestanaFicha ? _camposPublica[s] : _camposPrivada[s];
      if ((c?.text ?? '').trim().isEmpty) return s;
    }
    return null;
  }

  /// Lanza el run del scaffold.
  ///
  /// ## Lo que este botón NO hace, y por qué está escrito aquí
  /// No esquiva ninguna puerta. Lo que se lanza es un **run**, y lo que el run
  /// haga dentro sigue pasando por `autonomy.decide()`: escribir en el proyecto
  /// exige que esté marcado (`con_permiso`), y `project_create` es nivel 3 en los
  /// tres modos. O sea: Aegis va a parar pidiendo tu OK en cuanto toque algo que
  /// importe, y ese OK lo apruebas en «Ahora» con el motivo a la vista.
  ///
  /// Lo único que quita este botón es el paso de apretar «ejecutar». Que se lance
  /// solo no significa que escriba solo.
  Future<void> _queAegisLoCree() async {
    setState(() {
      _lanzando = true;
      _aviso = null;
    });
    final repo = ref.read(agentRepositoryProvider);
    try {
      // El proyecto queda elegido para que la pantalla de «Ahora» lo traiga ya
      // puesto, y para que el run vaya con su ficha y sus lecciones.
      ref.read(selectedProjectProvider.notifier).select(widget.alias);
      await repo.startAutopilot(
        prompt: _encargoDeScaffold(),
        project: widget.alias,
        maxSteps: 24,
        instructions: _instruccionesDeScaffold(),
        // `verificar: false` a propósito en el **primer** run, y no por descuido:
        // el proyecto está recién creado y no tiene scaffold, así que su
        // verificador casi seguro falla y el run se cortaría en el primer paso
        // por un motivo que no es del trabajo. A partir del segundo run ya hay
        // código contra el que correr.
        verify: false,
      );
      if (!mounted) return;
      setState(() {
        _lanzando = false;
        _aviso = null;
      });
      Navigator.of(context).pop(true);
      refrescarAsistente(ref);
      // El run vive en «Ahora», que es donde se ve la traza y dónde caen las
      // aprobaciones. Abrirla es lo útil: el run ya está corriendo y sin mirar no
      // se ve ni su primer paso.
      ref.read(seccionActualProvider.notifier).abrir('ahora');
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _lanzando = false;
        _aviso = 'No pude lanzar el run: ${mensajeDeError(e)}';
      });
    }
  }

  /// El encargo, en una frase que el modelo no puede malinterpretar.
  ///
  /// Se escribe aquí y no se deja que Aegis lo figure: un 7B al que se le pide
  /// «crea la base» elige qué significa base, y el trabajo que importa es el
  /// menos ambiguo de todos.
  String _encargoDeScaffold() {
    final b = StringBuffer()
      ..writeln('Crea la base del proyecto \'${widget.alias}\'.')
      ..writeln()
      ..writeln('La ficha de este proyecto ya está escrita y la tienes delante. '
          'Lo que hay que hacer es lo mínimo que hace falta para que el '
          'proyecto exista y se pueda verificar:')
      ..writeln()
      ..writeln('- Un repositorio con la estructura que use el stack declarado.')
      ..writeln('- El mínimo para que corran los comandos de verificación.')
      ..writeln('- Un README que diga qué es y cómo se prueba.')
      ..writeln()
      ..writeln('No añadas funcionalidad que no esté en la ficha, y no decidas '
          'nada comercial: el precio y las fechas no se tocan. Si la ficha no '
          'aclara algo del stack, léete lo que haya y **pregunta**, en vez de '
          'elegir por tu cuenta.');
    return b.toString();
  }

  String _instruccionesDeScaffold() {
    final verificador = _seccionesPublica()
        .firstWhere((s) => s.titulo == 'Cómo se verifica',
            orElse: () => const SeccionAcordeon(
                titulo: '', abierta: false, escrita: false))
        .escrita;
    return verificador
        ? 'El proyecto tiene verificador declarado en la ficha: úsalo para comprobar '
            'tu trabajo en cada paso. Si un comando no existe todavía, créalo.'
        : 'Este proyecto no tiene verificador declarado todavía. Escribe uno que '
            'funcione y déjalo anotado: sin él no se puede dar permiso de escritura.';
  }

  Widget _campo(String titulo) {
    final c = _pestana == _pestanaFicha
        ? _camposPublica[titulo]
        : _camposPrivada[titulo];
    if (c == null) return const SizedBox.shrink();
    return TextField(
      controller: c,
      maxLines: 6,
      minLines: 3,
      style: const TextStyle(
          fontFamily: AegisPalette.mono, fontSize: 12, height: 1.5, color: AegisPalette.fg),
      decoration: InputDecoration(
        hintText: titulo == 'Modelo de cobro' ? 'elige arriba' : '…',
        isDense: true,
      ),
      onChanged: (_) => setState(() {}),
    );
  }

  void _cambiarPestana(int i) {
    setState(() {
      _pestana = i;
      _markdownTocado = false;
      _markdown = '';
      // Al cambiar de pestaña no se fija: la nueva vuelve a abrir su primera
      // pendiente, que es lo que espera quien cambia para ver lo que falta.
      _abierta = null;
      _abiertaFijada = false;
    });
    _reconstruirMarkdown();
  }
}

/// El botón de «que Aegis lo cree».
///
/// ## Por qué dice lo que hace, en la propia etiqueta
/// Porque la primera tool del run choca con `project_create`, que es nivel 3, y
/// Aegis **para y te pregunta**. Un botón que dijera solo «crear» haría pensar
/// que el trabajo empieza sin más; este deja claro que hay un paso por delante y
/// que lo decides tú. El motivo está también en el código, que es donde se
/// pregunta por qué no escribe solo.
class _BotonScaffold extends StatelessWidget {
  const _BotonScaffold({
    required this.completa,
    required this.ocupado,
    required this.onLanzar,
  });

  final bool completa;
  final bool ocupado;
  final VoidCallback onLanzar;

  @override
  Widget build(BuildContext context) {
    if (!completa) {
      return const Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('—  ',
              style: TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 11,
                  color: AegisPalette.fgFaint)),
          Expanded(
            child: Text(
              'Termina la ficha para poder encargar el scaffold. La puerta del '
              'bridge no deja trabajar en un proyecto que no sabe para qué es.',
              style: TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 10.5,
                  height: 1.5,
                  color: AegisPalette.fgFaint),
            ),
          ),
        ],
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        FilledButton(
          onPressed: ocupado ? null : onLanzar,
          style: FilledButton.styleFrom(
            backgroundColor: AegisPalette.brand,
            foregroundColor: AegisPalette.bg0,
          ),
          child: Text(ocupado ? 'Lanzando…' : 'Que Aegis lo cree'),
        ),
        const SizedBox(height: 6),
        const Text(
          'Aegis va a parar a pedirte OK antes de crear nada: esta acción no '
          'es automática.',
          style: TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 10,
              height: 1.5,
              color: AegisPalette.fgFaint),
        ),
      ],
    );
  }
}

class _Pestanas extends StatelessWidget {
  const _Pestanas({
    required this.indice,
    required this.privadaVacia,
    required this.onCambiar,
  });

  final int indice;
  final bool privadaVacia;
  final void Function(int) onCambiar;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 6),
      child: Row(
        children: [
          Expanded(
            child: _Pestana(
              texto: 'FICHA',
              activa: indice == 0,
              onTap: () => onCambiar(0),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: _Pestana(
              texto: privadaVacia ? 'CLIENTE ·' : 'CLIENTE ✓',
              activa: indice == _pestanaCliente,
              aviso: 'no se versiona',
              onTap: () => onCambiar(_pestanaCliente),
            ),
          ),
        ],
      ),
    );
  }
}

class _Pestana extends StatelessWidget {
  const _Pestana({
    required this.texto,
    required this.activa,
    required this.onTap,
    this.aviso = '',
  });

  final String texto;
  final bool activa;
  final String aviso;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 9),
        decoration: BoxDecoration(
          color: activa ? AegisPalette.bg2 : Colors.transparent,
          border: Border(
            bottom: BorderSide(
                color: activa ? AegisPalette.brand : AegisPalette.line, width: activa ? 2 : 1),
          ),
        ),
        child: Column(
          children: [
            Text(
              texto,
              style: TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 11,
                letterSpacing: 1.5,
                color: activa ? AegisPalette.fg : AegisPalette.fgFaint,
              ),
            ),
            if (aviso.isNotEmpty)
              Text(
                aviso,
                style: const TextStyle(
                    fontFamily: AegisPalette.mono,
                    fontSize: 8.5,
                    color: AegisPalette.fgFaint),
              ),
          ],
        ),
      ),
    );
  }
}

class _Titulo extends StatelessWidget {
  const _Titulo({required this.alias, required this.kind});

  final String alias;
  final String kind;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Text(
        'FICHA · $alias${kind.isEmpty ? '' : ' · $kind'}',
        style: const TextStyle(
          fontFamily: AegisPalette.display,
          fontSize: 12,
          letterSpacing: 2,
          color: AegisPalette.fgFaint,
        ),
      ),
    );
  }
}

class _AvisoPrivada extends StatelessWidget {
  const _AvisoPrivada();

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(9),
      decoration: BoxDecoration(
        border: Border.all(color: AegisPalette.warn.withValues(alpha: .35)),
        color: AegisPalette.warn.withValues(alpha: .06),
      ),
      child: const Text(
        'Esto NO se versiona. Vive en bridge/fichas-privadas/, fuera de git, '
        'porque es información del cliente. Entra en el prompt de Aegis marcado '
        'como «no lo nombres ni lo repitas».',
        style: TextStyle(
            fontFamily: AegisPalette.mono, fontSize: 10, height: 1.5, color: AegisPalette.warn),
      ),
    );
  }
}

class _SelectorCobro extends StatelessWidget {
  const _SelectorCobro({required this.elegido, required this.onElegir});

  final ModeloDeCobro? elegido;
  final void Function(ModeloDeCobro) onElegir;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        border: Border.all(color: AegisPalette.line),
        color: AegisPalette.bg1,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text(
            '¿Cómo se cobra?',
            style: TextStyle(
                fontFamily: AegisPalette.mono, fontSize: 11, color: AegisPalette.fg),
          ),
          const SizedBox(height: 4),
          const Text(
            'Elige uno y solo se preguntará lo que ese modelo necesita. '
            'Aegis nunca pone un precio: eso lo escribes tú.',
            style: TextStyle(
                fontFamily: AegisPalette.mono,
                fontSize: 10,
                height: 1.5,
                color: AegisPalette.fgFaint),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final m in ModeloDeCobro.values)
                ChoiceChip(
                  label: Text(m.etiqueta,
                      style: const TextStyle(fontFamily: AegisPalette.mono, fontSize: 10.5)),
                  selected: elegido == m,
                  onSelected: (_) => onElegir(m),
                  tooltip: m.ayuda,
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _CajaMarkdown extends StatefulWidget {
  const _CajaMarkdown({required this.valor, required this.tocado, required this.onCambiado});

  final String valor;
  final bool tocado;
  final void Function(String) onCambiado;

  @override
  State<_CajaMarkdown> createState() => _CajaMarkdownState();
}

class _CajaMarkdownState extends State<_CajaMarkdown> {
  late final TextEditingController _c = TextEditingController(text: widget.valor);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            const Text(
              'MARKDOWN · lo que se guarda',
              style: TextStyle(
                  fontFamily: AegisPalette.mono,
                  fontSize: 9.5,
                  letterSpacing: 1,
                  color: AegisPalette.fgFaint),
            ),
            const Spacer(),
            if (widget.tocado)
              const Text(
                'editado a mano',
                style: TextStyle(
                    fontFamily: AegisPalette.mono, fontSize: 9, color: AegisPalette.warn),
              ),
          ],
        ),
        const SizedBox(height: 4),
        TextField(
          controller: _c,
          maxLines: 10,
          minLines: 4,
          style: const TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: 10,
              height: 1.4,
              color: AegisPalette.fgFaint),
          decoration: const InputDecoration(isDense: true),
          onChanged: widget.onCambiado,
        ),
      ],
    );
  }
}