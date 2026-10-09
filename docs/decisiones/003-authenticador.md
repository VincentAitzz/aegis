# 003 — El autenticador: en el móvil, y sin tocar el bridge

> 2026-10-07. Añade TOTP a la app y **cero** cosas al bridge.

## El problema

Aegis necesita poder autenticarte en servicios con doble factor. Y hay un
detalle que solo aparece cuando se piensa en el fallo y no en la función: la
app es **el único sitio donde puedes perder algo que no se puede recuperar**.

El bridge guarda notas, tareas y trazas. Si se pierden, se pierden. Una semilla
de TOTP es distinta: quien la tiene entra en tu correo, en tu banco, en tu
GitHub. No hay «soporte» ni «restaurar desde copia de seguridad» del servidor,
porque el servidor no tiene tu semilla: la tiene Aegis.

Eso convierte la decisión de **dónde vive** en la decisión del trabajo.

## Opciones

**A. En el bridge, como tool del agente.**
Coste: lo mínimo en código — una tool más en `mcp_ops`, y la pantalla la
consulta. Y es exactamente la opción que `002` ya rechazó por otra razón: el
schema son 19.083 chars que se pagan en cada paso de cada run, para acelerar un
subconjunto que no lo necesita.

Pero el problema de verdad es otro, y no es de coste: **la semilla passaría por
la traza del autopilot**, el log de telemetría y la memoria de Chroma. Las tres
son cosas que se pueden leer, y A-016 ya apkareció en este repo por cómo se
contamina la memoria con episodios que no lo eran. Una semilla en la traza es un
problema del mismo tipo y del mismo tamaño.

**B. En el móvil, sin red. Lo que se ha construido.**

**C. Híbrido: el móvil calcula y el bridge guarda la copia.**
Coste: un sobre cifrado en el bridge. Y el bridge guarda **todo lo demás en
claro** — notas, tareas, aprobancias, trazas—, así que un sobre cifrado sería
lo único cifrado que hay en él. Eso crea la sensación de que el bridge trata
tus claves de forma especial cuando en realidad depende de un fichero en el
mismo disco. Peor que no tenerlo.

## Recomendación

**B**, y no es una preferencia de arquitectura: es lo que piden las tres cosas
que este repo considera inviolables.

| Invariante | Por qué empuja aquí |
|---|---|
| **El prompt es la variable** (`vision.md` §2) | TOTP es determinista. Cero modelo, ~0,03 ms, como `intents.py`. Meterlo en el schema haría más lento el motor para nada |
| **Lo íntimo no sale** | La semilla no sale del proceso. Ni al bridge, ni a Chroma, ni al log |
| **Se puede auditar** | La traza del agente no tiene nada que auditar, porque no participa |

**Consecuencia medible: cero cambios en `bridge/`.** Salvo la lección, que es
obligatoria. Es la primera capacidad del repo que es *de la app* y no *del
agente*.

## Lo que salió de la decisión

| Pieza | Dónde | Por qué |
|---|---|---|
| El cálculo | `mobile/lib/core/auth/totp.dart` | Escrito a mano, no un paquete |
| Los vectores | `test/totp_test.dart` | Los de RFC 4226 y 6238, comprobados |
| El parser | `mobile/lib/core/auth/otpauth.dart` | El emisor duplicado rompe los parsers simples |
| La bóveda | `mobile/lib/core/auth/boveda.dart` | Keystore, y un sobre entero |
| La copia | `mobile/lib/core/auth/copia.dart` | Argon2id + AES-256-GCM, fichero manual |

### Por qué el cálculo está escrito a mano

`otp` de pub.dev lo hace en menos código. Se ha escrito por una razón concreta:
**los vectores de la RFC viven en este repo**. Un autenticador cuyo correctness
se delega en una caja negra de la que nadie ha leído el truncamiento dinámico no
es un autenticador.

Los 18 vectores se comprobaron además contra una implementación independiente
en Python antes de fijarlos. Salió que la RFC usa **semillas distintas para
SHA-1 y para SHA-256/512** (20, 32 y 64 bytes), cosa que no es evidente y que
hizo fallar los doce primeros.

### Por qué los códigos de recuperación van hasheados

Recuperar un código **sin el móvil** tiene que significar «lo tengo escrito en un
papel». Si estuviera en claro en la bóveda, recuperarlo significaría volver a
abrir la bóveda —y si has perdido el móvil, no puedes.

El canje funciona porque el hash basta para comprobarlo: tecleas el que tienes
escrito y se gasta uno. Y hay un test que falla si alguno de los diez códigos
aparece en claro en lo guardado.

### Por qué la corrupción es un valor y no una excepción

Esto salió de un fallo medido, no de una preferencia. La primera versión lanzaba
`BovedaCorrupta`, el provider la traducía a `AsyncError`, y **con Riverpod 3 la
pantalla se quedaba con el spinner de carga indefinidamente**: ni error ni
fallo, solo «cargando» sobre una bóveda ilegible.

Un spinner eterno es el peor resultado posible, porque parece que está haciendo
algo. Y peor: si en algún momento se hubiera pintado como lista vacía, un
«añadir cuenta» habría destruido lo que quedaba.

Ahora `Boveda.corrupta` es un **valor**, y por eso:

