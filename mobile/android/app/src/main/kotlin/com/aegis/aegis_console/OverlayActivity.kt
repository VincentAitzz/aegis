package com.aegis.aegis_console

import android.app.Activity
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.ColorDrawable
import android.os.Bundle
import android.text.InputType
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

/**
 * El cuadro de decisión, **encima de la app que estés usando**.
 *
 * ## Por qué esto es nativo y no una ruta de Flutter
 * Tres motivos, en orden de peso:
 *
 * 1. **Funciona con la app congelada.** Se abre por `PendingIntent` desde una
 *    notificación, o sea en background y muy probablemente con el proceso
 *    congelado por Android. Una ruta de Flutter necesita el motor levantado, y
 *    levantarlo cuesta cientos de milisegundos en un móvil de gama media. Esto
 *    son milisegundos porque no hay motor.
 * 2. **Aguanta el toque de la app de debajo.** Al ser una ventana propia
 *    translúcida decide ella qué toca el dedo. Un overlay del sistema (ventanas
 *    del sistema) necesita un permiso que aquí no se pide porque no hace falta.
 * 3. **No comparte estado con Flutter.** No le importa si la app está a mitad de
 *    un `setState` o sin bridge. Habla con el puente por su cuenta.
 *
 * ## El aspecto
 *
 * Neobrutalismo a propósito, y no por capricho de estilo: es la misma lengua que
 * la app (bordes gruesos, ámbar, negro, tipografía de palo seco) y su propiedad
 * útil es que **parece un cartel y no un diálogo del sistema**. En este estilo no
 * hay degradados ni sombras difusas: la sombra es otro rectángulo negro
 * desplazado, y el borde es negro y duro. Es lo que hace que un cartel se lea de
 * un vistazo, que es la distancia real a la que se mira un aviso.
 */
class OverlayActivity : Activity() {

    /** Lo que se rellena con las decisiones. La cabecera no se toca al recargar. */
    private lateinit var contenido: LinearLayout

    /** Los dos botones, para deshabilitarlos mientras se decide. */
    private var botonera: View? = null

    /** ¿Hay una decisión en vuelo? Sin esto, dos toques = dos llamadas. */
    private var _decidiendo = false

