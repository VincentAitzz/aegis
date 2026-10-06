"""El bridge se anuncia en la red local, para que el móvil lo encuentre solo.

## Por qué existe esto
El `API_HOST` que viaja dentro del APK **no es una dirección estable**. Son dos
las que hay, y las dos fallan solas:

- la de la **Tailscale** se desactiva en el móvil por su cuenta cuando pasa un
  rato, y entonces el móvil deja de ver el bridge sin que nadie haya tocado nada;
- la de la **LAN** es DHCP: hoy es `192.168.0.51` y mañana puede ser otra, y si
  el móvil está en otra red ni existe.

Un host hornearado produce la peor clase de fallo: la app **abre**, pinta, y no
ve nada. No hay error, solo silencio.

## Por qué mDNS y no buscar direcciones
La alternativa —que el móvil pruebe las 254 direcciones de la subred buscando un
`:8000` que conteste— funciona, pero hace 254 conexiones en cada arranque fallido
y tiene que acertar la subred. mDNS pregunta una vez y la respuesta trae
dirección, puerto y nombre.

## Qué filtra el anuncio
Que hay un bridge en esta red y qué versión habla. **No** el token, ni las
fichas, ni los proyectos: eso lo exige `X-Aegis-Token` en cada llamada, y aquí
no hay ninguna. El anuncio no es una puerta, es una dirección.

## Por qué se retira al parar
Un anunciante vivo después de apagar el bridge es la forma de que alguien intente
conectarse a un servicio que ya no existe y no entienda por qué. `parar()` es
explícito y `zeroconf` manda los dos goodbye, así que el móvil deja de verlo
enseguida.
"""

from __future__ import annotations

import atexit
import ipaddress
import logging
import socket
from typing import Optional

log = logging.getLogger("aegis.descubrimiento")

#: Tipo de servicio que se registra y se busca. Sin sufijo de dominio: el
#: protocolo es `_tcp` y el nombre `_aegis`, que es lo que resolvería `aegis.local`.
TIPO = "_aegis._tcp.local."
NOMBRE = "aegis"

#: Puerto del bridge. Se lee de los settings al registrar, no se fija aquí: si
#: alguien mueve el puerto, un valor fijo anunciaría uno que no escucha y el móvil
#: encontraría el bridge para no poder hablar con él.
_puerto: Optional[int] = None
_zeroconf = None
_registrado = False


def interfaces_de_red() -> list[str]:
    """Direcciones IPv4 que pueden servir para mDNS, en orden de preferencia.

    ## Por qué no `getaddrinfo(gethostname())`
    Porque en esta máquina resuelve por `/etc/hosts` a `127.0.1.1`, que es
    loopback y por tanto inútil: el método devolvía **lista vacía** y el anuncio
    se habría registrado sin direcciones, que es un anuncio que no encuentra
    nadie. El filtro de loopback estaba bien; lo que estaba mal era de dónde
    salían las direcciones.

    ## Por qué `ifaddr` y no `socket`
    `ifaddr` viene **como dependencia de `zeroconf`**, así que no añade nada al
    venv, y recorre los adaptadores de verdad. Leer `/proc/net/route` funciona en
    Linux pero no en nada más, y pedir `ioctl` necesita root.

    ## Qué se descarta
    Loopback y link-local (mDNS es multicast dentro de la red local), y los
    prefijos reservados.

    La de Tailscale **se queda**: es una dirección de red válida, y anunciarla no
    cuesta nada —solo responde quien esté en la misma tailnet, que es quien ya
    podía hablar con el bridge—.

    Los bridges de Docker **se quitan**. Aquí `172.17.0.1` es el `docker0`, que
    no es una red donde el móvil pueda estar: nadie busca un bridge ahí, y una
    dirección de más es una dirección que el móvil puede probar y fallar antes de
    llegar a la buena. Se detectan por nombre de interfaz, no por prefijo, porque
    el prefijo se puede reconfigurar y el nombre no.
    """
    found: list[str] = []

    def anota(ip: str) -> None:
        try:
            addr = ipaddress.IPv4Address(ip)
        except ValueError:
            return
        if addr.is_loopback or addr.is_link_local or addr.is_multicast:
            return
        if addr.is_reserved or addr.is_unspecified:
            return
        if ip not in found:
            found.append(ip)

    try:
        import ifaddr
        adaptadores = ifaddr.get_adapters()
    except ImportError:
        log.info("descubrimiento: sin ifaddr, caigo al resolver por nombre; "
                 "puede no ver las direcciones de la LAN")
        try:
            adaptadores = []
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                anota(info[4][0])
        except OSError as exc:  # noqa: BLE001 — sin red no hay anuncio
            log.info("descubrimiento: no pude resolver el nombre: %s", exc)
            return found
        return found

    for adaptador in adaptadores:
        if _es_puente(adaptador.nice_name):
            continue
        for ip in adaptador.ips:
            if getattr(ip, "is_IPv4", False):
                anota(str(ip.ip))
    # La LAN va primero: es donde el móvil y elbridge están casi siempre, y la
    # de Tailscale solo cuando la tailnet está viva en ambos lados.
    return sorted(found, key=lambda ip: (ip.startswith("100."), ip))


