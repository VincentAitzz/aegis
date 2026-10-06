// ¿En qué punto se decide la URL final de una llamada: el baseUrl o la ruta
// absoluta?
//
// ## Por qué este test existe
// El interceptor que resuelve el bridge reescribe `baseUrl`. Pero las 35 llamadas
// del repositorio piden una URL **absoluta** (`${config.httpBase}/health`), y en
// Dio una ruta absoluta gana al `baseUrl`: la URL final sería la compilada y el
// discovery no serviría para nada, sin error ni aviso.
//
// Ese fallo es invisible: la app seguiría funcionando en la red de la casa si la
// IP compilada sigue viva, y «no funciona» solo aparecería cuando esa IP dejara
// de existir, que es justo cuando el discovery era la solución. Un interceptor
// que no hace nada es peor que no tenerlo, porque parece que sí.
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late String? vista;

  Dio dio(String baseUrl) => Dio(BaseOptions(baseUrl: baseUrl))..interceptors.add(
        InterceptorsWrapper(onRequest: (o, handler) {
          vista = o.uri.toString();
          handler.reject(DioException(requestOptions: o, type: DioExceptionType.cancel));
        }),
      );

  test('con ruta absoluta, el baseUrl NO manda', () async {
    // El caso que importa: así es como están escritas las llamadas reales.
    final d = dio('http://RESUELTO:8000');
    d.interceptors.add(InterceptorsWrapper(onRequest: (o, handler) {
      vista = o.uri.toString();
      // Corta aquí: lo que se prueba es la URL que se compone, no que alguien
      // conteste. Sin esto el test espera al timeout de conexión y el fallo dice
      // «timeout», que no es lo que se está probando.
      handler.reject(DioException(requestOptions: o, type: DioExceptionType.cancel));
    }));
    try {
      await d.get<Map<String, dynamic>>('http://COMPILED:8000/health');
    } on DioException {
      // esperado: cortamos a propósito
    }
    expect(vista, 'http://compiled:8000/health', // Dio baja el host a minúsculas
        reason: 'la ruta absoluta gana: reescribir el baseUrl no basta');
  });

  test('con ruta relativa, el baseUrl sí manda', () async {
    // Por eso la solución es quitar el `${config.httpBase}` de las llamadas y
    // dejar solo la ruta: el destino lo pone el interceptor.
    final d = dio('http://RESUELTO:8000');
    d.interceptors.add(InterceptorsWrapper(onRequest: (o, handler) {
      vista = o.uri.toString();
      handler.reject(DioException(requestOptions: o, type: DioExceptionType.cancel));
    }));
    try {
      await d.get<Map<String, dynamic>>('/health');
    } on DioException {
      // esperado
    }
    expect(vista, 'http://resuelto:8000/health'); // idem
  });
}