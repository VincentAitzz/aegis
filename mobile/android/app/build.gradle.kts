import java.io.File
import java.util.Base64
import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// ## Dónde vive la clave de firma
//
// Antes esto firmaba con la clave de **debug**, que es la del SDK de Android y
// tiene la contraseña en la documentación de Google. Eso no es una credencial
// débil: es una credencial **pública**. Cualquiera puede generar un APK con
// **la misma firma**, y en Android el almacén de claves está indexado por
// paquete **y** certificado. Mismo paquete y misma firma = misma identidad =
// **acceso al mismo Keystore**. Con `FLAG_SECURE` puesto, esa era justo la vía
// para robarle las semillas TOTP a alguien: hacerte creer que su app nueva era
// la app vieja. Estaba abierta de par en par.
//
// Se lee en este orden, y el primero que exista gana:
//
// 1. `AEGIS_KEY_PROPERTIES` — una ruta explícita.
// 2. `~/.config/aegis/key.properties` — **fuera del repositorio**, que es donde
//    vive de verdad. Fuera del árbol porque la contraseña no es algo que deba
//    depender de que nadie haga `git add .` un día con prisa.
// 3. `android/key.properties` — la convención de Flutter/Gradle, por si alguien
//    trabaja en otra máquina. `android/.gitignore` ya lo excluye.
//
// Si no hay ninguna, la build de release **falla**; está en `buildTypes` abajo.
val ficheroClaves: File? = sequenceOf(
    System.getenv("AEGIS_KEY_PROPERTIES")?.let(::File),
    File(System.getProperty("user.home"), ".config/aegis/key.properties"),
    rootProject.file("key.properties"),
).filterNotNull().firstOrNull { it.isFile }

val claves = Properties().apply {
    ficheroClaves?.inputStream()?.use { load(it) }
}

android {
    namespace = "com.aegis.aegis_console"

    // Va **dentro** de `android` porque `signingConfigs` es del plugin, no del
    // script. Fuera de aquí el build falla al *evaluar*, no al compilar, y el
    // mensaje que sale es sobre el DSL y no sobre la clave que falta.
    signingConfigs {
        if (ficheroClaves != null) {
            create("release") {
                storeFile = file(claves.getProperty("storeFile"))
                storePassword = claves.getProperty("storePassword")
                keyAlias = claves.getProperty("keyAlias")
                keyPassword = claves.getProperty("keyPassword")
            }
        }
    }

    // `buildConfig` va a propósito: el overlay nativo y el receptor de
    // notificaciones necesitan la dirección del bridge y el token **sin pasar por
    // Dart**. Un intent puede arrancar la app con `--es` sin leer nada de Dart, y
    // para eso la URL y la clave tienen que estar en la constante de la app.
    buildFeatures {
        buildConfig = true
    }
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.aegis.aegis_console"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName

        // El puente y el token, leídos de los **mismos** `--dart-define` que
        // Flutter ya pasa a Gradle en `dart-defines` (base64, separados por coma).
        //
        // Por qué no una lista propia de flags: porque entonces habría dos
        // lugares que mantener, y bastaría con compilar con uno y no con el otro
        // para tener una app cuyo overlay habla con un host y cuyo Dart con otro.
        // Leyendo del mismo sitio, es imposible que discrepen.
        val defines: Map<String, String> = (project.findProperty("dart-defines") as String?)
            ?.split(",")
            ?.filter { it.isNotBlank() }
            ?.mapNotNull { par ->
                // Flutter codifica en base64 **el par entero** `CLAVE=valor`, no
                // solo el valor: hay que decodificar y luego partir por el `=`.
                // Al revés se obtiene un valor con `API_HOST=...` pegado delante
                // y el overlay llama a un host que no existe.
                val plano = try {
                    String(Base64.getDecoder().decode(par), Charsets.UTF_8)
                } catch (e: IllegalArgumentException) {
                    null
                }
                plano?.split("=", limit = 2)?.takeIf { it.size == 2 }?.let { it[0] to it[1] }
            }?.toMap() ?: emptyMap()
        val apiHost = defines["API_HOST"] ?: ""
        val token = defines["AEGIS_TOKEN"] ?: ""
        buildConfigField("String", "API_HOST", "\"$apiHost\"")
        buildConfigField("String", "TOKEN", "\"$token\"")
    }

    buildTypes {
        release {
            // ## Por qué esto falla y antes no
            //
            // `signingConfigs.getByName("release")` **no existe** si no hay
            // `key.properties`, y por eso no se puede dejar el
            // `getByName("debug")` de antes como red de seguridad: siempre
            // funcionaba, y por eso el fallo era invisible. Una release firmada
            // con una clave pública circulaba igual que una de verdad, porque
            // **que compile no dice con qué está firmada**.
            //
            // El mensaje dice dónde se busca el fichero, porque el fallo tiene que
            // ser accionable sin leer este comentario.
            signingConfig = signingConfigs.findByName("release") ?: throw GradleException(
                "Falta el fichero de claves de firma. Se busca en " +
                    "\$AEGIS_KEY_PROPERTIES, ~/.config/aegis/key.properties o " +
                    "android/key.properties. Una release NO se firma con la clave " +
                    "de debug: cualquiera podría generar un APK con la misma firma " +
                    "y leer el Keystore de este telefono."
            )
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

dependencies {
    // `NotificationCompat`: el canal, el `PendingIntent` y la comprobación de
    // permiso que usa el receptor. Lo trae Flutter de forma transitiva, pero
    // depender de eso es frágil: si mañana la versión de Flutter no lo arrastra,
    // el fallo aparece en el `assemble` y no se entiende. Declarado, se ve.
    implementation("androidx.core:core-ktx:1.13.1")
}

flutter {
    source = "../.."
}
