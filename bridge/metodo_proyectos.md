# Cómo trabajo en un proyecto

Esto **solo** aplica cuando el encargo tiene un proyecto. En una pregunta,
una nota o mirar algo, esto no va: Aegis es un agente y sirve para el uso
cotidiano, no solo para trabajar en repos.

- Cada escritura pasa por el verificador del proyecto. Si el verificador se
  pone rojo, no sigo hasta que improves o hasta que me digas por qué sigo.


- **Pruebo en el emulador, nunca en el teléfono de entrada.** El emulador replica
  el galaxy a17 (Android 16, 1080x2340, 450 dpi) y no interrumpe a nadie. Todas
  las pruebas de la app van con `target='emulador'`.
- **Tu teléfono solo se toca si tú lo autorizas, una vez por instalación.** Si no
  hay aprobación tuya, no se instala nada y no se abre la app. Instalar y abrir son
  cosas distintas, y por defecto solo se instala. *La única excepción es la
  primera instalación*, porque el botón de aprobar está dentro de la app que aún
  no está: aun así exige la puerta entera y no la abre.
- **Cada destino tiene su APK y su nombre.** El del emulador habla por
  `localhost`, el del tuyo por la tailnet del bridge. No compilo un APK para el
  emulador y lo pruebo en tu teléfono, ni al revés: abriría sin ver nada y no
  habría error.
- **Antes de tocar tu teléfono, la puerta se comprueba sola**: análisis limpio,
  tests verdes y un humo en el emulador que además confirma que la app habla con
  el bridge. No me vale con decir que lo probé.
- Si una prueba falla, la arreglo en el emulador y vuelvo a intentarlo. Solo te
  pido el teléfono cuando ya está verde de verdad.
