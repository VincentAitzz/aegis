package com.aegis.aegis_console

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {

    /** A quién responder cuando vuelva el selector de Android. */
    private var pendienteCopia: MethodChannel.Result? = null

    /** El texto que se va a escribir, guardado entre el «exportar» y el vuelta. */
    private var pendingExport: String? = null

    /**
     * Al abrir la app, se reconcilia el aviso con lo que hay de verdad.
     *
     * ## Por qué hace falta y no solo «publicar pendientes»
     * Publicar pendientes ya cubría el caso normal. El que no cubría era el
     * **aviso que ya no vale**: quedó uno de un test en la bandeja sin forma de
     * quitarlo, porque el único sitio que cancelaba era un aviso de pendientes
     * que veía la cola vacía —y si no volvía a haber nada que decidir, ese otro
     * aviso nunca llegaba. Un aviso que se queda para siempre enseñando algo
     * falso es peor que ninguno.
     *
     * Por eso primero se **limpia** y luego se pregunta. Son dos broadcasts y no
     * uno: «limpia» no lee nada y no falla nunca, y «pendientes» sí lee. Si se
     * hicieran a la vez, un fallo de red dejaría la bandeja vacía por un motivo
     * que no es «no hay nada», que es exactamente la mentira que hay que evitar.
     */
    /**
     * Lo que hace con la pantalla antes de que se vea nada.
     *
     * ## Por qué `FLAG_SECURE` y no "es una app de autenticación"
     * Porque aquí vive la semilla TOTP de cuentas reales, y sin esta bandera las
     * tres salidas por las que se escapan son **gratis** y ninguna necesita root:
     *
     * - el **lockscreen** de Android, que hace una captura de la ventana cuando
     *   pulsas recentes o al bloquear;
     * - las **capturas y grabaciones** de pantalla;
     * - el **multitarea**, que guarda un reductor de la ventana en el sistema.
     *
     * La bandera corta las tres de raíz, y no depende de que la app recuerde
     * tapar nada: se aplica al sistema de ventanas, no a nuestra UI.
     *
     *## Por qué va en `onCreate` y no en Flutter
     * `FLAG_SECURE` es una propiedad de la `Window` nativa. Ponerla desde Dart
     * dejaría una ventana de arranque sin ella, que es justo la que se captura al
     * abrir la app.
     */
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.setFlags(
            WindowManager.LayoutParams.FLAG_SECURE,
            WindowManager.LayoutParams.FLAG_SECURE,
        )
    }

    override fun onStart() {
        super.onStart()
        if (!concedePermiso()) return
        android.content.Intent(this, NotificacionReceiver::class.java)
            .setAction(ACCION_AVISAR)
            .putExtra("tipo", NotificacionReceiver.LIMPIAR)
            .let { sendBroadcast(it) }
        android.content.Intent(this, NotificacionReceiver::class.java)
            .setAction(ACCION_AVISAR)
            .putExtra("tipo", NotificacionReceiver.PENDIENTE)
            .let { sendBroadcast(it) }
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        // El permiso de notificaciones se pide **desde Dart**, no en el `onCreate`.
        //
        // ## Por qué no pedirlo solo al arrancar
        // Android 13+ muestra un diálogo del sistema la primera vez. Si salta en
        // el primer frame, lo primero que ve alguien al abrir Aegis es un
        // "¿permitir notificaciones?" sin contexto, y la respuesta razonable es
        // "no". Preguntado en su sitio, con una línea que explica para qué es,
        // se contesta bien.
        //
        // ## Por qué un canal y no pedirlo en cada arranque
        // `requestPermissions` en el `onCreate` dispara el diálogo del sistema en
        // cada arranque en versiones donde el usuario lo denegó dos veces, o en
        // cada arranque si se usa `shouldShowRequestPermissionRationale` mal.
        // Un canal con un método `pedir` explícito deja la decisión en Dart, que
        // es donde está la UI que la explica.
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CANAL)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "estado" -> result.success(concedePermiso())
                    "pedir" -> {
                        // ## Por qué aquí **no** se responde todavía
                        // Porque `requestPermissions` solo **lanza** el diálogo: no
                        // es su respuesta. Antes se hacía
                        // `result.success(concedePermiso())` aquí, y eso devolvía
                        // `false` de inmediato, así que Dart creía que ya tenía la
                        // respuesta y seguía trabajando con ella.
                        //
                        // Se notó en el emulador: Aegis entró al shell con la
                        // franja de «Avisos apagados» puesta, el usuario concedió
                        // después, y la franja siguió ahí **con el permiso ya
                        // dado** — porque nadie volvía a preguntar. El arreglo de
                        // invalidar desde Dart tapaba el síntoma, pero la causa
                        // es que la promesa se resolvía antes de la respuesta.
                        //
                        // Ahora el `Result` queda pendiente y se completa en
                        // `onRequestPermissionsResult`, cuando ya hay veredicto.
                        if (concedePermiso()) {
                            result.success(true)
                        } else if (pendienteNotificacion != null) {
                            // Ya hay un diálogo en pantalla. Android no enseña
                            // dos: esta llamada se resuelve con el estado real
                            // en vez de quedarse colgada para siempre.
                            result.success(concedePermiso())
                        } else {
                            pendienteNotificacion = result
                            pedirPermisoNotificaciones()
                        }
                    }
                    else -> result.notImplemented()
                }
            }

        // El canal de instalar. Va **aparte** del de las notificaciones porque
        // son permisos distintos: uno es «¿me avisas?» y este «¿puedes
        // reemplazar mi binario?». En un solo canal, una app que hablara con las
        // notificaciones podría además instalar, y el motivo de cada permiso
        // dejaría de estar a la vista.
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, Instalador.CANAL)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    // El `versionCode` propio. Dart lo compara con el que anuncia
                    // el bridge para decidir si hay versión nueva, y con eso
                    // evita descargar 50 MB para descubrir que no hacía falta.
                    "versionCode" -> result.success(Instalador.versionCodeDe(this))

                    // Si se tiene el permiso de «instalar apps desconocidas».
                    // Va aparte de `abrirPermiso` porque la app necesita **saber**
                    // para no ofrecer un botón que va a fallar.
                    "puedeInstalar" -> result.success(Instalador.puedeInstalar(this))

                    // Abre Ajustes. El permiso se concede a mano: es un viaje de
                    // la persona al sistema y no hay forma de automatizarlo.
                    //
                    // Devuelve un motivo si no se pudo abrir. Antes devolvía siempre
                    // `null`, o sea «todo bien», y el caso real —un dispositivo sin
                    // pantalla de Ajustes que lo resuelva— era un botón que no
                    // hacía nada y una excepción sin dueño. Decir «no pude» es lo
                    // que permite que Dart lo enseñe.
                    "abrirPermiso" -> result.success(Instalador.abrirPermiso(this))

                    // Pasa el APK al instalador. Devuelve `null` si el intent se
                    // lanzó, y un **motivo** si no. Que se lanzara no quiere decir
                    // que se haya instalado: el desenlace está en un diálogo que
                    // controla el sistema y esta app no puede ver.
                    "instalar" -> {
                        val ruta = call.argument<String>("ruta")
                        if (ruta.isNullOrEmpty()) {
                            result.error("sin_ruta", "no me dijiste qué fichero instalar", null)
                        } else {
                            result.success(Instalador.instalar(this, ruta))
                        }
                    }

                    // Dónde dejar el APK. Lo calcula el nativo para que el
                    // directorio externo y el `FileProvider` no puedan
                    // desincronizarse: si Dart eligiera la ruta, un cambio de
                    // versión del provider dejaría la descarga inencontrable.
                    "destino" -> result.success(Instalador.destino(this).absolutePath)

                    else -> result.notImplemented()
                }
            }

        // El canal de las copias. El tercero, y va aparte por lo mismo que los
        // otros dos: cada canal es **una cosa que la app puede hacer que la
        // anterior no**, y el motivo tiene que poder leerse.
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CopiaNativa.CANAL)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    // Lanza el selector de destino. Responde `null` si el intent
                    // se lanzó, que **no** quiere decir que se haya guardado: el
                    // desenlace llega después, por `onActivityResult`. Prometer
                    // «guardado» aquí sería mentirle a Dart, igual que con el
                    // instalador.
                    "exportar" -> {
                        val texto = call.argument<String>("texto")
                        val nombre = call.argument<String>("nombre")
                        if (texto.isNullOrEmpty() || nombre.isNullOrEmpty()) {
                            result.error("sin_datos", "no me dijiste qué guardar", null)
                        } else {
                            pendienteCopia = result
                            pendingExport = texto
                            result.success(CopiaNativa.exportar(this, texto, nombre))
                        }
                    }

                    // Abre el selector de fichero. El texto llega por
                    // `onActivityResult`, así que aquí solo se responde con que
                    // el selector se lanzó.
                    "importar" -> {
                        pendienteCopia = result
                        result.success(CopiaNativa.pedirFichero(this))
                    }

                    else -> result.notImplemented()
                }
            }
    }

    /**
     * Lo que el selector de Android devolvió.
     *
     * ## Por qué guarda el `result` pendiente
     * Un `MethodChannel` responde **una vez**, y el selector de destino es un
     * diálogo del sistema que vuelve por `onActivityResult`, mucho después de
     * que el canal ya contestara. Sin guardar el `result` entre medias, la
     * escritura del fichero no tendría a quién responder y Dart se quedaría
     * esperando para siempre —que es el mismo «preguntando para siempre» de
     * A-105, por otro camino—.
     *
     * ## Por qué cancelado y fallado son respuestas distintas
     * Cancelar es una decisión y se dice. Fallar al escribir es un problema del
     * destino y se dice el motivo. Devolver «no se pudo guardar» para los dos
     * hace que alguien que cambió de opinión piense que ha perdido algo.
     */
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        val pendiente = pendienteCopia ?: return
        if (requestCode != CopiaNativa.PEDIR_DESTINO && requestCode != CopiaNativa.PEDIR_FICHERO) {
            return
        }
        pendienteCopia = null

        val uri = data?.data
        if (resultCode != Activity.RESULT_OK || uri == null) {
            // Cancelado. No es un fallo y no se dice que falló.
            pendingExport = null
            pendiente.success(null)
            return
        }

        if (requestCode == CopiaNativa.PEDIR_FICHERO) {
            pendingExport = null
            pendiente.success(CopiaNativa.leer(this, uri))
            return
        }

        // Exportar: el texto se guardó al lanzar el selector, y ahora se
        // escribe donde la persona eligió.
        val texto = pendingExport
        pendingExport = null
        if (texto == null) {
            pendiente.success("no había nada que escribir")
            return
        }
        pendiente.success(CopiaNativa.escribir(this, uri, texto))
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == CODIGO_PERMISO) {
            // La llamada de `pedir` se resuelve **aquí**, que es donde está la
            // respuesta. Antes se respondía al lanzar el diálogo, y Dart
            // seguía con un `false` viejo.
            pendienteNotificacion?.success(concedePermiso())
            pendienteNotificacion = null

            // Ha vuelto el permiso: se publica el aviso que quedó pendiente, si
            // había alguno. Sin esto habría que esperar al próximo despliegue para
            // enterarse de lo que ya pasó.
            if (concedePermiso()) {
                android.content.Intent(this, NotificacionReceiver::class.java)
                    .setAction(ACCION_AVISAR)
                    .putExtra("tipo", NotificacionReceiver.PENDIENTE)
                    .let { sendBroadcast(it) }
            }
        }
    }

    /**
     * La llamada de `pedir` a la espera de que el usuario conteste.
     *
     * Vive aquí, y no como argumento, porque la respuesta llega en un callback
     * del ciclo de vida que no sabe nada de la llamada que la pidió.
     */
    private var pendienteNotificacion: MethodChannel.Result? = null

    private fun concedePermiso(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return true
        return ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED
    }

    private fun pedirPermisoNotificaciones() {
        if (concedePermiso()) return
        ActivityCompat.requestPermissions(
            this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), CODIGO_PERMISO
        )
    }

    companion object {
        const val CANAL = "aegis/notificaciones"
        const val ACCION_AVISAR = "com.aegis.aegis_console.AVISAR"
        private const val CODIGO_PERMISO = 4701
    }
}
