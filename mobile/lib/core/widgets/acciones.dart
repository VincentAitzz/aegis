/// Lo que es una acción de esta app.
///
/// ## Por qué esto **no** es `VoidCallback`
/// Porque `VoidCallback` es `void Function()`, y en Dart el tipo de retorno
/// `void` **descarta cualquier valor**: `() => _escanear` —que devuelve una
/// referencia al método en vez de llamarlo— es asignable a `void Function()`
/// sin que el analizador diga nada. Comprobado.
///
/// Eso pasó de verdad. Los dos botones principales de la pantalla de claves no
/// hacían nada: `flutter analyze` daba 0 issues y los tests pasaban, porque solo
/// comprobaban que el botón **existía** y nunca que **hiciera** algo.
///
/// Declarando `Future<void> Function()`, `() => _escanear` **deja de compilar**:
/// el error dice que no puede devolver una función donde se espera un `Future`.
/// El fallo no pasa a ser detectable por un test: pasa a ser **imposible de
/// escribir**.
///
/// ## Por qué `Future<void> Function()` y no `void Function()`
/// Porque estas acciones hacen trabajo asíncrono —descifrar, escribir en disco,
/// preguntar al sistema— y `void` mentiría sobre eso igual que mintió antes.
library;

typedef AccionAegis = Future<void> Function();