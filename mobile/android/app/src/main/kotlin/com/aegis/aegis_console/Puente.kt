package com.aegis.aegis_console

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Cliente del bridge para las partes **nativas** de la app.
 *
 * ## Por qué no reusar el repositorio de Dart
 * El receptor de notificaciones y el overlay se lanzan por `am start` / `am
 * broadcast`, es decir, sin que pase por el motor de Flutter ni por ningún
 * `MethodChannel`: tienen que poder hablar con el puente siendo Android puro.
 *
 * Podría haberse esperado a que arranque Flutter y hablar por un canal, pero
 * entonces el overlay dependería de que el motor levante, y el motor no levanta
 * si la app está en background y Android lo ha congelado. La ruta nativa es la
 * única que funciona con la app congelada, que es justo el caso normal.
 *
 * ## Por qué HTTP crudo y no OkHttp
 * El proyecto no depende de OkHttp ni de ningún cliente HTTP más allá de Dart.
 * Meter una dependencia de red para dos peticiones sería más superficie que
 * código. `HttpURLConnection` está en el sistema y hace lo que hace falta.
 */
object Puente {
    /**
     * URL base del bridge, tal como la compuso `build_apk`.
     *
     * Viene del mismo `--dart-define` que usa Dart (§ `app/build.gradle.kts`),
     * así que el overlay y la app no pueden estar apuntando a hosts distintos.
     */
    val base: String get() = conEsquema(BuildConfig.API_HOST)

    /**
     * `API_HOST` es `host` o `host:puerto`, **sin esquema**, y esa es la forma que
     * valida `AppConfig.authority` en Dart. Aquí hay que traducirlo igual, porque
     * el overlay y el receptor hablan con el puente **sin pasar por Dart**.
     *
     * ## Por qué el esquema y el puerto van los dos
     * Los dos se olvidaron por separado, y cada olvido se veía igual —«no me
     * llega el puente»— con la app conectada y el puente escuchando:
     *
     * - **el esquema**: `URL("100.101.102.100:8000/deploys")` lanza
     *   `MalformedURLException`, la petición ni sale y `pedir()` devuelve `null`.
     * - **el puerto**: `URL("http://100.101.102.100/deploys")` es una URL válida que
     *   va al **puerto 80**, que no escucha nada, y falla con un
     *   `ConnectException` igual de opaco.
     *
     * ## Por qué no se delega en otro sitio
     * Porque la regla ya existe y es la de Dart, y reescribirla aquí es como
     * pasó: dos sitios decidiendo qué significa `API_HOST`, y el segundo
     * divergió del primero. Si alguna vez cambia la regla, tiene que cambiar en
     * los dos sitios a la vez; por eso aquí está escrita una sola vez, y todas
     * las peticiones pasan por ella.
     */
    private fun conEsquema(hostCrudo: String): String {
        if (hostCrudo.isBlank()) return hostCrudo
        val host = hostCrudo.removePrefix("http://").removePrefix("https://")
        // Mismo corte que `AppConfig.authority`: el **último** `:` separa el
        // puerto, y si no es un número, no hay puerto.
        val corte = host.lastIndexOf(':')
        if (corte > 0 && corte < host.length - 1) {
            val puerto = host.substring(corte + 1)
            return if (puerto.toIntOrNull() != null) {
                "http://$host"
            } else {
                // Sin puerto explícito: el 8000, como en Dart. Al 80 no escucha
                // nada, y el fallo parece de red.
                "http://$host:8000"
            }
        }
        return "http://$host:8000"
    }

    /** Token de la API. Mismo origen, misma razón. */
    val token: String get() = BuildConfig.TOKEN

    /** Hay con qué hablar. Sin host o sin token, no se intenta. */
    val hayPuente: Boolean get() = base.isNotBlank() && token.isNotBlank()

    /** Qué hay pendiente de tu OK, tal y como lo ve el puente. */
    data class Pendiente(
        val id: String,
        val proyecto: String,
        val motivo: String,
        val tool: String,
    )

