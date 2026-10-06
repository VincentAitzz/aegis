"""El anuncio del bridge en la red local.

## Qué se prueba
Tres cosas, y la tercera es la que de verdad importa:

1. **Qué direcciones anuncia.** Filtra loopback y los puentes de Docker, y
   **conserva** la de Tailscale. Esto se rompió una vez: `getaddrinfo(gethostname())`
   resuelve por `/etc/hosts` a `127.0.1.1`, así que el método devolvía lista
   vacía y se habría registrado un anuncio que no encuentra nadie. El filtro
   estaba bien; lo que estaba mal era de dónde salían las direcciones.

2. **Que no filtra nada de lo que importa.** El anuncio dice que hay un bridge y
   de qué versión. Ni token, ni fichas, ni proyectos.

3. **Que un fallo al anunciarse no rompe nada.** Es la invariante del módulo: el
   descubrimiento no puede retrasar ni tumbar el arranque. Se comprobó que
   `register_service` tarda 90 s y lanza `TimeoutError` sin red.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import descubrimiento as desc  # noqa: E402


class _Adaptador:
    def __init__(self, nombre, ips):
        self.nice_name = nombre
        self.ips = [_IP(i) for i in ips]


class _IP:
    def __init__(self, ip):
        self.ip = ip
        self.is_IPv4 = ":" not in ip


def _con_interfaces(mapa):
    """Parchea `ifaddr.get_adapters` con un mapa `interfaz -> ips`."""
    adaptadores = [_Adaptador(n, ips) for n, ips in mapa.items()]
    import ifaddr
    return mock.patch.object(ifaddr, "get_adapters", return_value=adaptadores)


class TestQueDireccionesAnuncia(unittest.TestCase):
    def test_queda_la_de_la_lan(self) -> None:
        with _con_interfaces({"wlan0": ["192.168.0.51"]}):
            self.assertEqual(desc.interfaces_de_red(), ["192.168.0.51"])

    def test_no_anuncia_loopback(self) -> None:
        """Anunciar `127.0.0.1` haría que el móvil fuera a buscarlo a sí mismo."""
        with _con_interfaces({"lo": ["127.0.0.1"], "wlan0": ["192.168.0.51"]}):
            self.assertEqual(desc.interfaces_de_red(), ["192.168.0.51"])

    def test_no_anuncia_docker(self) -> None:
        """Nadie busca un bridge en la red de Docker, y una dirección de más es
        una que el móvil puede probar y fallar antes de llegar a la buena."""
        with _con_interfaces({"docker0": ["172.17.0.1"], "wlan0": ["192.168.0.51"]}):
            self.assertEqual(desc.interfaces_de_red(), ["192.168.0.51"])

    def test_no_anuncia_puente_por_prefijo_de_nombre(self) -> None:
        """Va por nombre de interfaz, no por prefijo de IP.

        El prefijo `172.16/12` se puede reconfigurar y `docker0` no, así que el
        nombre es lo que no miente.
        """
        with _con_interfaces({"br-c0ffee": ["172.18.0.1"], "wlan0": ["192.168.0.51"]}):
            self.assertEqual(desc.interfaces_de_red(), ["192.168.0.51"])

    def test_conserva_la_de_tailscale(self) -> None:
        """Es una red válida y solo responde quien ya podía hablar con el bridge."""
        with _con_interfaces({"wlan0": ["192.168.0.51"], "tailscale0": ["100.101.102.100"]}):
            self.assertIn("100.101.102.100", desc.interfaces_de_red())

    def test_la_lan_va_primero(self) -> None:
        """La LAN es donde el móvil y el bridge casi siempre están.

        El orden decide cuál prueba la app primero, y probar una dirección que
        no va a responder es un segundo perdido en cada arranque.
        """
        with _con_interfaces({"tailscale0": ["100.101.102.100"], "wlan0": ["192.168.0.51"]}):
            self.assertEqual(desc.interfaces_de_red()[0], "192.168.0.51")

    def test_no_anuncia_link_local(self) -> None:
        with _con_interfaces({"wlan0": ["169.254.1.1", "192.168.0.51"]}):
            self.assertEqual(desc.interfaces_de_red(), ["192.168.0.51"])

    def test_sin_ifaddr_no_revienta(self) -> None:
        """Cae al resolver por nombre, que puede no ver la LAN, pero no muere."""
        import ifaddr
        with mock.patch.dict(sys.modules, {"ifaddr": None}):
            with mock.patch.object(
                desc.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("192.168.0.51", 0))]
            ):
                self.assertEqual(desc.interfaces_de_red(), ["192.168.0.51"])

    def test_sin_red_devuelve_lista_vacia_y_no_lanza(self) -> None:
        """Sin direcciones no hay anuncio, pero `registrar` lo dirá en vez de
        Registrarse con un `addresses=[]` que es un anuncio invisible."""
        with _con_interfaces({}):
            self.assertEqual(desc.interfaces_de_red(), [])


class TestElAnuncioNoFiltra(unittest.TestCase):
    def test_el_txt_solo_lleva_la_version(self) -> None:
        """Ni token, ni fichas, ni proyectos: eso lo exige `X-Aegis-Token`.

        El anuncio no es una puerta, es una dirección. Si un día lleva algo más,
        este test es el que lo dice.
        """
        self.assertEqual(desc.texto_de_anuncio("0.1.0"), {"version": "0.1.0"})

    def test_el_tipo_es_el_que_se_busca(self) -> None:
        self.assertEqual(desc.TIPO, "_aegis._tcp.local.")

    def test_el_nombre_no_choca_con_el_hostname(self) -> None:
        """El bug real, medido.

        Con el nombre corto, `zeroconf` levanta `NonUniqueNameException` y el
        anuncio no se registra. La causa está en `ps`: hay un `avahi-daemon`
        publicando `Aegis.local`, porque el hostname de esta máquina **es**
        `Aegis`, y los nombres DNS-SD no distinguen mayúsculas.

        No es una expiración rara: este repo vive en un portátil cuyo hostname es
        el nombre de lo que publica. Chocar con el nombre del host es el caso
        normal aquí, no el raro.
        """
        self.assertNotEqual(desc.NOMBRE, "aegis")
        import socket
        self.assertNotEqual(
            desc.NOMBRE.lower(), socket.gethostname().lower(),
            "el nombre de instancia coincide con el hostname, que es lo que "
            "avahi ya publica en esta máquina")


class TestUnFalloNoRompeElArranque(unittest.TestCase):
    """La invariante del módulo, y la razón del `except` ancho.

    Se comprobó: `register_service` puede tardar **90 s** y lanzar `TimeoutError`
    en un entorno sin red. Un test del lifespan pasó de 4 s a 94 con un anuncio
    que no hacía falta, y un puente que tarda un minuto y medio en arrancar
    porque un servicio de comodidad no respondió es un puente roto.
    """

    def setUp(self) -> None:
        desc.retirar()
        self.addCleanup(desc.retirar)

    def test_un_timeout_no_lanza(self) -> None:
        with _con_interfaces({"wlan0": ["192.168.0.51"]}):
            with mock.patch("zeroconf.Zeroconf") as zc:
                zc.return_value.register_service.side_effect = TimeoutError("90 s")
                resultado = desc.registrar(8000, "0.1.0")
        self.assertIn("NO ANUNCIO", resultado)
        self.assertFalse(desc.announcing())

    def test_no_deja_medio_anunciar(self) -> None:
        """Si falla el registro, no puede quedar `announcing()` diciendo que sí."""
        with _con_interfaces({"wlan0": ["192.168.0.51"]}):
            with mock.patch("zeroconf.Zeroconf") as zc:
                zc.return_value.register_service.side_effect = OSError("sin red")
                desc.registrar(8000)
        self.assertFalse(desc.announcing())

    def test_falta_zeroconf_no_lanza(self) -> None:
        with mock.patch.dict(sys.modules, {"zeroconf": None}):
            self.assertIn("NO ANUNCIO", desc.registrar(8000))
        self.assertFalse(desc.announcing())

    def test_registrarse_dentro_de_un_loop_asyncio_no_lanza(self) -> None:
        """El otro bug real, y el que hizo que el bridge arrancara sin anunciar.

        `Zeroconf()` creado con un loop de asyncio corriendo lanza
        `EventLoopBlocked` al instante —es el `lifespan` de uvicorn—, así que el
        registro va en un hilo propio. Sin esto el bridge se levanta con «NO
        ANUNCIO» y **nada parece roto**: el puente funciona, solo no se encuentra.
        """
        import asyncio

        async def dentro_de_loop():
            with _con_interfaces({"wlan0": ["192.168.0.51"]}):
                with mock.patch("zeroconf.Zeroconf") as zc:
                    zc.return_value.register_service.side_effect = TimeoutError("90 s")
                    resultado = desc.registrar(8000)
            return resultado

        self.assertIn("NO ANUNCIO", asyncio.run(dentro_de_loop()))
        self.assertFalse(desc.announcing())

    def test_el_hilo_no_puede_dejar_medio_anunciar(self) -> None:
        """Si el hilo no termina a tiempo, no puede quedar `announcing()` diciendo
        que sí: el bridge seguiría vivo sin anuncio y nadie lo sabría."""
        with mock.patch.object(desc.threading, "Thread") as hilo:
            instancia = mock.Mock()
            instancia.is_alive.return_value = True
            hilo.return_value = instancia
            resultado = desc.registrar(8000)
        self.assertIn("no respondió", resultado)
        self.assertFalse(desc.announcing())

    def test_retirar_es_idempotente(self) -> None:
        """Se llama en el `finally` del lifespan **y** con `atexit`; los dos a la
        vez tienen que ser inofensivos."""
        desc.retirar()
        desc.retirar()
        self.assertFalse(desc.announcing())

    def test_anunciarse_dos_veces_no_duplica(self) -> None:
        with _con_interfaces({"wlan0": ["192.168.0.51"]}):
            with mock.patch("zeroconf.Zeroconf") as zc:
                self.assertIn("anunciado", desc.registrar(8000))
                self.assertIn("ya anunciado", desc.registrar(8000))
        self.assertEqual(zc.call_count, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()