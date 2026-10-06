/// Genera el markdown de una ficha a partir de los campos del formulario.
///
/// ## Por qué existe, y por qué está aquí y no en el bridge
/// Porque el markdown tiene que salir de algo **determinista**. Se comprobó que
/// un modelo pequeño copiando un texto literal se come los `---` del frontmatter
/// (A-016), y el `---` es lo que declara el `kind`: sin él, la puerta rechaza la
/// ficha y no hay forma de saber por qué. Un `StringBuffer` no puede perder un
/// `---`, y además es idempotente, que es lo que hace que guardar dos veces no
/// destroce el fichero.
///
/// ## Lo que este generador NO hace
/// **No decide qué secciones existen.** Esa lista sale del bridge
/// (`GET /fichas/plantillas`), y llega como argumento. Copiarla aquí sería
/// duplicar `fichas.SECCIONES_POR_TIPO` en Dart: el día que el bridge añadiese
/// una sección, esta app preguntaría las antiguas y la puerta pediría la nueva,
/// sin que nada lo explicara.
///
/// ## Y lo que no borra
/// Reescribe el documento entero, pero conserva **lo que no viene de los
/// campos**: una sección que el formulario no conoce, o una línea que alguien
/// escribió a mano en la caja de markdown. Perder texto en un guardado es la
/// forma más rápida de que alguien deje de usar el formulario.
library;

/// El frontmatter de una ficha, y el título que la acompaña.
///
/// El `kind` va **siempre**, incluso vacío: es lo que la puerta lee para saber
/// qué secciones exigir, y omitirlo produce un 422 en la puerta en vez de un
/// error visible en la pantalla.
String frontmatter(String kind, {String titulo = ''}) {
  final b = StringBuffer()..writeln('---');
  b.writeln('kind: ${kind.trim()}');
  if (titulo.trim().isNotEmpty) {
    b.writeln('titulo: ${_comillas(titulo.trim())}');
  }
  b.writeln('---');
  b.writeln();
  b.writeln('# ${titulo.trim().isEmpty ? 'Ficha · ${kind.trim()}' : titulo.trim()}');
  b.writeln();
  return b.toString();
}

/// El documento entero de una ficha pública.
///
/// [secciones] es la lista **en orden** que envía el bridge, y [valores] el mapa
/// de lo que el usuario escribió. Un valor vacío o con solo espacios no se
/// escribe: una sección en blanco cuenta como no escrita (la puerta lo trata
/// como pendiente), así que dejar un hueco es lo honesto y lo que hace que el
/// formulario siga preguntando.
///
/// [extra] son secciones que no están en [secciones] y aun así hay que
/// conservar: lo que alguien escribió a mano o lo que una versión anterior del
/// bridge dejó ahí. Se anexan al final, y no se pisan entre sí.
String fichaPublica({
  required String kind,
  required List<String> secciones,
  required Map<String, String> valores,
  String titulo = '',
  Map<String, String> extra = const {},
}) {
  final b = StringBuffer()..write(frontmatter(kind, titulo: titulo));
  for (final s in secciones) {
    final v = (valores[s] ?? '').trim();
    if (v.isEmpty) {
      continue;
    }
    b.writeln('## $s');
    b.writeln();
    b.writeln(v);
    b.writeln();
  }
  for (final e in extra.entries) {
    if (e.value.trim().isEmpty) {
      continue;
    }
    b.writeln('## ${e.key}');
    b.writeln();
    b.writeln(e.value.trim());
    b.writeln();
  }
  return _sinColaEnBlanco(b.toString());
}

/// El documento entero de la ficha privada.
///
/// Sin `kind`: la privada no lo tiene, porque no hay puerta que la lea y el tipo
/// lo decide la pública. Ponerlo sería inventar un campo que nada usa.
String fichaPrivada({
  required List<String> secciones,
  required Map<String, String> valores,
  Map<String, String> extra = const {},
}) {
  final b = StringBuffer()
    ..writeln('---')
    ..writeln('tipo: privada')
    ..writeln('---')
    ..writeln()
    ..writeln('# Ficha privada · contexto comercial')
    ..writeln();
  for (final s in secciones) {
    final v = (valores[s] ?? '').trim();
    if (v.isEmpty) {
      continue;
    }
    b.writeln('## $s');
    b.writeln();
    b.writeln(v);
    b.writeln();
  }
  // De aquí en adelante, lo que el formulario no conoce pero el fichero tiene.
  for (final e in extra.entries) {
    if (e.value.trim().isEmpty) {
      continue;
    }
    b.writeln('## ${e.key}');
    b.writeln();
    b.writeln(e.value.trim());
    b.writeln();
  }
  return _sinColaEnBlanco(b.toString());
}

/// Las secciones que el puente devolvió y que el formulario no tiene campos.
///
/// Son las que hay que **conservar**: si el generador las escribiera vacías,
/// desaparecerían del fichero el día que alguien guardara desde el formulario.
/// Este es el mecanismo que hace segura la caja de markdown.
Map<String, String> seccionesAConservar({
  required List<String> conocidas,
  required Map<String, String> existentes,
}) {
  final fuera = <String, String>{};
  for (final e in existentes.entries) {
    if (!conocidas.contains(e.key)) {
      fuera[e.key] = e.value;
    }
  }
  return fuera;
}

/// Cuántas secciones obligatorias quedan sin escribir.
///
/// Cuenta solo las de [secciones]: la privada no tiene obligatorias a propósito,
/// y mandar un contador de secciones privadas haría creer que hay que rellenar
/// las doce.
int pendientes(int escritas, int secciones) => secciones - escritas;

/// Une los valores de un modelo de cobro elegido.
///
/// El modelo se escribe como la primera línea de su sección, para que Aegis lo
/// lea sin tener que deducirlo del resto. No lleva importe: el precio lo pone la
/// persona, y Aegis tiene prohibido inventarlo.
String lineaModeloDeCobro(String etiqueta) => etiqueta;

/// Un valor con `"` necesita comillas en el frontmatter; sin esto, un título con
/// comillas produce un frontmatter que no parsea y la ficha queda sin tipo.
String _comillas(String v) {
  if (v.contains('"') || v.contains("'") || v.contains(':')) {
    return '"${v.replaceAll('"', r'\"')}"';
  }
  return v;
}

/// Quita la racha de líneas en blanco del final.
///
/// No es estética: `_escrito` del bridge parte el cuerpo por líneas y una
/// sección con tres líneas vacías al final se sigue considerando escrita, pero el
/// fichero resultante no es estable —dos guardados seguidos producirían
/// documentos distintos si el contenido creciera—.
String _sinColaEnBlanco(String texto) {
  final lineas = texto.split('\n');
  while (lineas.isNotEmpty && lineas.last.trim().isEmpty) {
    lineas.removeLast();
  }
  return '${lineas.join('\n')}\n';
}