    /**
     * `[200]` con la lista de pendientes, `[]` si no hay nada, `null` si no se
     * pudo comprobar.
     *
     * Se distingue `null` de `[]` a propósito: "no hay nada pendiente" y "no sé
     * si hay" llevan a acciones opuestas. El primero deja la notificación en
     * paz; el segundo tiene que callarse también, pero por otra razón.
     *
     * ## Por qué devuelve `null` en vez de propagar el fallo
     * `/deploys` devuelve un **objeto** (`{emulador, telefono, pendientes,
     * tokens_vivos}`), no una lista. Una versión de este código hizo
     * `JSONArray(cuerpo)` sobre ese objeto, y `JSONException` salía dentro de
     * un hilo de receiver, donde **nadie la ve**: no hay stacktrace en logcat, no
     * hay aviso, y el diagnóstico fue "el bridge dice que avisó y no aparece
     * nada". Un fallo silencioso dentro de un hilo es indistinguible de un
     * sistema que no avisó.
     *
     * Por eso todo esto devuelve `null` ante cualquier cosa inesperada, y quien
     * llama lo registra.
     */
    fun pendientes(): List<Pendiente>? = pedir("/deploys")?.let { cuerpo ->
        try {
            // La lista está dentro del objeto, en `pendientes`. Si algún día el
            // puente devuelve la lista pelada, esto no revienta: avisa y se
            // devuelve `null`.
            val arr = JSONObject(cuerpo).optJSONArray("pendientes")
                ?: return@let null
            (0 until arr.length()).mapNotNull { i ->
                val o = arr.optJSONObject(i) ?: return@mapNotNull null
                Pendiente(
                    id = o.optString("id"),
                    proyecto = o.optString("proyecto"),
                    motivo = o.optString("razon"),
                    tool = o.optString("tool"),
                )
            }
        } catch (e: Exception) {
            null
        }
    }

    /**
     * Aprueba o deniega. Devuelve el mensaje del puente, o `null` si falló.
     *
     * El `motivo` solo importa al denegar: el puente lo guarda y lo inyecta en el
     * prompt del siguiente run del agente, para que no vuelva a proponer lo
     * mismo (ver §3 de `AGENTS.md`). Por eso el denegar **no** sale con un
     * motivo vacío.
     */
    fun decidir(id: String, aprobar: Boolean, motivo: String = ""): String? {
        val cuerpo = JSONObject()
            .put("decision", if (aprobar) "aprobar" else "denegar")
            .put("motivo", motivo)
            .toString()
        return pedir("/deploys/$id", cuerpo, "POST")
    }

    /**
     * Pide la instalación en segundo plano de un despliegue ya aprobado.
     *
     * ## Por qué esto existe y no es "el agente lo hace después"
     * Antes, aprobar **devolvía un token** y el agente tenía que volver a llamar
     * a `install_apk` para gastarlo. Eso no es instalar en segundo plano: es que
     * el agente se entere, y si el agente no está, el APK aprobado se queda
     * descargado en el disco para siempre.
     *
     * Ahora el token se lo gasta el propio puente, dentro de este endpoint, y no
     * sale de aquí. El diálogo approve → el puente instala → avisa. Sin que pase
     * nada por el agente ni por su contexto.
     */
    fun instalar(id: String): String? =
        pedir("/deploys/$id/instalar", JSONObject().toString(), "POST")

    /** Una petición al bridge. `null` si no hubo respuesta utilizable. */
    private fun pedir(ruta: String, cuerpo: String? = null, metodo: String = "GET"): String? {
        if (!hayPuente) return null
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL(base + ruta).openConnection() as HttpURLConnection).apply {
                requestMethod = metodo
                connectTimeout = 4000
                readTimeout = 6000
                setRequestProperty("X-Aegis-Token", token)
                setRequestProperty("Accept", "application/json")
                if (cuerpo != null) {
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json; charset=utf-8")
                }
            }
            if (cuerpo != null) {
                conn.outputStream.use { it.write(cuerpo.toByteArray(Charsets.UTF_8)) }
            }
            // Un 4xx también trae un cuerpo con el motivo (por ejemplo
            // `esperando tu OK`), y ese motivo es justo lo que hay que enseñarle
            // a la persona. Por eso se lee el cuerpo siempre y se mira el código
            // aparte, en vez de devolver `null` en cuanto no sea 200.
            val codigo = conn.responseCode
            val texto = (if (codigo in 200..299) conn.inputStream else conn.errorStream)
                ?.bufferedReader()?.use { it.readText() } ?: ""
            if (texto.isBlank()) null else texto
        } catch (e: Exception) {
            // Sin puente (laptop apagada, tailnet caído, app abierta sin red) esto
            // es lo normal y no es un error que merezca un crash: Aegis no es
            // punto único de falla, y su app tampoco.
            //
            // Pero se registra. Un `catch` que devuelve `null` sin más es un
            // agujero: «no pude leer /deploys» y «la petición falló por X» se
            // ven igual desde fuera, y el primero se acababa depurando como si
            // fuera culpa del puente cuando era un `MalformedURLException` aquí
            // dentro.
            android.util.Log.w(
                "Aegis",
                "la petición a $ruta falló (${e.javaClass.simpleName}: ${e.message})",
                e,
            )
            null
        } finally {

            conn?.disconnect()
        }
    }
}
