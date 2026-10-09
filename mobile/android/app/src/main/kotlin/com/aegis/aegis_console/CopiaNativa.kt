package com.aegis.aegis_console

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns

/**
 * Guardar y recuperar la copia de las claves, con el selector de Android.
 *
 * ## Por qué SAF y no el directorio de la app
 * La versión anterior escribía la copia en `Android/data/<paquete>/files/` y
 * la leía de ahí. Eso **no es una copia de seguridad**: desde Android 11 el
 * explorador de archivos no puede entrar en `Android/data`, y además ese
 * directorio se borra al desinstalar. El fichero se escribía donde nadie
 * llegaba, y la función «exportar copia» parecía funcionar sin que nadie
 * pudiera comprobarlo.
 *
 * Con SAF quien guarda elige la carpeta, así que el fichero acaba donde la
 * persona puede encontrarlo y sacarlo del móvil. Y el selector de Android
 * incluye destinos en la nube: **la app no sube nada por su cuenta** —escribe
 * donde se le dice—, pero el destino es elección suya y Aegis lo dice.
 *
 * ## Por qué el canal va aparte
 * Los otros dos son «¿me avisas?» y «¿puedes reemplazar mi binario?». Este es
 * «¿puedes escribir fuera de tu carpeta?». En un solo canal, una app que hablara
 * con las notificaciones podría además sacar las claves del dispositivo, y el
 * motivo de cada permiso dejaría de estar a la vista.
 *
 * ## Por qué devuelve `String?` y no `Boolean`
 * Igual que el instalador: que el intent **se lanzara** no quiere decir que se
 * haya exportado. El desenlace —cancelar el selector, elegir una carpeta sin
 * permiso, no poder escribir— está en un diálogo que controla el sistema y esta
 * app no puede observar. Un `true` sería una mentira; un motivo es verdad, y es
 * lo que permite decir «no elegiste dónde guardarlo» en vez de «no se pudo
 * guardar», que son dos problemas distintos.
 */
object CopiaNativa {

    /** Canal del `MethodChannel`. Distinto de los otros dos, a propósito. */
    const val CANAL = "aegis/copia"

    /**
     * Códigos de petición, para no colarse en el de otro intent.
     *
     * Públicos porque los necesita `MainActivity.onActivityResult`, que es quien
     * los compara: si fueran privados, tendría que repetir los números aquí y
     * un cambio en uno no cambiaría el otro.
     */
    const val PEDIR_DESTINO = 4711
    const val PEDIR_FICHERO = 4712

    /** MIME de la copia: JSON, que es lo que Aegis escribe. */
    private const val TIPO = "application/json"

    /**
     * Guarda [texto] y devuelve `null` si se eligió destino y se escribió, o un
     * motivo si no.
     *
     * El nombre propuesto lleva fecha y hora, y por qué: exportar dos veces sin
     * querer **pisa** la copia anterior, y una copia que se sobrescribe sin
     * preguntar no era una copia.
     */
    fun exportar(activity: Activity, texto: String, nombre: String): String? {
        if (texto.isEmpty()) return "no hay nada que guardar"
        val intent = Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = TIPO
            putExtra(Intent.EXTRA_TITLE, nombre)
        }
        return lanzar(activity, intent, PEDIR_DESTINO)
    }

    /** Abre el selector para elegir una copia. Devuelve `null` si se canceló. */
    fun pedirFichero(activity: Activity): Intent =
        Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = TIPO
        }

    /**
     * Lee el contenido de lo que eligió la persona.
     *
     * El tipo es `String?` explícito y no el del `use`, porque `use` devuelve
     * lo que devuelve el bloque y el tipo se infiere como `Any` si no se
     * anota —y `Any` no se puede asignar a un `String?`.
     */
    fun leer(activity: Activity, uri: Uri): String? = try {
        activity.contentResolver.openInputStream(uri)?.use { flujo ->
            flujo.readBytes().toString(Charsets.UTF_8)
        }
    } catch (e: Exception) {
        null
    }

    /** Escribe [texto] en [uri], que es lo que eligió como destino. */
    fun escribir(activity: Activity, uri: Uri, texto: String): String? = try {
        // `openOutputStream` recorta por defecto: si el destino es más pequeño
        // que el contenido, **dejaría el fichero a medias** y la copia sería
        // un JSON truncado que parece bueno. Por eso el "wt".
        //
        // El bloque del `use` no devuelve nada, y Kotlin lo infiere como `Any`
        // si no se le dice que es `Unit`; sin eso, la función devuelve `Any`
        // y no encaja en `String?`.
        activity.contentResolver.openOutputStream(uri, "wt")?.use { salida ->
            salida.write(texto.toByteArray(Charsets.UTF_8))
            salida.flush()
            Unit
        }
        null
    } catch (e: Exception) {
        "no se pudo escribir: ${e.javaClass.simpleName}"
    }

    private fun lanzar(activity: Activity, intent: Intent, codigo: Int): String? {
        return try {
            activity.startActivityForResult(intent, codigo)
            null
        } catch (e: Exception) {
            "no hay ninguna app que pueda guardar un fichero"
        }
    }

    /** Si el selector devolvió algo, [accion] con la URI; si no, `null`. */
    fun <T> resultado(requestCode: Int, esperado: Int, uri: Uri?, accion: (Uri) -> T): T? {
        if (requestCode != esperado) return null
        if (uri == null) return null
        return accion(uri)
    }
}