#: Nombres de interfaz que son puentes y no redes donde el móvil pueda estar.
#: Van por nombre y no por prefijo de IP a propósito: `172.16/12` se puede
#: reconfigurar y `docker0` no, así que el nombre es lo que no miente.
PUENTES = ("docker", "br-", "veth", "virbr", "cni", "flannel", "kube", "tun", "tap")


def _es_puente(interfaz: str) -> bool:
    return interfaz.lower().startswith(PUENTES)


def texto_de_anuncio(version: str) -> dict[str, str]:
    """El TXT del anuncio.

    La **versión va aquí** y no solo en el cuerpo porque es lo que permite a la app
    decidir si tiene sentido seguir por este camino: si anuncia una versión
    distinta a la que espera, hay algo raro y conviene decirlo en vez de fallar
    más abajo.
    """
    return {"version": version}


def registrar(puerto: int, version: str = "0.1.0") -> str:
    """Anuncia el bridge. Devuelve lo que anuncie, o el motivo si no pudo.

    Nunca lanza. Un anuncio que falla **no puede impedir que el bridge arranque**:
    es una comodidad de descubrimiento, y perderla degrada el caso de uso —buscar
    la IP a mano— pero no impide trabajar. Por eso la diferencia entre «no pudiste
    anunciar» y «el bridge no está» tiene que ser explícita.
    """
    global _zeroconf, _registrado, _puerto
    if _registrado:
        return f"ya anunciado en {_puerto}"
    try:
        from zeroconf import ServiceInfo, Zeroconf
    except ImportError as exc:
        return f"NO ANUNCIO: falta zeroconf en el venv ({exc})"

    # El `except` es ancho a propósito, y no por descuido: `zeroconf` lanza de
    # todo —`TimeoutError` esperando la respuesta del otro extremo, `socket.error`
    # al abrir el socket, `AttributeError` si la versión cambia la firma de
    # `ServiceInfo`— y el motivo de capturarlos todos es una invariante, no una
    # comodidad:
    #
    #   **el descubrimiento nunca puede retrasar ni tumbar el arranque.**
    #
    # Se comprobó: `register_service` puede tardar 90 s y lanzar `TimeoutError`
    # en un entorno sin red, y un test del lifespan pasó de 4 s a 94 s con un
    # anuncio que no hacía falta. Un puente que tarda un minuto y medio en
    # arrancar porque un servicio de comodidad no respondió es un puente roto,
    # no uno lento.
    try:
        zc = Zeroconf()
        info = ServiceInfo(
            TIPO,
            f"{NOMBRE}.{TIPO}",
            addresses=[ipaddress.IPv4Address(ip).packed for ip in interfaces_de_red()],
            port=puerto,
            properties=texto_de_anuncio(version),
            # El nombre que sale en el discoverer del móvil. Sin esto aparece
            # como un nombre largo con el dominio dentro.
            server=f"{NOMBRE}.local.",
        )
        zc.register_service(info)
    except Exception as exc:  # noqa: BLE001 — ver la invariante de arriba
        log.warning("descubrimiento: no pude anunciarme: %s", exc)
        return f"NO ANUNCIO: {type(exc).__name__}: {exc}"

    _zeroconf, _registrado, _puerto = zc, True, puerto
    atexit.register(retirar)
    ip = ", ".join(interfaces_de_red()) or "sin IPv4 de red local"
    log.info("descubrimiento: anunciado como %s en %s:%s (vía %s)", NOMBRE, ip, puerto, TIPO)
    return f"anunciado en {puerto} vía {ip}"


def retirado() -> bool:
    return not _registrado


def retirar() -> None:
    """Retira el anuncio. Idempotente, y no lanza.

    Se llama en el `finally` del lifespan y también con `atexit`: los dos, porque
    cada uno cubre un apagado que el otro no ve —el `lifespan` cubre uvicorn
   muriendo, `atexit` cubre que el proceso muera sin él— y un anunciante vivo
    después de apagar el bridge es peor que no anunciarse nunca.
    """
    global _zeroconf, _registrado, _puerto
    if not _registrado:
        return
    try:
        _zeroconf.unregister_all_services()
        _zeroconf.close()
    except OSError as exc:
        log.warning("descubrimiento: al retirarme, %s", exc)
    finally:
        _zeroconf, _registrado, _puerto = None, False, None
        log.info("descubrimiento: retirado")


def announcing() -> bool:
    return _registrado