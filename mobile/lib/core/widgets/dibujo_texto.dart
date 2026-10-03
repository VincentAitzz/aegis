/// El contorno de un dibujo de texto, calculado.
///
/// ## Por qué se calcula y no se declara
///
/// Lo obvio es escribir el arte a mano marcando qué caracteres son del borde:
/// un `1` en el borde y un `0` dentro. Se descarta por tres razones, en orden de
/// peso:
///
/// 1. **Es mantenimiento.** Un arte de 77 × 65 celdas son 5000 marcas que hay que
///    upkeepar. Tocas una fila y el dibujo se rompe, y no hay forma de saber
///    qué fila has tocado.
/// 2. **Solo sirve para un arte.** El día que entre otra calavera, hay que
///    volver a las 5000 marcas.
/// 3. **Se puede comprobar.** La regla «pocos vecinos = borde» se puede testear
///    con un dibujo de 5 líneas donde la respuesta se sabe a ojo. Una lista de
///    marcas no se puede comprobar, solo mirar.
///
/// ## La regla
///
/// Un carácter es **contorno** si en la ventana de 3×3 que lo rodea hay pocos
/// compañeros: dentro de la masa densa el vecindario está lleno (8), y en el borde
/// rasgado —donde el texto se acaba— está casi vacío.
///
/// El umbral está en [_umbralVecinos] y no es un número mágico: se eligió
/// mirando este arte, y el test de banda lo vigila para que siga teniendo
/// sentido. Si algún día el arte cambia tanto que el contorno se comiera el
/// interior, la banda se sale y el test lo dice en vez de dejarlo pasar.
library;

/// Un carácter con este vecindario o menos es del borde.
///
/// ## De dónde sale el 6
/// Medido sobre el arte real, no estimado. De 3732 celdas con texto, **3434
/// tienen los 8 vecinos**: la calavera es un bloque macizo, así que casi todo es
/// interior y el borde es una franja. La cola es esta:
///
/// ```
/// vecinos:  2    3    4    5    6    7    8
/// celdas:   1    7   49  118   50   73 3434
/// ```
///
/// Con umbral 4 el contorno es el 1,5 % y **no se ve**: son las cinco letras
/// sueltas de la frente. Con 7, el 8 %. Con 8, el 100 % — y el glifo entero se
/// pinta del color de estado, que es el otro extremo del mismo fallo.
///
/// El 6 deja una franja de unas dos letras en cada borde de línea, que es lo que
/// se ve a 5 px por renglón y lo que dibuja la silueta.
const int _umbralVecinos = 6;

/// Qué carácter hay en cada celda del dibujo, y cuáles son del borde.
///
/// Devuelve dos rejillas de la misma forma que [arte]: [interior] tiene `true`
/// donde va el color de relleno y [contorno] donde va el de estado. Son
/// **inmutables y se calculan una vez**, no en cada `build`: son 77 × 65 celdas,
/// y hacerlo en cada frame con el glifo latiendo sería trabajo por frame para un
/// resultado que no cambia nunca.
class DibujoTexto {
  DibujoTexto(this.lineas) {
    final alto = lineas.length;
    final ancho = lineas.fold<int>(0, (m, l) => l.length > m ? l.length : m);
    _interior = List.generate(alto, (_) => List<bool>.filled(ancho, false));
    _contorno = List.generate(alto, (_) => List<bool>.filled(ancho, false));

    for (var f = 0; f < alto; f++) {
      final linea = lineas[f];
      for (var c = 0; c < linea.length; c++) {
        if (linea[c] == ' ') continue;
        final vecinos = _vecinos(lineas, f, c);
        if (vecinos <= _umbralVecinos) {
          _contorno[f][c] = true;
        } else {
          _interior[f][c] = true;
        }
      }
    }
  }

  final List<String> lineas;
  late final List<List<bool>> _interior;
  late final List<List<bool>> _contorno;

  int get alto => lineas.length;
  int get ancho => _interior.isEmpty ? 0 : _interior.first.length;

  /// Los caracteres de relleno, con huecos donde va el contorno.
  ///
  /// Se devuelve como **lineas de texto** y no como rejilla de bool, porque lo
  /// que se pinta es un `Text`: una capa de texto por color. Pintar 5000
  /// `TextSpan` uno por carácter sería 5000 objetos por frame.
  List<String> get textoInterior => _componga(_interior);

  /// Los del borde, con huecos donde va el interior. Se pinta encima.
  List<String> get textoContorno => _componga(_contorno);

  /// Cuántos caracteres hay, y cuántos son del borde.
  ///
  /// Lo usa el test de banda: un arte donde el 90 % es borde no es una calavera
  /// con el borde resaltado, es un contorno gigante, y pasa desapercibido.
  int get celdas => _interior.fold<int>(
      0, (m, l) => m + l.where((b) => b).length);
  int get celdasContorno =>
      _contorno.fold<int>(0, (m, l) => m + l.where((b) => b).length);

  /// La fracción del dibujo que es contorno.
  double get fraccionContorno =>
      celdas == 0 ? 0 : celdasContorno / celdas;

  List<String> _componga(List<List<bool>> capa) {
    final salida = <String>[];
    for (var f = 0; f < lineas.length; f++) {
      final bucle = StringBuffer();
      for (var c = 0; c < ancho; c++) {
        bucle.write(capa[f][c] ? lineas[f].padRight(ancho).substring(c, c + 1) : ' ');
      }
      salida.add(bucle.toString());
    }
    return salida;
  }

  /// Compañeros de tinta en la ventana 3×3, sin contarse a sí mismo.
  static int _vecinos(List<String> lineas, int f, int c) {
    var n = 0;
    for (var df = -1; df <= 1; df++) {
      for (var dc = -1; dc <= 1; dc++) {
        if (df == 0 && dc == 0) continue;
        final y = f + df;
        final x = c + dc;
        if (y < 0 || y >= lineas.length) continue;
        final l = lineas[y];
        if (x < 0 || x >= l.length) continue;
        if (l[x] != ' ') n++;
      }
    }
    return n;
  }
}