    /** Si lo que se está decidiendo es aprobar. Lo necesita [terminar]. */
    private var aprobarPendiente = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Fondo transparente: lo que hay detrás es la app que tenías, sin cortar.
        // El oscurecido lo pone `backgroundDimAmount` en el tema.
        window.setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
        // `FLAG_NOT_TOUCH_MODAL` deja que lo que toques **fuera** de la tarjeta
        // vaya a la app de debajo, en vez de quedarse en esta ventana. Con
        // `FLAG_WATCH_OUTSIDE_TOUCH` además nos avisa, para poder cerrar.
        window.setFlags(
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH
        )
        setContentView(construir())
        cargar()
    }

    /**
     * Lee los pendientes y pinta.
     *
     * ## Por qué en un hilo y no aquí
     * `Puente.pendientes()` es una llamada de red **síncrona**, y `onCreate` corre
     * en el hilo principal. Android tira `NetworkOnMainThreadException`, que el
     * `catch` de `pedir()` se come y convierte en `null`… y `null` significa
     * «no pude comprobar». El resultado era un cuadro que **siempre** decía
     * «SIN RESPUESTA», con la app perfectamente conectada.
     *
     * Es la peor forma de fallo posible en este sitio: no es un error, es una
     * respuesta. La UI se ve bien, los textos están, y lo que dice es mentira.
     *
     * ## Por qué no se ve el cuadro mientras carga
     * Se pinta primero el esqueleto —cabecera, separador, «consultando…»— y
     * luego se sustituye. Un cuadro que aparece un segundo después se lee como
     * que funciona; uno que aparece ya vacío, no.
     */
    private fun cargar() {
        contenido.removeAllViews()
        contenido.addView(bloque("CONSULTANDO", "Preguntando al puente qué espera tu OK…"))

        Thread {
            val pendientes = Puente.pendientes()
            runOnUiThread { pintar(pendientes) }
        }.start()
    }

    private fun pintar(pendientes: List<Puente.Pendiente>?) {
        contenido.removeAllViews()
        when {
            // No se pudo comprobar. Se dice tal cual, sin inventar: la diferencia
            // entre "no hay nada" y "no sé si hay" es la diferencia entre apagar
            // el aviso y dejarlo puesto.
            pendientes == null -> contenido.addView(bloque(
                "SIN RESPUESTA",
                "No alcanzo el puente. Puede que la laptop esté apagada — Aegis no " +
                    "es punto único de falla, así que esto es lo normal.\n\n" +
                    "Tu decisión sigue guardada. Cuando vuelvas a conectarte, el aviso reaparece.",
            ))

            pendientes.isEmpty() -> contenido.addView(bloque(
                "NADA PENDIENTE",
                "Ya no hay nada esperando tu OK. Puedes cerrar esto.",
            ))

            // Varias decisiones: una tarjeta cada una. El aviso era uno solo con
            // el número, y esta es la pantalla donde se pagan todas.
            else -> pendientes.forEachIndexed { i, p ->
                if (i > 0) contenido.addView(espacio(20f))
                contenido.addView(tarjetaDe(p))
            }
        }
    }

    /** Toca fuera de la tarjeta: se cierra, sin decidir nada. */
    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (event.action == MotionEvent.ACTION_OUTSIDE) finish()
        return super.onTouchEvent(event)
    }

    @Suppress("DEPRECATION")
    override fun onBackPressed() {
        // Cerrar sin decidir es legítimo: no es una cancelación con motivo. El
        // puente sigue guardando la decisión, y el aviso sigue puesto.
        finish()
    }

    // ---------------------------------------------------------------- construir

    private fun construir(): View {
        contenido = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }

        val tarjeta = panel(BLANCO).apply {
            setPadding(dp(22f), dp(22f), dp(22f), dp(22f))
        }
        tarjeta.addView(cabecera())
        tarjeta.addView(separador())
        tarjeta.addView(contenido)

        val raiz = android.widget.FrameLayout(this).apply {
            // El aire lateral y vertical es lo que separa la tarjeta de los
            // bordes de la pantalla. Sin él, la sombra dura se sale por fuera y
            // la ventana transparente se ve cortada.
            setPadding(dp(20f), dp(44f), dp(20f), dp(44f))
            addView(
                caja(BLANCO, tarjeta),
                android.widget.FrameLayout.LayoutParams(
                    android.widget.FrameLayout.LayoutParams.WRAP_CONTENT,
                    android.widget.FrameLayout.LayoutParams.WRAP_CONTENT,
                    Gravity.CENTER
                )
            )
        }

        // `fillViewport` para que en pantallas cortas la tarjeta pueda desplazarse
        // en vez de salirse por abajo: en un móvil con 3 decisiones el alto crece,
        // y una tarjeta cortada se lee como la app rota.
        return ScrollView(this).apply {
            isFillViewport = true
            addView(raiz)
        }
    }

    private fun cabecera(): View {
        val f = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }

        f.addView(
            TextView(this).apply {
                text = "AEGIS"
                setTextColor(NEGRITO)
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 26f)
                typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
                letterSpacing = 0.12f
            },
            LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        )

        f.addView(TextView(this).apply {
            text = "DECISIÓN"
            setTextColor(NEGRITO)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11f)
            typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
            letterSpacing = 0.18f
            setPadding(dp(10f), dp(5f), dp(10f), dp(5f))
            background = cartulina(AMBAR)
        })

        return f
    }

    private fun separador(): View = View(this).apply {
        setBackgroundColor(NEGRITO)
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, dp(3f)
        ).apply {
            topMargin = dp(14f)
            bottomMargin = dp(16f)
        }
    }

    private fun bloque(titulo: String, texto: String): View = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        addView(TextView(context).apply {
            text = titulo
            setTextColor(AMBAR)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 20f)
            typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
        })
        addView(TextView(context).apply {
            text = texto
            setTextColor(NEGRITO)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            typeface = Typeface.MONOSPACE
            setPadding(0, dp(10f), 0, 0)
        })
    }

    private fun tarjetaDe(p: Puente.Pendiente): View {
        val t = panel(GRIS_CLARO)

        t.addView(TextView(this).apply {
            text = "INSTALAR EN TU TELÉFONO"
            setTextColor(NEGRITO)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 18f)
            typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
        })

        t.addView(rotulo("PROYECTO", p.proyecto.ifBlank { "aegis" }))
        if (p.tool.isNotBlank()) t.addView(rotulo("ACCIÓN", p.tool))
        if (p.motivo.isNotBlank()) t.addView(rotulo("POR QUÉ", p.motivo))

        // El motivo del "no". Sin este campo, denegar es un "no" que el agente no
        // puede aprender de, y el puente lo necesita para inyectárselo al prompt
        // del siguiente run (§2 de `AGENTS.md`).
        val motivo = EditText(this).apply {
            hint = "Si niegas, escribe por qué (obligatorio)"
            setHintTextColor(GRIS)
            setTextColor(NEGRITO)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
            typeface = Typeface.MONOSPACE
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
            maxLines = 3
            setPadding(dp(12f), dp(10f), dp(12f), dp(10f))
            background = cartulina(BLANCO)
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { topMargin = dp(18f) }
        }
        t.addView(motivo)
        t.addView(botones(p.id, motivo))
        return caja(GRIS_CLARO, t)
    }

    private fun rotulo(nombre: String, valor: String): View = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ).apply { topMargin = dp(14f) }

        addView(TextView(context).apply {
            text = nombre
            setTextColor(GRIS)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 10f)
            typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
            letterSpacing = 0.16f
        })
        addView(TextView(context).apply {
            text = valor
            setTextColor(NEGRITO)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            typeface = Typeface.MONOSPACE
        })
    }

    private fun botones(id: String, motivo: EditText): View {
        val f = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { topMargin = dp(20f) }
        }

        f.addView(
            boton("NO", ROJO, BLANCO).apply {
                setOnClickListener {
                    val porQue = motivo.text.toString().trim()
                    if (porQue.isEmpty()) {
                        // Denegar sin motivo no es denegar: es un "no" que el
                        // agente no puede aprender de. Se dice aquí, en vez de
                        // aceptarlo en silencio y perder la lección.
                        motivo.error = "El motivo es obligatorio: es lo que Aegis aprende"
                        return@setOnClickListener
                    }
                    decidir(id, aprobar = false, porQue = porQue)
                }
            },
            LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                .apply { rightMargin = dp(10f) }
        )

        f.addView(
            boton("SÍ", AMBAR, NEGRITO).apply {
                setOnClickListener { decidir(id, aprobar = true, porQue = "") }
            },
            LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        )

        // Se guarda la fila para poder apagarla mientras se decide.
        botonera = f
        return f
    }

    private fun boton(texto: String, fondo: Int, tinta: Int): Button = Button(this).apply {
        this.text = texto
        setTextColor(tinta)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
        typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
        letterSpacing = 0.1f
        isAllCaps = false
        // Sin `stateListAnimator` el botón toma `elevation` al pulsarse y su
        // sombra dura se difumina justo en el gesto, que es donde más se nota.
        stateListAnimator = null
        background = cartulina(fondo)
        setPadding(dp(12f), dp(16f), dp(12f), dp(16f))
    }

    // ------------------------------------------------------------------ decidir

    /**
     * Decide, fuera del hilo principal, y cierra solo si **el puente confirma**.
     *
     * ## Por qué en un hilo
     * Igual que [cargar]: `Puente.decidir` es una llamada de red síncrona, y esto
     * corre en el hilo principal. Android tira `NetworkOnMainThreadException`, el
     * `catch` de `pedir()` la convierte en `null`… y `null` en `decidir` quiere
     * decir «no pude hablar con el puente».
     *
     * Lo que se veía era un Toast de error tras haber pulsado "sí" con la app
     * conectada, y en el puente la petición seguía `pendiente`. Es A-016 otra
     * vez: un gesto que parece hecho y no está guardado en ninguna parte.
     *
     * ## Por qué se bloquean los botones
     * Porque la respuesta tarda. Con los dos activos, quien pulse "sí" sin ver
     * nada puede volver a pulsar, y la segunda llamada llegaría con la primera a
     * medias.
     */
    private fun decidir(id: String, aprobar: Boolean, porQue: String) {
        if (_decidiendo) return
        _decidiendo = true
        aprobarPendiente = aprobar
        botonera?.isEnabled = false
        avisar("Enviando tu decisión…")

        Thread {
            val r = Puente.decidir(id, aprobar, porQue)
            // Aprobar **encadena** la instalación, y esto no era opcional.
            //
            // ## El fallo que esto arregla
            // `POST /deploys/{id}` solo emite el token: el token lo gasta
            // `POST /deploys/{id}/instalar`, dentro del bridge, para que el agente
            // nunca lo vea. Aquí se aprobaba, se pintaba un Toast que decía «se
            // instala en segundo plano» y se cerraba… sin instalar. Dos OK dados
            // y `lastUpdateTime` del teléfono sin cambiar. Aprobado de verdad,
            // nada instalado, y con un Toast que decía lo contrario.
            //
            // ## Por qué el token se queda aquí
            // Por eso existe `Puente.instalar()`: el token **no** sale del
            // bridge. Aquí no hay token, ni lo hay antes ni después: lo que sale
            // de `decidir` es un "sí, guardado", y `instalar` es "hazlo".
            // Encadenar las dos es lo que convierte el gesto en algo.
            val instalado = if (r != null && aprobar) Puente.instalar(id) else null
            runOnUiThread { terminar(r, instalado) }
        }.start()
    }

    /**
     * @param r lo que dijo `/deploys/{id}`: `null` si no hubo respuesta.
     * @param instalado lo que dijo `/deploys/{id}/instalar`: `null` si no se llamó
     *   (denegaste), o si la llamada falló. Los tres casos se distinguen, y no
     *   querer distinguirlos es lo que dejó el Toast mintiendo.
     */
    private fun terminar(r: String?, instalado: String?) {
        when {
            // No hubo respuesta: la decisión no se guardó. Se dice y se reabre el
            // cuadro, que sigue en pie con lo que se había pintado. Cerrar sin más
            // haría creer que sí.
            r == null -> {
                _decidiendo = false
                avisar("No pude hablar con el puente. Tu decisión no se guardó.")
                pintar(Puente.pendientes())
            }

            // Denegado. El motivo queda escrito y Aegis lo lee la próxima vez.
            !aprobarPendiente -> {
                avisar("Denegado. El motivo queda guardado para Aegis.")
                finish()
            }

            // Aprobado y la instalación arrancó.
            instalado != null -> {
                avisar("Aprobado. $instalado")
                finish()
            }

            // Aprobado pero la instalación no arrancó. Se dice con esas palabras,
            // y se reabre: sin esto, un Toast de "aprobado" y nada instalado es
            // justo lo que pasó.
            else -> {
                _decidiendo = false
                avisar("Aprobado, pero no pude arrancar la instalación. Inténtalo otra vez.")
                botonera?.isEnabled = true
                pintar(Puente.pendientes())
            }
        }
    }

    private fun avisar(texto: String) =
        Toast.makeText(this, texto, Toast.LENGTH_LONG).show()

    // ------------------------------------------------------------------ adornos

    private fun dp(v: Float): Int =
        TypedValue.applyDimension(
            TypedValue.COMPLEX_UNIT_DIP, v, resources.displayMetrics
        ).toInt()

    private fun espacio(altoDp: Float): View = View(this).apply {
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, dp(altoDp)
        )
    }

    /**
     * Una caja con **sombra dura**: un rectángulo negro detrás, desplazado.
     *
     * ## Por qué no `View.setShadow` ni `elevation`
     * `setShadow` es API oculta —no está en el SDK público, así que no compila—
     * y además dibuja un difuminado. `elevation` también difumina. En
     * neobrutalismo la sombra no es un degradado: es **otra forma** más grande y
     * desplazada, con borde propio. Por eso se construye a mano con dos vistas.
     */
    private fun caja(fondo: Int, hijo: View): View = SombraDura(dp(8f), hijo)

    /**
     * La tarjeta con su rectángulo negro detrás, desplazado.
     *
     * ## Por qué una clase y no dos vistas con `MATCH_PARENT`
     * La primera versión era un `FrameLayout` con la sombra a `MATCH_PARENT`. En
     * un padre `WRAP_CONTENT` eso mide a 0 —un `View` sin contenido no ocupa
     * nada—, así que la sombra desaparecía y la tarjeta quedaba plana. Peor:
     * parecía funcionar en un caso y no en otro según la altura del contenido.
     *
     * Aquí se coloca a mano: primero la tarjeta, y la sombra toma exactamente sus
     * medidas más el desplazamiento. No depende de cómo mida nadie.
     */
    private inner class SombraDura(private val d: Int, tarjeta: View) :
        android.widget.FrameLayout(this@OverlayActivity) {

        init {
            // La sombra se añade **antes** para que quede detrás.
            addView(hijoSombra())
            addView(tarjeta)
        }

        private fun hijoSombra(): View = View(context).apply {
            setBackgroundColor(NEGRITO)
        }

        override fun onLayout(cambiado: Boolean, l: Int, t: Int, r: Int, b: Int) {
            val tarjeta = getChildAt(1)
            val ancho = tarjeta.measuredWidth
            val alto = tarjeta.measuredHeight
            // La tarjeta en (0,0); la sombra asoma `d` por la derecha y por abajo.
            tarjeta.layout(0, 0, ancho, alto)
            getChildAt(0).layout(d, d, d + ancho, d + alto)
        }

        override fun onMeasure(
            anchoMedida: Int,
            altoMedida: Int,
        ) {
            val tarjeta = getChildAt(1)
            tarjeta.measure(anchoMedida, altoMedida)
            // El ancho disponible menos `d`, para que la sombra que asoma a la
            // derecha no se salga de la pantalla.
            setMeasuredDimension(
                tarjeta.measuredWidth + d,
                tarjeta.measuredHeight + d,
            )
        }
    }

    /** El contenido de una caja: el color y el borde negro. */
    private fun panel(fondo: Int): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(18f), dp(18f), dp(18f), dp(18f))
        background = cartulina(fondo)
    }

    /**
     * Fondo de neobrutalismo: color plano, borde negro duro, sin radio.
     * El radio blando es justo lo que este estilo no usa.
     */
    private fun cartulina(color: Int) =
        android.graphics.drawable.GradientDrawable().apply {
            shape = android.graphics.drawable.GradientDrawable.RECTANGLE
            setColor(color)
            setStroke(dp(4f), NEGRITO)
        }

    private companion object {
        val NEGRITO = Color.parseColor("#0B0B0C")
        val BLANCO = Color.parseColor("#F4F1EA")
        val GRIS_CLARO = Color.parseColor("#E7E3D9")
        val AMBAR = Color.parseColor("#FFB020")
        val ROJO = Color.parseColor("#FF4D3D")
        val GRIS = Color.parseColor("#6B6B6B")
    }
}
