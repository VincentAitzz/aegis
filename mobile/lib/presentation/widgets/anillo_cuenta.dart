/// El anillo de cuenta atrás.
///
/// ## Por qué un `CustomPaint` y no un `CircularProgressIndicator`
/// Porque el `CircularProgressIndicator` de Material es una vuelta completa con
/// su grosor y su tapa, y para un TOTP lo que se necesita es **una barra de 30
/// segundos que se vacía**, no un spinner. Se puede hacer con un `LinearProgressIndicator`
/// en horizontal, que es más simple —y por eso se miró— pero el anillo se lee
/// junto al número sin ocupar una fila más, y con seis cuentas en pantalla la
/// altura es lo primero que escasea.
///
/// ## Por qué el trazo se dibuja al revés
/// Se dibuja empezando arriba y avanzando en sentido horario, descontando el
/// hueco conforme se agota el tiempo. La alternativa —dibujar el arco que
/// queda— obliga a distinguir un arco de 359° de uno de 1°, y se ve un salto
/// al final de la vuelta. Restando el hueco, la punta avanza siempre igual y
/// el final se ve como una mella, que es lo que es.
library;

import 'dart:math';

import 'package:flutter/material.dart';

import '../../core/theme/aegis_palette.dart';

class AnilloCuentaAtras extends StatelessWidget {
  const AnilloCuentaAtras({
    super.key,
    required this.fraccion,
    this.periodo = 30,
    this.diametro = 46,
    this.grosor = 3,
    this.color = AegisPalette.brand,
  });

  /// De 1 (ventana entera) a 0 (agotada). Por debajo de 0.02 se dibuja igual,
  /// porque un anillo en cero es un anillo que no está.
  final double fraccion;

  /// Cuántos segundos dura la ventana de esta cuenta.
  ///
  /// ## Por qué no son 30 fijos
  /// Porque hay cuentas de 60 (Outlook) y de 45. Con un 30 escrito a fuego, una
  /// cuenta de 60 **siempre** ponía «30» en el centro del anillo y se vaciaba a
  /// la mitad de lo que le tocaba. El número era mentira y no había forma de que
  /// el usuario lo notara, porque un número fijo parece un contador.
  ///
  /// Es un parámetro y no una constante por eso: la cuenta es quien sabe su
  /// periodo, y el widget solo dibuja.
  final int periodo;

  final double diametro;
  final double grosor;

  /// El color cambia con el tiempo: celeste mientras queda, ámbar al final.
  ///
  /// ## Por qué el color dice «queda poco»
  /// Porque el número **no cambia** durante los 30 segundos: el mismo código
  /// sirve hasta el final. Sin una señal, alguien que llega al final de la
  /// ventana copia un código que ya no vale y no entiende por qué el login
  /// falla. El color es la aviso, y llega antes que leer la cuenta atrás.
  final Color color;

  /// El color que corresponde a esta fracción.
  static Color colorPara(double fraccion) {
    if (fraccion > 0.34) return AegisPalette.brand;
    if (fraccion > 0.17) return AegisPalette.warn;
    return AegisPalette.danger;
  }

  @override
  Widget build(BuildContext context) {
    final f = fraccion.clamp(0.0, 1.0);
    return SizedBox(
      width: diametro,
      height: diametro,
      child: CustomPaint(
        painter: _AnilloPainter(
          fraccion: f,
          grosor: grosor,
          color: color,
        ),
        // El número va dentro del anillo: es lo que se mira, y ponerlo al lado
        // obliga a la vista a saltar de un sitio a otro en cada cuenta.
        child: Center(
          child: Text(
            '${(f * periodo).ceil()}',
            style: TextStyle(
              fontFamily: AegisPalette.mono,
              fontSize: diametro * 0.32,
              color: AegisPalette.fgDim,
            ),
          ),
        ),
      ),
    );
  }
}

class _AnilloPainter extends CustomPainter {
  const _AnilloPainter({
    required this.fraccion,
    required this.grosor,
    required this.color,
  });

  final double fraccion;
  final double grosor;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final centro = Offset(size.width / 2, size.height / 2);
    final radio = (size.width - grosor) / 2;
    final caja = Rect.fromCircle(center: centro, radius: radio);

    // El resto de la vuelta, siempre el mismo: da la forma del anillo aunque
    // falte todo el tiempo.
    final fondo = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = grosor
      ..color = AegisPalette.line
      ..strokeCap = StrokeCap.round;
    canvas.drawCircle(centro, radio, fondo);

    // El hueco se dibuja encima. Se empieza arriba (`-pi/2`) y se avanza en
    // sentido horario, que es como se lee el paso del tiempo.
    final hueco = (1 - fraccion) * 2 * pi;
    if (hueco <= 0) return;
    final trazo = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = grosor
      ..color = color
      ..strokeCap = StrokeCap.round;
    canvas.drawArc(caja, -pi / 2 + hueco, -hueco, false, trazo);
  }

  @override
  bool shouldRepaint(_AnilloPainter anterior) =>
      anterior.fraccion != fraccion ||
      anterior.color != color ||
      anterior.grosor != grosor;
}

/// El código grande, en grupos.
///
/// ## Por qué grupos de tres
/// Porque son seis u ocho dígitos y en un bloque corrido hay que contar
/// posiciones para no saltarse uno al copiar. `123 456` se lee entero; en
/// tipografía monoespaciada el hueco hace de guía.
class CodigoGrande extends StatelessWidget {
  const CodigoGrande({
    super.key,
    required this.codigo,
    this.tamanio = 30,
    this.color,
  });

  final String codigo;
  final double tamanio;
  final Color? color;

  /// Inserta el espacio cada tres dígitos desde la izquierda.
  static String agrupar(String codigo) {
    if (codigo.length <= 3) return codigo;
    final buffer = StringBuffer();
    for (var i = 0; i < codigo.length; i++) {
      if (i > 0 && i % 3 == 0) buffer.write(' ');
      buffer.write(codigo[i]);
    }
    return buffer.toString();
  }

  @override
  Widget build(BuildContext context) {
    return Text(
      agrupar(codigo),
      style: TextStyle(
        fontFamily: AegisPalette.mono,
        fontSize: tamanio,
        height: 1.1,
        letterSpacing: 2,
        color: color ?? AegisPalette.fg,
      ),
    );
  }
}