- La pantalla no puede confundir «no tienes cuentas» con «no se pueden leer».
- `Boveda.escribirEn` se niega a escribir encima, **en el valor y no en cada
  llamador**: un olvido en uno de ellos sería exactamente la pérdida.

### Por qué la barra no creció

`test/sections_test.dart:54` falla a propósito por la séptima sección. Con seis
pestañas a 180 px cada una las etiquetas se leen; con siete hay que encogerlas,
y el propio test avisa de que la solución no es el texto. Por eso el
autenticador se abre desde un botón en **Ahora**, no como pestaña.

## Qué lo falsaría

1. **Que el servicio acepte un código calculado con los parámetros por defecto.**
   Es el falsador fuerte: significaría que `digits`/`period`/`algorithm` de la
   query no se leen bien, y no se vería hasta un login fallido en casa. Se
   comprueba con una cuenta real de un servicio real — **pendiente, y es la
   prueba que falta**.
2. Que dos escrituras seguidas notificationen a Riverpod. Hoy funciona porque
   [Boveda.copia] devuelve siempre un objeto nuevo; si alguien quita el
   `.copia()`, el alta y el borrado dejan de repintarse **solo** con almacenes que
   devuelven la misma instancia. El fallo es silencioso y por eso hay test.

## Qué invariante toca

Ninguna la relaja; dos la estrechan:

- **Lo íntimo no sale** — se cumple por construcción: el bridge no participa.
- **La memoria es tuya** — se cumple: hay que poder **borrar** la bóveda, y eso
  borra de verdad, con sus códigos.

Y una nueva que este trabajo pone sobre la mesa:

- **Nada irreversible sin OK.** Añadir una cuenta no lo es. **Borrarla sí**: es
  la acción que puede dejarte fuera. Por eso el diálogo de borrado dice qué se
  pierde, y por eso existe la copia cifrada antes de poder borrar nada.

## Lo que cambió de opinión: la copia de seguridad

La primera versión escribía la copia con `getApplicationDocumentsDirectory()`, y
el fichero quedaba **en almacenamiento interno**: `/data/user/0/<paquete>/app_flutter/`.
El explorador de archivos de Android no ve ahí. La función «exportar copia»
producía algo que **el usuario no podía recuperar sin `adb`**, que es justo lo
contrario de una copia de seguridad.

La razón por la que se escribió así estaba en el propio código: SAF
(`ACTION_CREATE_DOCUMENT`) deja elegir destino, y entre destinos están Drive y
el correo, y eso «es enviar la bóveda a un tercero».

**El razonamiento estaba mal en un punto**, y es el que importa: la invariante de
«lo íntimo no sale» protege contra **salidas que no eliges**, no contra que la
persona elija. Y la opción de no hacer nada —un fichero inalcanzable— no era
neutral: era la peor, porque hacía creer que había copia.

Como se pidió **full local y privado**, la decisión es:

- El fichero va a `Android/data/<paquete>/files/copias/` — almacenamiento
  externo de la app, sin ningún permiso de almacenamiento.
- Se expone con el `FileProvider` que ya declaraba el manifest
  (`<external-files-path name="copias" path="copias/" />`).
- **Importar solo lee de ahí.** No hay selector de destino: la app no ofrece
  ninguna puerta a una nube.

**Y el aviso que va con la exportación**: `Android/data/` se borra al desinstalar
la app, y desinstalar es lo que hace la gente cuando recupera un móvil. Sin
decirlo, el usuario cree que tiene una copia y la tiene hasta el día que la
necesita. Por eso sigue existiendo el formato en papel/QR, que no se pierde al
desinstalar y que es la misma filosofía que los códigos de recuperación.

## Lo que resulta de no depender de terceros

La dependencia de Google que introduce el escáner se **auditó**, no se dio por supuesta:

| | |
|---|---|
| Permisos en el manifest de ML Kit | ninguno |
| Clases de telemetría / analytics / firebase | 0 de 362 |
| URLs http(s) en las clases Java | 0 |
| Clases con cliente HTTP | 0 |
| Símbolos de red en el `.so` | 3, y son `OPENSSL_memory_alloc/free/get_size` |

Se usa la variante **empaquetada** (`com.google.mlkit:barcode-scanning`), no la
de Play Services: la segunda descarga el modelo al primer uso, y un autenticador
que necesita red para leer un QR no funciona sin cobertura.

El matiz honesto: eso es evidencia sobre `barcode-scanning-17.3.0`, no una
garantía de familia. Si se actualiza, hay que repetirlo. Está en la Fase 4 como
comprobación repetible y no como nota al pie.

## Lo que queda abierto

- **`AEGIS_API_KEY` sigue compilado en el APK.** Esto no lo arregla, pero lo
  deja a un paso: la bóveda ya existe, y proteger el bridge con TOTP es cambiar
  `exigir_token()` por una puerta de dos factores. Siguiente paso natural.
- **No hay sincronización entre dispositivos.** A propósito: sincronizar
  significa mandar las semillas a algún sitio, y el único sitio al que se puede
  mandar es el bridge.
- **La puerta completa no incluye el login contra un servicio real.** La
  instalación de dos builds del `AGENTS.md` §4.1.2 sigue pendiente para esto, y
  es lo que falta para cerrar el falsador fuerte de §Qué lo falsaría.
- **`versionCode 17`, sin instalar nada todavía.** Android no acepta una
  actualización con el mismo código, así que la siguiente build con cambios
  reales tiene que subir a **18**.