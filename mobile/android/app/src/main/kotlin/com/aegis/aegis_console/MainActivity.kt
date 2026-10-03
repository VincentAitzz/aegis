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
