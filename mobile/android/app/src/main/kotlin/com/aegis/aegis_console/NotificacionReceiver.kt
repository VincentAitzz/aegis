package com.aegis.aegis_console

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.graphics.drawable.Icon
import android.os.Build
import android.os.Bundle
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat

/**
 * Publica el aviso de que Aegis necesita tu OK.
 *
 * ## Por qué un receptor y no `cmd notification post`
 * La primera versión la posteaba el puente con
 * `adb shell cmd notification post`. En el emulador se veía; en el teléfono
 * real, `exit=0`, "aviso enviado", y nada:
 *
 * ```
 * appops: com.aegis.aegis_console -> POST_NOTIFICATION: ignore
 * canal:  shell_cmd (del sistema, del shell, no de Aegis)
 * ```
 *
 * Tres cosas que con ese camino era imposible tener:
 *
 * 1. **El logo.** El aviso lo firma `com.android.shell`, así que el icono es el
 *    del sistema. `-i`/`-I` de `cmd` apuntan a recursos, pero los recursos de
 *    *otra* app no se pueden cargar igual: de ahí que en el emulador se pudiera
 *    y en el Samsung no.
 * 2. **El permiso.** `POST_NOTIFICATIONS` es de la app. `cmd` va con el del
 *    shell, y el `appop` de la app seguía en `ignore` porque nadie se lo pedía.
 * 3. **El toque.** `cmd` puede lanzar una activity, sí, pero a una activity que
 *    la app todavía no tenía.
 *
 * El problema de fondo era uno solo: **una notificación que postea otro no es
 * una notificación tuya.** El puente avisaba "como el shell", el sistema lo
 * guardaba como del shell, y no había manera de que el aviso pareciera de Aegis.
 * Ahora lo publica Aegis, y por eso lleva su icono, su canal, su sonido y su
 * toque.
 *
 * ## Por qué no recibe datos del broadcast
 * El receptor está `exported` porque el puente lo despierta por adb, que es otro
 * proceso. Podría haber leído el id del despliegue del intent, pero entonces
 * cualquier app de tu teléfono podría mandar un broadcast con un id inventado y
 * enseñarte un aviso falso. Aquí no se lee **nada** del intent: se va al bridge
 * a preguntar qué hay pendiente, y lo que se enseña es su respuesta. Que lo
 * disparen sin permiso solo provoca una lectura más, que es idempotente y no
 * concede nada.
 */
class NotificacionReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        // Un receiver tiene ~10 s de vida y `onReceive` corre en el hilo principal:
        // una llamada de red aquí tiraría `NetworkOnMainThreadException` y, peor,
        // mataría el proceso. El trabajo va a un hilo y el receiver devuelve.
        //
        // Del intent solo se lee el **rótulo** del aviso (`hecho` / `fallo`).
        // Lo que decide algo sale de `/deploys`, no del intent: ver la nota sobre
        // `exported` en la cabecera de la clase.
        val tipo = intent.getStringExtra("tipo") ?: PENDIENTE
        val motivo = intent.getStringExtra("motivo").orEmpty()
        val ts = intent.getStringExtra("ts")?.toDoubleOrNull() ?: 0.0
        val petId = intent.getStringExtra("pet_id").orEmpty()
        Thread {
            try {
                avisar(context.applicationContext, tipo, motivo, ts, petId)
            } catch (e: Exception) {
                // ## Por qué esto está y no parece que haga falta
                // Una excepción en este hilo **no se ve**: no hay stacktrace en
                // logcat, no hay aviso, y desde el puente el resultado es el
                // mismo que si el aviso se hubiera publicado y no se viera. La
                // primera versión tenía justo eso —`JSONArray` sobre un
                // objeto— y el diagnóstico fue "avisó y no aparece nada", que
                // es indistinguible de un bug en el puente.
                //
                // Con el `catch` + log, el puente puede leer esto y decir
                // "falló dentro de la app por X" en vez de especular.
                android.util.Log.e(TAG, "no pude publicar el aviso ($tipo)", e)
            }
        }.start()
    }

    /**
     * Pinta el estado que le dice el puente, o se calla si ese estado ya es viejo.
     *
     * ## Por qué hay un solo aviso y no uno por cosa
     * Antes eran dos ids: 4101 para «necesito tu OK» y 4102 para el resultado, a
     * propósito, para que un «ya está» no borrara un «todavía necesito tu OK».
     * Lo que pasó en la práctica es peor que ese riesgo: **4102 no lo cancelaba
     * nadie nunca**, así que un aviso de un test quedó en la bandeja sin forma de
     * quitarlo, y mientras tanto los avisos de resultado nunca se verificaban,
     * porque el puente solo miraba el 4101 en `dumpsys`.
     *
     * Con un id, «no puede haber dos avisos de Aegis» deja de ser una intención y
     * pasa a ser una propiedad. Y el riesgo que se temía —perder a la vista una
     * decisión pendiente— se paga solo: el siguiente aviso de pendientes repinta
     * el aviso de decisión.
     *
     * ## Por qué se guarda el `ts` en disco
     * Los broadcasts van por `adb`, uno a uno, pero **sin orden entre llamadas
     * distintas**: el puente avisa por teléfono y por emulador en procesos
     * separados, y una respuesta lenta puede llegar después de un estado nuevo.
     * Sin este guardia, un «instalado» tardío podía dejar la bandeja pidiendo un
     * OK sobre algo que ya estaba hecho. `ts` es la marca de tiempo que pone el
     * puente y contra la que se compara.
     */
    private fun avisar(
        context: Context,
        tipo: String,
        motivo: String,
        ts: Double,
        petId: String,
    ) {
        val nm = NotificationManagerCompat.from(context)
        if (tipo != CUADRO && ts > 0.0 && ts < UltimoAviso.leer(context)) {
            android.util.Log.i(TAG, "ignoro un aviso viejo: $tipo (ts=$ts)")
            return
        }
        when (tipo) {
            // Todo se va. No se publica nada: un aviso que ya no vale tiene que
            // poder irse **sin** que llegue otro aviso que lo tape.
            LIMPIAR -> {
                nm.cancel(ID)
                UltimoAviso.borrar(context)
            }

            // Aviso de resultado. Se publica aunque `/deploys` no conteste: el
            // resultado de una instalación no está en `/deploys`, así que si el
            // puente se cayó justo al terminar, la noticia sigue siendo real y
            // hay que contarla igual.
            HECHO -> publicarFinal(
                context, nm, "AEGIS · INSTALADO", "Ya está en tu teléfono.", ts
            )
            FALLO -> publicarFinal(
                context, nm, "AEGIS · NO SE PUDO",
                motivo.ifBlank { "Algo impidió que saliera adelante." }, ts
            )

            // En marcha. El único aviso *ongoing*: no se puede quitar con un dedo,
            // porque entre tu «sí» y el resultado hay un trabajo y si el aviso se
            // pudiera deslizar la bandeja volvería a quedarse muda justo en la
            // parte que espera.
            TRABAJANDO -> publicarTrabajando(context, nm, motivo, ts)

            // Enseñar el cuadro, sin abrir la app.
            //
            // ## Por qué hace falta
            // La notificación lleva `setAutoCancel`: al tocarla sin decidir, se va
            // sola. Como la petición sigue pendiente, el puente la vuelve a
            // publicar en el siguiente despliegue, pero hasta entonces no hay
            // forma de volver al cuadro. Quien la abrió sin querer —o la
            // deslizó— se queda sin acceso a la decisión.
            //
            // Se lanza desde aquí y no desde el shell porque `OverlayActivity` es
            // `exported=false` a propósito: si cualquier app del teléfono pudiera
            // abrirla, podría **aprobar una instalación**. Lanzarla desde el
            // proceso de la app es lo que deja esa puerta cerrada.
            CUADRO -> mostrarCuadro(context)

            else -> avisarPendientes(context, nm, ts, petId)
        }
    }

    private fun mostrarCuadro(context: Context) {
        context.startActivity(
            Intent(context, OverlayActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            }
        )
    }

    /** El aviso de «necesito tu OK», y su retirada cuando ya no queda nada. */
    private fun avisarPendientes(
        context: Context,
        nm: NotificationManagerCompat,
        ts: Double,
        petId: String,
    ) {
        // Antes de nada, se dice de dónde se está mirando y si hay con qué. Un
        // `null` sin más información es indistinguible de un puente apagado, de
        // un token caducado y de un host mal compilado — tres fallos con arreglo
        // distinto y el mismo síntoma.
        android.util.Log.i(
            TAG,
            "mirando pendientes: puente=${Puente.hayPuente} host=${Puente.base}",
        )

        val pendientes = Puente.pendientes()

        if (pendientes == null) {
            // No se pudo comprobar. **No se avisa de un problema unknowable**: si el
            // puente está apagado —que es normal, Aegis no es punto único de
            // falla— no hay nada que contar. Un aviso que aparece cada vez que la
            // laptop está cerrada es ruido, y ruido es lo contrario de avisar.
            //
            // Pero sí se deja rastro en el log, porque quien lo lea después
            // necesita distinguir «no había nada» de «no pude mirar».
            android.util.Log.w(TAG, "no pude leer /deploys; no aviso de lo que no sé")
            return
        }

        android.util.Log.i(TAG, "pendientes: ${pendientes.size}")

        if (pendientes.isEmpty()) {
            // Se cobró todo. Se retira el aviso: dejarlo puesto es una mentira
            // esperando a que alguien la lea.
            nm.cancel(ID)
            UltimoAviso.borrar(context)
            return
        }

        publicar(context, nm, pendientes, ts)
    }

    /**
     * Un aviso **final**, y caduca solo.
     *
     * ## Por qué `setTimeoutAfter` y no esperar a otro aviso
     * `setAutoCancel(true)` solo lo quita al tocarlo. Y antes, como estos avisos
     * iban a un id que nadie cancelaba, un «ya está» se quedaba en la bandeja
     * para siempre: pasado un rato es ruido, y ruido es lo contrario de avisar.
     *
     * ## Por qué el toque no lleva a ninguna decisión
     * Un «instalado» no abre el cuadro de decidir. Lleva a la app, que es donde
     * se ve lo que pasó; mandar a un cuadro con la cola vacía sería un callejón.
     */
    private fun publicarFinal(
        context: Context,
        nm: NotificationManagerCompat,
        titulo: String,
        cuerpo: String,
        ts: Double,
    ) {
        crearCanal(context)
        if (!nm.areNotificationsEnabled()) return
        UltimoAviso.guardar(context, ts)
        nm.notify(
            ID,
            NotificationCompat.Builder(context, CANAL)
                .setSmallIcon(R.drawable.aegis_mono)
                .setLargeIcon(Icon.createWithResource(context, R.drawable.ic_launcher_foreground))
                .setContentTitle(titulo)
                .setContentText(cuerpo)
                .setStyle(
                    NotificationCompat.BigTextStyle()
                        .bigText(cuerpo)
                        .setBigContentTitle(titulo)
                )
                .setColor(COLOR_ACENTO)
                .setColorized(true)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .setCategory(NotificationCompat.CATEGORY_STATUS)
                .setAutoCancel(true)
                .setTimeoutAfter(CADUCIDAD_MS)
                .setContentIntent(abrirLaApp(context))
                .build()
        )
    }

    /**
     * «Esto está en marcha», y no se puede quitar.
     *
     * La barra es **indeterminada** a propósito: `adb install` no da porcentaje y
     * uno inventado sería peor que ninguno —un 40 % que no significa nada es una
     * mentira con graphique. Lo que sí sabemos es que hay algo en marcha, y eso
     * es lo que se dice.
     */
    private fun publicarTrabajando(
        context: Context,
        nm: NotificationManagerCompat,
        que: String,
        ts: Double,
    ) {
        crearCanal(context)
        if (!nm.areNotificationsEnabled()) return
        UltimoAviso.guardar(context, ts)
        val cuerpo = que.ifBlank { "Un momento…" }
        nm.notify(
            ID,
            NotificationCompat.Builder(context, CANAL)
                .setSmallIcon(R.drawable.aegis_mono)
                .setLargeIcon(Icon.createWithResource(context, R.drawable.ic_launcher_foreground))
                .setContentTitle("AEGIS · EN MARCHA")
                .setContentText(cuerpo)
                .setStyle(
                    NotificationCompat.BigTextStyle()
                        .bigText(cuerpo)
                        .setBigContentTitle("AEGIS · EN MARCHA")
                )
                .setColor(COLOR_ACENTO)
                .setColorized(true)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .setCategory(NotificationCompat.CATEGORY_PROGRESS)
                .setOngoing(true)
                .setSilent(true)
                .setProgress(0, 0, true)
                .setContentIntent(irAlCuadro(context))
                .build()
        )
    }

    private fun publicar(
        context: Context,
        nm: NotificationManagerCompat,
        pendientes: List<Puente.Pendiente>,
        ts: Double,
    ) {
        crearCanal(context)

        // Un solo aviso, con el número. Uno por decisión inundaría: el caso
        // normal son varias herramientas esperando a la vez, y ver cinco
        // notificaciones idénticas no informa más que ver una que dice cinco.
        val titulo = if (pendientes.size == 1) {
            "AEGIS · NECESITO TU OK"
        } else {
            "AEGIS · ${pendientes.size} DECISIONES PENDIENTES"
        }

        val cuerpo = pendientes.joinToString("\n") { p ->
            val proyecto = p.proyecto.ifBlank { "aegis" }
            if (p.tool.isBlank()) "$proyecto — ${p.motivo}" else "$proyecto — ${p.tool}"
        }

        val aviso = NotificationCompat.Builder(context, CANAL)
            // La **silueta**, no el arte. `ic_launcher_foreground` es la calavera
            // entera de texto, y en la barra de estado sale un rectángulo gris:
            // 77 renglones en 24 dp son una mancha. `aegis_mono` es la misma
            // calavera reducida a bloques, que es lo que se lee a ese tamaño.
            .setSmallIcon(R.drawable.aegis_mono)
            // Y aquí sí el arte, a color y grande, que es donde tiene sitio.
            .setLargeIcon(Icon.createWithResource(context, R.drawable.ic_launcher_foreground))
            .setContentTitle(titulo)
            .setContentText(cuerpo.lineSequence().first())
            .setStyle(
                NotificationCompat.BigTextStyle()
                    .bigText(cuerpo)
                    .setBigContentTitle(titulo)
            )
            .setColor(COLOR_ACENTO)
            .setColorized(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setAutoCancel(true)
            .setSilent(false)
            .setContentIntent(irAlCuadro(context))
            .addAction(
                NotificationCompat.Action.Builder(
                    R.drawable.aegis_mono, "VER", irAlCuadro(context)
                ).build()
            )
            .build()

        // Sin `POST_NOTIFICATIONS`Granted, `notify()` **no lanza y no publica**:
        // se queda en silencio. Es el `appop: ignore` que traía la versión
        // anterior, y por eso aquí se comprueba antes de publicar en vez de
        // confiar en el código de salida.
        //
        // No se pide el permiso desde aquí: un receiver no puede mostrar el
        // diálogo del sistema, y hacerlo a través de la app sería abrirla de
        // golpe para un aviso. El permiso se pide en Dart, con su explicación, y
        // al concederlo `MainActivity` reintenta este mismo aviso por broadcast.
        if (!nm.areNotificationsEnabled()) return
        UltimoAviso.guardar(context, ts)
        nm.notify(ID, aviso)
    }

    /** El toque de un aviso final: la app, donde se ve lo que pasó. */
    private fun abrirLaApp(context: Context): PendingIntent =
        PendingIntent.getActivity(
            context, 1,
            Intent(context, MainActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            },
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

    /** El toque: la ventana translúcida, no la app. */
    private fun irAlCuadro(context: Context): PendingIntent {
        val intent = Intent(context, OverlayActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        }
        return PendingIntent.getActivity(
            context, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
    }

    private fun crearCanal(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val canal = NotificationChannel(
            CANAL, "Decisiones de Aegis", NotificationManager.IMPORTANCE_HIGH
        ).apply {
            description = "Aegis te necesita para instalar o escribir. Nada más."
            enableVibration(true)
            setShowBadge(true)
        }
        context.getSystemService(NotificationManager::class.java)
            ?.createNotificationChannel(canal)
    }

    companion object {
        private const val TAG = "Aegis"

        /** Un solo aviso, un solo id.
         *
         * ## Por qué 4102 desapareció
         * Existía para que el aviso de decisión y el de resultado no se pisaran.
         * El resultado fue peor: 4102 **no lo cancelaba nadie nunca** (solo se
         * cancelaba 4101, y solo cuando otro aviso veía la cola vacía), así que
         * un aviso se quedó en la bandeja sin forma de quitarlo. Y como el puente
         * verifica la entrega mirando `id=4101` en `dumpsys`, todos los avisos de
         * resultado acababan en «AVISO NO VERIFICADO».
         *
         * ## Y 4101 no es un número arbitrario
         * `ID_AVISO = 4101` en `bridge/app/deploy.py` **comprueba** este mismo
         * número en `dumpsys` para decir si el aviso llegó. Si divergen, el
         * broadcast se pierde y no hay error en ninguna parte. Si algún día
         * cambia, cambia en los dos sitios a la vez.
         */
        const val ID = 4101
        const val CANAL = "aegis"

        //: Los estados, con los mismos nombres que `ESTADO_*` en `deploy.py`.
        const val PENDIENTE = "pendiente"
        const val TRABAJANDO = "trabajando"
        const val HECHO = "hecho"
        const val FALLO = "fallo"
        const val LIMPIAR = "limpiar"

        /** Abrir el cuadro sin decidir. Nunca lo manda el puente hoy. */
        const val CUADRO = "cuadro"

        /** Cuánto vive un aviso final antes de irse solo. */
        const val CADUCIDAD_MS = 45_000L

        /**
         * La marca del último aviso pintado, guardada en disco.
         *
         * ## Por qué en `SharedPreferences` y no en memoria
         * El proceso se muere entre un aviso y otro —es un `BroadcastReceiver`, y
         * Android lo mata para cuando quiere—, y un `var` en el companion
         * volvería a cero. Con un aviso que se puede quedar puesto (el que no se
         * podía quitar), perder la marca significa dejar de detectar los avisos
         * viejos justo cuando más falta hace.
         *
         * ## Y por qué guardar el `ts` **del puente**
         * Porque es el puente quien sabe en qué orden envió las cosas. La hora del
         * reloj del teléfono no sirve: el teléfono puede tener la hora cambiada
         * mientras el bridge no.
         */
        object UltimoAviso {
            private const val CLAVE = "aegis.ultimo_aviso"

            fun leer(context: Context): Double =
                context.getSharedPreferences("aegis", Context.MODE_PRIVATE)
                    .getFloat(CLAVE, 0f).toDouble()

            fun guardar(context: Context, ts: Double) {
                if (ts <= 0.0) return
                context.getSharedPreferences("aegis", Context.MODE_PRIVATE)
                    .edit().putFloat(CLAVE, ts.toFloat()).apply()
            }

            fun borrar(context: Context) {
                context.getSharedPreferences("aegis", Context.MODE_PRIVATE)
                    .edit().remove(CLAVE).apply()
            }
        }

        /// El celeste de la identidad (`aegis_palette.dart`).
        ///
        /// ## Por qué una constante y no leer la paleta
        /// Porque Kotlin no lee el Dart. Y **por eso lleva aquí el mismo valor
        /// y no en dos sitios a propósito**: se quedó en ámbar `#FFB020` cuando
        /// la paleta pasó a celeste, y los avisos siguieron saliendo del color
        /// que ya no era el de Aegis. Dos listas de colores en dos lenguajes, y
        /// la segunda se queda. Por eso está en un `companion object` con
        /// nombre, y no suelto por el código.
        const val COLOR_ACENTO = 0xFF4CC9F0.toInt()
    }
}
