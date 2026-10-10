// Sembrar el «ya preguntado» para las pruebas que no son de la primera vez.
//
// ## Por qué hace falta, y por qué no es una comodidad
// Porque el registro empieza **vacío** en cada test, y vacío significa «primera
// vez»: la app enseña el pase de permisos. Eso es correcto, pero deja sin poder
// probar lo que estas pruebas dicen probar —el arranque, el shell, la
// navegación— porque delante se interpone una pantalla que aún no dice nada.
//
// La primera vez **no se salta**: tiene su propio test, en
// `primera_vez_test.dart`, y `app_smoke_test.dart` monta la app **sin** sembrar
// justamente para comprobar que el pase aparece cuando toca.
import 'package:aegis_console/core/permisos.dart';

/// El registro entero, como si el usuario ya hubiera pasado por el pase.
///
/// No es un override del provider: `AegisApp` recibe el `Set` resuelto, así que
/// aquí no hay nada que sobrescribir. Es el mismo dato, por el camino que la
/// appReally usa.
Set<String> yaPreguntados() => {
      for (final p in permisosDePrimeraVez) p.id,
    };
