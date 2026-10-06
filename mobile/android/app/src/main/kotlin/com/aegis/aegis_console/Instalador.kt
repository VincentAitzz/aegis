package com.aegis.aegis_console

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import java.io.File

/**
 * Instalar una actualización sin `adb`.
 *
 * ## Lo que esto **no** puede hacer
 * Instalar en silencio. Android no lo permite en ningún modo: ni como app
 * normal, ni siendo device owner sin provisionar por `adb`. Siempre hay un
 * diálogo del sistema y siempre hay un toque humano. La app lo dice en la
 * pantalla; aquí no hay ningún atajo, y no porque no se pueda añadir sino
 * porque no existe.
 *
 * ## El permiso se concede a mano, una vez
 * `REQUEST_INSTALL_PACKAGES` abre Ajustes → Apps → Acceso especial → «Instalar
 * apps desconocidas». Es un viaje de la persona al sistema, y no se puede
 * automate. Por eso `puedeInstalar` y `abrirPermiso` están separados: la app
 * necesita **saber** si lo tiene para no ofrecer un botón que va a fallar, y
 * necesita **llevar allí** a quien no lo tiene.
 *
 * ## Por qué un canal propio y no el de las notificaciones
 * Porque son cosas distintas: uno es «¿me das permiso para hablarte?» y este es
 * «¿me das permiso para reemplazar mi propio binario?». Mezclarlos en un solo
 * `MethodChannel` haría que una app que habla con las notificaciones pudiera
 * además instalar cosas, y el motivo de cada permiso dejaría de estar a la vista
 * en el código.
 */
object Instalador {

    /** Canal del `MethodChannel`. Distinto del de las notificaciones, a propósito. */
    const val CANAL = "aegis/instalar"

    /** Error que Dart tiene que distinguir: «no hay instalador», no «falló». */
    private const val SIN_INSTALADOR = "sin_instalador"

    /** MIME del paquete. Es el que el instalador del sistema entiende. */
    private const val MIME_APK = "application/vnd.android.package-archive"

    /**
     * El `versionCode` de la app instalada.
     *
     * ## Por qué esto y no el `versionName`
     * Android **rechaza** una actualización cuyo `versionCode` sea menor, y no lo
     * explica de forma utilizable. Es el único número que decide si una
     * actualización se puede siquiera ofrecer, y por eso se lee del paquete
     * instalado y no de `pubspec.yaml`: para que no pueda discrepar de lo que el
     * bridge tiene en su APK.
     */
    fun versionCodeDe(context: Context): Long {
        val info = context.packageManager.getPackageInfo(context.packageName, 0)
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            info.longVersionCode
        } else {
            @Suppress("DEPRECATION") info.versionCode.toLong()
        }
    }

    /** ¿Ha concedido la persona el permiso de instalar apps desconocidas? */
    fun puedeInstalar(context: Context): Boolean =
        context.packageManager.canRequestPackageInstalls()

    /**
     * Lleva a Ajustes, al apartado de este permiso.
     *
     * No se puede conceder desde la app: es un viaje de la persona. Por eso esto
     * solo abre la pantalla; el resultado se consulta después con
     * [puedeInstalar].
     */
    fun abrirPermiso(context: Context) {
        val intent = Intent(
            Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
            Uri.parse("package:${context.packageName}")
        )
        // Un móvil viejo, o un fabricante que mueve la pantalla, puede no tener
        // esa activity. Se cae al ajustes de la app, que siempre existe, en vez
        // de reventar con `ActivityNotFoundException`: el usuario ve algo y
        // busca, que es mejor que un crash.
        val nekst = intent.resolveActivity(context.packageManager) == null
        context.startActivity(
            if (nekst) Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                .setData(Uri.parse("package:${context.packageName}"))
            else intent
        )
    }

    /**
     * Pasa el APK de [ruta] al instalador del sistema.
     *
     * Devuelve si el intent **pudió lanzarse**, no si la instalación se completó:
     * el desenlace llega después en un diálogo que el sistema controla y esta app
     * no puede observar. Por eso el que llama tiene que decir «te toca confirmar»
     * y no «instalado».
     *
     * @param ruta ruta **absoluta** de un fichero dentro de `external-files/apk`.
     */
    fun instalar(context: Context, ruta: String): String? {
        val fichero = File(ruta)
        if (!fichero.isFile) {
            return "no encuentro el APK descargado en $ruta. Vuelve a descargarlo."
        }
        val uri = FileProvider.getUriForFile(
            context, "${context.packageName}.ficheros", fichero
        )
        val intent = Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, MIME_APK)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        // Desde Android 11 las apps no ven las de otras. El `<queries>` del
        // manifest declara esto; si algún día falta, `resolveActivity` da `null`
        // y sin esta comprobación el arranque del intent falla con una excepción
        // que no dice que el problema es el manifest.
        if (intent.resolveActivity(context.packageManager) == null) {
            return SIN_INSTALADOR
        }
        return try {
            context.startActivity(intent)
            null
        } catch (e: Exception) {
            "el sistema no aceptó abrir el instalador: ${e.message ?: e::class.java.simpleName}"
        }
    }

    /** Dónde va el APK descargado, y por qué ahí. */
    fun destino(context: Context): File {
        // `external-files/apk`: es de la app, no hace falta permiso de
        // almacenamiento, y `FileProvider` lo expone sin tocar nada del usuario.
        // El nombre lleva el `versionCode`, para que una descarga interrumpida
        // no se confunda con la nueva.
        val dir = File(context.getExternalFilesDir(null), "apk")
        if (!dir.isDirectory) dir.mkdirs()
        return File(dir, "aegis-${versionCodeDe(context)}.apk")
    }
}