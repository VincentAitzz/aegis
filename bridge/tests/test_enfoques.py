"""Los enfoques: solo se pagan los runs que los llevan, y cierran puertas.

Cuatro cosas se comprueban aquí, y las cuatro importan:

- un enfoque válido **aparece** en el prompt, y uno inventado o con traversal
  **no rompe el run** ni lee nada;
- sin enfoque, el prompt **no crece**: es el presupuesto del 7B (A-016), y un
  enfoque que se colara en todos los runs se pagaría en los de operación;
- el **tope** se comprueba en cada petición, no solo al cargar el índice;
- un enfoque **cierra tools**, y el cierre lo cumple la autonomía, no el prompt.

## Lo que este fichero no puede comprobar

Que Aegis **pida** el suyo con `usar_enfoque`. Eso depende del 7B emitiendo la
llamada, y es lo que mide `bin/probe-toolcall.sh`. Un test unitario que lo
simule daría verde sin decir nada del riesgo real (A-016).
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import enfoques  # noqa: E402
from app import autopilot  # noqa: E402


def _indice(tmp: Path, enfoques_: list[dict]) -> None:
    """Escribe un índice y sus bloques en `tmp`."""
    (tmp / "_indice.json").write_text(
        json.dumps({"enfoques": enfoques_}), encoding="utf-8")
    for f in enfoques_:
        if f.get("sin_bloque"):
            continue
        bloque = f.get("bloque") or f"{f['nombre']}.md"
        (tmp / bloque).write_text(
            f.get("texto") or f"Cuerpo de {f['nombre']}.", encoding="utf-8")


class _PisoEnfoques(unittest.TestCase):
    """Un directorio de enfoques de mentira, para poder romper las cosas."""

    def setUp(self) -> None:
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(enfoques, "ENFOQUES_DIR", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        indice = mock.patch.object(enfoques, "INDICE", self.tmp / "_indice.json")
        indice.start()
        self.addCleanup(indice.stop)
        # El registro es cacheado con `lru_cache`: sin limpiarlo, un índice de
        # este test se leería desde el de otro. Es el mismo motivo por el que el
        # piso de `deploy` limpia su estado.
        enfoques._registro.cache_clear()
        self.addCleanup(enfoques._registro.cache_clear)
        enfoques._CACHE.clear()
        self.addCleanup(enfoques._CACHE.clear)

    def uno(self, **extra) -> dict:
        base = {"nombre": "arquitectura", "titulo": "Cómo se construye",
                "resumen": "para decidir cómo", "bloque": "arquitectura.md"}
        base.update(extra)
        return base


class TestCargaDelIndice(_PisoEnfoques):
    def test_un_enfoque_se_lee(self) -> None:
        _indice(self.tmp, [self.uno()])
        self.assertEqual(enfoques.nombres(), ["arquitectura"])
        # El bloque es el texto del `.md`; el título vive en el índice, y son dos
        # cosas distintas: el título es lo que ve la persona, el texto lo lee Aegis.
        self.assertEqual(enfoques.bloque("arquitectura"), "Cuerpo de arquitectura.")
        self.assertEqual(enfoques.ficha("arquitectura")["titulo"],
                         "Cómo se construye")

    def test_un_nombre_con_traversal_no_lee_fuera(self) -> None:
        """`nombre` lo escribe un 7B. Un `../` no es una hipótesis."""
        fuera = self.tmp.parent / "secreto.md"
        fuera.write_text("no deberías leerme\n", encoding="utf-8")
        _indice(self.tmp, [self.uno()])
        self.assertEqual(enfoques.bloque("../secreto"), "")
        self.assertEqual(enfoques.bloque(".."), "")

    def test_un_indice_roto_se_ve(self) -> None:
        """Un índice mal formado es **nuestro** fallo y tiene que verse.

        El código viejo devolvía cadena vacía en cualquier fallo, y eso degraded el
        prompt sin que nadie supiera que Aegis había dejado de tener enfoques.
        """
        (self.tmp / "_indice.json").write_text("{no es json", encoding="utf-8")
        with self.assertRaises(enfoques.EnfoqueNoExiste) as cm:
            enfoques.ficha("arquitectura")
        self.assertIn("no es JSON legible", str(cm.exception))
        # Y `nombres()` **no** revienta: lo llama la UI, y una pantalla en blanco
        # por un índice roto sería un segundo fallo tapando el primero.
        self.assertEqual(enfoques.nombres(), [])

    def test_un_bloque_que_falta_se_ve(self) -> None:
        _indice(self.tmp, [self.uno(bloque="no-existe.md", sin_bloque=True)])
        with self.assertRaises(enfoques.EnfoqueNoExiste) as cm:
            enfoques.ficha("arquitectura")
        self.assertIn("no existe", str(cm.exception))

    def test_un_nombre_invalido_se_ve(self) -> None:
        _indice(self.tmp, [self.uno(nombre="Arquitectura")])
        with self.assertRaises(enfoques.EnfoqueNoExiste):
            enfoques.ficha("arquitectura")

    def test_un_campo_obligatorio_que_falta_se_ve(self) -> None:
        _indice(self.tmp, [{"nombre": "x", "titulo": "", "resumen": "r",
                            "bloque": "x.md"}])
        with self.assertRaises(enfoques.EnfoqueNoExiste) as cm:
            enfoques.ficha("x")
        self.assertIn("titulo", str(cm.exception))

    def test_el_tope_de_caracteres_trunca_y_lo_dice(self) -> None:
        _indice(self.tmp, [self.uno(
            texto="x" * (enfoques.MAX_CHARS + 500))])
        texto = enfoques.bloque("arquitectura")
        self.assertLessEqual(len(texto), enfoques.MAX_CHARS + 40)
        self.assertIn("truncado por tamaño", texto)

    def test_el_indice_no_es_una_ficha(self) -> None:
        """Los ficheros sueltos sin entrada en el índice no son enfoques.

        Con la estructura de fases esto seitrileaba con el `_` del nombre. Aquí es
        explícito: lo que no está en `_indice.json` no se puede ni pedir ni
        aplicar, y por tanto no cierra nada.
        """
        (self.tmp / "suelto.md").write_text("nada", encoding="utf-8")
        _indice(self.tmp, [self.uno()])
        self.assertEqual(enfoques.nombres(), ["arquitectura"])


class TestNombreDesconocido(_PisoEnfoques):
    def test_el_error_lista_los_que_si_hay(self) -> None:
        """Un 7B escribe «arquitecturas». El error le deja arreglarse solo."""
        _indice(self.tmp, [self.uno()])
        with self.assertRaises(enfoques.EnfoqueNoExiste) as cm:
            enfoques.ficha("arquitecturas")
        texto = str(cm.exception)
        self.assertIn("arquitecturas", texto)
        self.assertIn("arquitectura", texto)
        # Y le dice que puede seguir sin ninguno: un error que obliga a elegir
        # algo es un error que miente sobre la obligatoriedad.
        self.assertIn("sigue sin ninguno", texto)


class TestPresupuesto(_PisoEnfoques):
    """El tope se comprueba en cada petición, no solo al cargar el índice."""

    def test_uno_nuevo_cabe(self) -> None:
        _indice(self.tmp, [self.uno(texto="x" * 100)])
        cabe, _ = enfoques.cabe("arquitectura", ())
        self.assertTrue(cabe)

    def test_repetir_el_mismo_no_cabe(self) -> None:
        _indice(self.tmp, [self.uno(texto="x" * 100)])
        cabe, motivo = enfoques.cabe("arquitectura", ("arquitectura",))
        self.assertFalse(cabe)
        self.assertIn("ya estás", motivo)

    def test_el_segundo_que_no_cabe_lo_dice_con_cifras(self) -> None:
        _indice(self.tmp, [self.uno(nombre="a", texto="x" * 2000),
                           self.uno(nombre="b", texto="x" * 2000)])
        cabe, motivo = enfoques.cabe("b", ("a",))
        self.assertFalse(cabe)
        # El motivo lleva las cifras porque «no cabe» sin decir cuánto es
        # esconderse. Y el aviso que no dice por qué hay que buscarlo es la clase
        # de error que este repo ya pagó dos veces (A-042, A-055).
        self.assertIn("2000", motivo)
        self.assertIn("A-016", motivo)

    def test_el_tope_de_activos_se_cumple_acumulando(self) -> None:
        """El tope va sobre los **activos**, no sobre lo que cabe de una en una.

        Comprobado acumulando, porque `cabe(n, ())` con la lista vacía no puede
        fallar nunca: la pregunta no es «¿cabe este?», sino «¿cabe este **encima**
        de lo que ya llevas?». Un test que solo mirara la lista vacía daría verde
        con cualquier tope.
        """
        _indice(self.tmp, [self.uno(nombre=n, texto="x" * 10) for n in "abcd"])
        activos: list[str] = []
        for n in "abcd":
            cabe, _ = enfoques.cabe(n, tuple(activos))
            if cabe:
                activos.append(n)
        self.assertEqual(len(activos), enfoques.MAX_ACTIVOS)


class TestLosDientes(_PisoEnfoques):
    """Lo que el enfoque cierra lo cierra `decide()`, no el prompt."""

    def test_restringe_devuelve_las_tools_del_indice(self) -> None:
        _indice(self.tmp, [self.uno(restringe=["aegis_write_file"])])
        self.assertEqual(enfoques.restringe("arquitectura"), ["aegis_write_file"])

    def test_sin_enfoque_no_cierra_nada(self) -> None:
        _indice(self.tmp, [self.uno(restringe=["aegis_write_file"])])
        self.assertEqual(enfoques.restringe(""), [])

    def test_una_tool_cerrada_no_se_ejecuta(self) -> None:
        from app import autonomy
        _indice(self.tmp, [self.uno(restringe=["aegis_write_file"])])
        d = autonomy.decide("aegis_write_file", {"path": "x.txt"},
                            run_id="r", paso=1, enfoque="arquitectura")
        self.assertFalse(d.ok)
        self.assertIn("arquitectura", d.motivo)
        self.assertIn("usar_enfoque", d.motivo,
                      "el motivo tiene que decir cómo se sale")

    def test_una_tool_permitida_pasa(self) -> None:
        from app import autonomy
        _indice(self.tmp, [self.uno(restringe=["aegis_write_file"])])
        d = autonomy.decide("aegis_read_file", {"path": "x.txt"},
                            run_id="r", paso=1, enfoque="arquitectura")
        self.assertTrue(d.ok)

    def test_sin_enfoque_el_cierre_no_existe(self) -> None:
        from app import autonomy
        _indice(self.tmp, [self.uno(restringe=["aegis_write_file"])])
        d = autonomy.decide("aegis_write_file", {"path": "x.txt"},
                            run_id="r", paso=1)
        self.assertNotIn("arquitectura", d.motivo)


class TestLaToolQueLoPide(_PisoEnfoques):
    """`usar_enfoque`: el por qué es el razonamiento, y por eso es obligatorio."""

    def test_sin_por_que_no_adjunta(self) -> None:
        from app import mcp_ops
        _indice(self.tmp, [self.uno()])
        salida = mcp_ops.usar_enfoque("arquitectura", "")
        self.assertIn("por qué", salida)
        self.assertNotIn("ENFOQUE ACTIVO", salida)

    def test_un_nombre_que_no_existe_no_tumba_nada(self) -> None:
        """Las tools de Aegis no lanzan: devuelven el motivo.

        Un `raise` aquí sería un run que muere por un nombre mal escrito, que es
        justo lo que un 7B hace a menudo.
        """
        from app import mcp_ops
        _indice(self.tmp, [self.uno()])
        salida = mcp_ops.usar_enfoque("arquitecturas", "porque me lo parece")
        self.assertIn("no hay ningún enfoque", salida)

    def test_con_por_que_devuelve_el_bloque(self) -> None:
        from app import mcp_ops
        _indice(self.tmp, [self.uno(restringe=["aegis_write_file"])])
        salida = mcp_ops.usar_enfoque("arquitectura", "hay dos motores razonables")
        self.assertIn("ENFOQUE ACTIVO", salida)
        self.assertIn("Cuerpo de arquitectura", salida)
        # Y dice qué cierra: para que Aegis no lo descubra pidiéndolo.
        self.assertIn("aegis_write_file", salida)
        self.assertIn("hay dos motores razonables", salida)

    def test_soltar_no_esta_activo(self) -> None:
        from app import mcp_ops
        _indice(self.tmp, [self.uno()])
        self.assertIn("Sin enfoque activo", mcp_ops.usar_enfoque(""))


class TestElBucle(_PisoEnfoques):
    """El estado del enfoque vive en el bucle, y cambia antes de la autonomía."""

    def test_activa_con_razon(self) -> None:
        from app.autopilot import _aplicar_enfoque
        _indice(self.tmp, [self.uno(texto="x" * 100)])
        activos, nota = _aplicar_enfoque(
            {"nombre": "arquitectura", "por_que": "hay dos motores"}, [])
        self.assertEqual(activos, ["arquitectura"])
        self.assertIn("hay dos motores", nota)

    def test_sin_razon_no_activa(self) -> None:
        from app.autopilot import _aplicar_enfoque
        _indice(self.tmp, [self.uno()])
        activos, _ = _aplicar_enfoque({"nombre": "arquitectura", "por_que": ""}, [])
        self.assertEqual(activos, [])

    def test_soltar_vacia(self) -> None:
        from app.autopilot import _aplicar_enfoque
        _indice(self.tmp, [self.uno()])
        activos, nota = _aplicar_enfoque({"nombre": ""}, ["arquitectura"])
        self.assertEqual(activos, [])
        self.assertIn("suelta", nota)

    def test_lo_que_no_cabe_no_activa(self) -> None:
        from app.autopilot import _aplicar_enfoque
        _indice(self.tmp, [self.uno(texto="x" * (enfoques.MAX_CHARS + 100))])
        activos, nota = _aplicar_enfoque(
            {"nombre": "arquitectura", "por_que": "x"}, [])
        self.assertEqual(activos, [])
        self.assertIn("no cabe", nota)


class TestPrompt(_PisoEnfoques):
    def _prompt(self, project: str, enfoque: str) -> str:
        from app.autopilot import build_system_prompt
        with mock.patch("app.autonomy.almacen", lambda: mock.Mock(
                resume_denegaciones=lambda limite=4: "")):
            return build_system_prompt("", project, "", enfoque=enfoque)

    def test_sin_enfoque_no_aporta_nada(self) -> None:
        _indice(self.tmp, [self.uno()])
        self.assertEqual(enfoques.bloque(""), "")

    def test_el_enfoque_se_anuncia_con_su_nombre(self) -> None:
        _indice(self.tmp, [self.uno()])
        self.assertIn("Cómo se construye", self._prompt("aegis", "arquitectura"))

    def test_un_enfoque_que_no_existe_no_altera_el_prompt(self) -> None:
        """Un parámetro de una app no puede cambiar el prompt ni una letra."""
        _indice(self.tmp, [self.uno()])
        a = self._prompt("aegis", "")
        b = self._prompt("aegis", "no-existe")
        self.assertEqual(a, b)

    def test_el_enfoque_anuncia_las_herramientas_que_cierra(self) -> None:
        _indice(self.tmp, [self.uno(restringe=["aegis_write_file"])])
        prompt = self._prompt("aegis", "arquitectura")
        self.assertIn("aegis_write_file", prompt)
        self.assertIn("prohibida", prompt)

    def test_sin_proyecto_no_entra_la_parte_de_proyectos(self) -> None:
        """El arreglo de fondo del uso cotidiano.

        `metodo.md` estaba escrito entero como si siempre hubiera un proyecto, así
        que una pregunta por la mañana cargaba instrucciones sobre emuladores y
        scrubbers que no iban a usarse. Con el proyecto vacío solo entra la parte
        que aplica siempre.
        """
        with_project = self._prompt("aegis", "")
        without = self._prompt("", "")
        self.assertIn("el emulador", with_project)
        self.assertNotIn("el emulador", without)
        self.assertLess(len(without), len(with_project))


class TestLoQueHayEnDisco(unittest.TestCase):
    """El registro de verdad, sin falseos: lo que se publica tiene que estar bien."""

    def test_los_publicados_caben_en_el_presupuesto(self) -> None:
        for nombre in enfoques.nombres():
            self.assertLessEqual(len(enfoques.bloque(nombre)),
                                 enfoques.MAX_CHARS,
                                 f"el enfoque '{nombre}' se pasó del tope")

    def test_lo_que_cerran_son_tools_de_verdad(self) -> None:
        from app.autopilot import allowed_tools
        reales = allowed_tools()
        for nombre in enfoques.nombres():
            for tool in enfoques.restringe(nombre):
                self.assertIn(tool, reales,
                              f"'{nombre}' cierra '{tool}', que no es una tool")

    def test_ningun_enfoque_repite_a_metodo(self) -> None:
        """Un enfoque no puede **preguntar** lo que `metodo.md` ya pregunta.

        `idea` se quitó a propósito: aterrizar una idea hasta poder escribir su
        ficha ya lo hace `metodo.md`, en **todos** los runs, así que tenerlo
        además como enfoque era pagar dos veces. Y aquí pagar dos veces cuesta
        concreto: el prompt se paga **en cada paso de cada run** (37k chars
        medidos), así que un bloque redundante se paga docenas de veces por run.

        El test pasó de contar enfoques a comprobar el principio, porque el
        principio es lo que hay que proteger: un recuento solo congela una
        decisión pasada, y no dice nada del enfoque que venga mañana.

        ## Por qué la comprobación es afirmativa
        La primera versión hacía `if frase in bloque: assertNotIn(...)`, y eso
        **pasa en vacío**: si nadie repite nada, no comprueba nada. Un test que
        no puede fallar es peor que no tener test (A-088). Ahora se afirma que
        la frase **no** está, siempre.
        """
        from app.method import load_method
        metodo = load_method().lower()
        # Se afirma que metodo.md **sí** las tiene. Si algún día se le quitan,
        # los enfoques dejan de poder apoyarse en él y esto hay que notar.
        self.assertIn("qué problema resuelve", metodo,
                      "metodo.md perdio las preguntas que los enfoques no repiten")
        for nombre in enfoques.nombres():
            if nombre == "producto":
                continue      # lo declara explicito en su bloque; testeado aparte
            bloque = enfoques.bloque(nombre).lower()
            for frase in ("qué problema resuelve", "cómo se sabrá que funcionó",
                          "qué alternativas se consideró"):
                self.assertNotIn(frase, bloque,
                                 f"el enfoque '{nombre}' repite «{frase}», que "
                                 "metodo.md ya dice en todos los runs")

    def test_producto_no_repite_las_seis_preguntas(self) -> None:
        """El caso concreto de `producto`, escrito aparte para que se lea.

        Las seis preguntas de "antes de construir" viven en `metodo.md`, en todos
        los runs. Copiarlas en el enfoque es exactamente el `idea` que se borró.
        """
        producto = enfoques.bloque("producto").lower()
        # Se comprueba que NO aparecen como pregunta que el enfoque hace. Nombra
        # `metodo.md` y dice que no las repite, y eso está permitido: lo que no
        # vale es volver a contestarlas.
        for pregunta in ("1. **qué problema resuelve**",
                         "2. **para qué se usa**",
                         "3. **quién lo usa**",
                         "6. **qué queda explícitamente fuera"):
            self.assertNotIn(pregunta.lower(), producto,
                             f"producto.md vuelve a preguntar lo que ya pide "
                             f"metodo.md: {pregunta}")
        # Y sí: las tres que metodo.md NO pregunta, están.
        for anadida in ("¿Es un problema tuyo o un problema de la herramienta?",
                        "¿Cuándo lo dejarías de usar?",
                        "¿Hay algo más pequeño?"):
            self.assertIn(anadida.lower(), producto,
                          f"producto.md dejo de preguntar: {anadida}")
        from app.method import load_method
        self.assertIn("Qué problema resuelve", load_method(),
                      "metodo.md perdio las preguntas: el enfoque las necesita")


class TestDerivar(unittest.TestCase):
    """La derivación (A-077): la tool no dispara sola, así que el bridge propone."""

    def test_una_señal_clara_deriva(self):
        self.assertEqual(enfoques.derivar(
            "estoy pensando qué motor de base de datos uso, postgres o sqlite"),
            ("arquitectura", "el encargo dice «qué motor de base de datos»"))

    def test_sin_señal_no_sugiere_nada(self):
        """`None` es la respuesta honesta: mejor sin enfoque que con uno equivocado."""
        self.assertIsNone(enfoques.derivar(
            "agrega un test a la función parsear de app/autopilot.py"))

    def test_encargo_vacío_no_deriva(self):
        self.assertIsNone(enfoques.derivar(""))
        self.assertIsNone(enfoques.derivar("   "))

    def test_es_determinista(self):
        """Mismo encargo, misma respuesta: si no, la traza no es auditable."""
        a = enfoques.derivar("diseñamos la arquitectura del sistema")
        b = enfoques.derivar("diseñamos la arquitectura del sistema")
        self.assertEqual(a, b)
        self.assertEqual(a[0], "arquitectura")

    def test_ignora_mayusculas(self):
        self.assertEqual(enfoques.derivar("DISEÑAMOS LA ARQUITECTURA")[0],
                         "arquitectura")


class TestEnfoqueDerivadoEnElPrompt(unittest.TestCase):
    """Lo derivado se dice como derivado, o la traza está mintiendo."""

    def test_avisa_de_que_lo_puso_el_bridge(self):
        p = autopilot.build_system_prompt(
            enfoque="arquitectura", enfoque_por_que="el encargo dice «postgres o»",
            enfoque_derivado=True)
        self.assertIn("DERIVADO POR EL BRIDGE", p)
        self.assertIn("No lo pediste tú", p)
        self.assertIn("«postgres o»", p)

    def test_el_derivado_se_puede_soltar(self):
        """Si no se puede corregir, derivar es imponer. Y pasar el prompt es inútil."""
        p = autopilot.build_system_prompt(
            enfoque="arquitectura", enfoque_por_que="x", enfoque_derivado=True)
        self.assertIn("usar_enfoque(nombre='')", p)

    def test_el_fijado_no_dice_que_lo_derivó(self):
        p = autopilot.build_system_prompt(enfoque="arquitectura")
        self.assertIn("ENFOQUE FIJADO", p)
        self.assertNotIn("DERIVADO", p)
        self.assertNotIn("No lo pediste tú", p)

    def test_sin_enfoque_no_hay_bloque(self):
        p = autopilot.build_system_prompt()
        self.assertNotIn("ENFOQUE", p)


class TestTrazaDelEnfoqueDerivado(unittest.TestCase):
    """Lo derivado tiene que verse en la traza, o no se puede auditar (A-077).

    Y aquí estaba el fallo: la entrada del paso 0 se escribía en `trace` y acto
    seguido una re-declaración la borraba. Lo que se ve en `GET /autopilot/{id}`
    no era lo que había pasado, y sin esto el enfoque se elegía a oscuras. Por eso
    esto se prueba **sin** modelo: si depended de una inferencia, tardaría medio
    minuto y acabaría sin comprobarse.
    """

    def test_la_derivacion_aparece_en_la_traza(self):
        activos, motivo, entrada = autopilot._sembrar_enfoque(
            "", "qué motor de base de datos uso, postgres o sqlite")
        self.assertEqual(activos, ["arquitectura"])
        self.assertTrue(motivo)
        self.assertEqual(entrada["step"], 0)
        self.assertEqual(entrada["action"], "enfoque_derivado")
        self.assertEqual(entrada["enfoque"], "arquitectura")
        self.assertEqual(entrada["propuesto_por"], "bridge")
        self.assertEqual(entrada["por_que"], motivo)

    def test_un_encargo_normal_no_inventa_enfoque(self):
        """Sin señal no hay entrada: una traza con enfoques de más no informa."""
        activos, motivo, entrada = autopilot._sembrar_enfoque(
            "", "agrega un test a la función parsear")
        self.assertEqual(activos, [])
        self.assertEqual(motivo, "")
        self.assertEqual(entrada, {})

    def test_lo_fijado_manda_sobre_lo_derivado(self):
        """Quien elige en la app sabe más que una regla, y no se pisa con ella."""
        activos, motivo, entrada = autopilot._sembrar_enfoque(
            "arquitectura", "qué motor de base de datos uso")
        self.assertEqual(activos, ["arquitectura"])
        # Sin `propuesto_por`: no lo puso el bridge, lo puso una persona.
        self.assertEqual(entrada, {})
        self.assertEqual(motivo, "")


if __name__ == "__main__":
    unittest.main()
