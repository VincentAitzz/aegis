import java.util.Base64

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.aegis.aegis_console"

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
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
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
