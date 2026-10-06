package com.aegis.aegis_console

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {

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
                        pedirPermisoNotificaciones()
                        // Se responde con el estado **de ahora**, que sigue siendo
                        // `false`: el diálogo del sistema es asíncrono y el
                        // resultado llega después, por `onRequestPermissionsResult`.
                        // Prometer `true` aquí sería mentirle a Dart.
                        result.success(concedePermiso())
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
                    "abrirPermiso" -> {
                        Instalador.abrirPermiso(this)
                        result.success(null)
                    }

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
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == CODIGO_PERMISO) {
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
