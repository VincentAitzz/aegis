# Seguridad

## Qué reporta este documento

Si has encontrado un fallo **de seguridad** en Aegis, no abras una issue pública.
Escríbeme por privado (GitHub → *Security advisories* → *Report a vulnerability*,
o el correo que salga en el perfil del repo).

Una issue pública puede darle a alguien la respuesta antes de que haya un
parche. Cuando lo tengas preparado, o cuando de verdad no quede nadie expuesto,
se publica.

## Qué cuenta como fallo de seguridad

En orden de gravedad:

1. **Que Aegis ejecute algo sin la aprobación que exige.** El invariante es
   *nada irreversible por su cuenta y siempre se puede saber qué hizo y por
   qué*. Un bypass de la cola de aprobaciones es lo más grave que puede pasar
   aquí, porque el bridge tiene escritura sobre tus proyectos.
2. **Que un tercero reciba algo íntimo.** Audio, fotogramas, rostros o el
   contenido de la bóveda TOTP travele a un servidor sin permiso explícito y
   medible. Nota: `boveda_keystore_test.dart` prueba contra el Keystore real de
   Android, no contra un doble — que un doble en memoria no detectaría un cambio de
   cómo se guarda.
3. **Que un secreto acabe en un archivo o en un log.** El escaneo de secretos está
   en el camino de escritura y **antes** que la puerta de fichas, para que una
   ficha ausente nunca enmascare un secreto.
4. **Que la memoria o el prompt se puedan manipular desde fuera.** Es el ataque
   documentado contra `USER.md` de otros sistemas (ClawHavac: base64 y
   caracteres de ancho cero en ficheros que entran en el prompt). Por eso
   `quien-eres.md` se escribe solo con nivel 3, y la aprobación lleva el texto
   entero delante.

## Qué **no** es un fallo

- **Aegis no acierta.** Es un modelo de 7 GB en local; falla, se equivoca y a
  veces hace preguntas tontas. Eso es el estado del arte, no una vulnerabilidad.
- **Aegis ejecuta lo que le pides.** Esa es la función. Si le dices que borre
  algo y lo borra, con la aprobación que tocaba, ha hecho bien su trabajo.
- **La app se ve bien pero hace algo raro en tu máquina.** Suele ser la
  configuración: mira `docs/runbook.md` §4 antes de escribirme.

## Qué hace Aegis ya para que esto no pase

Esto está en el código y tiene tests, no es una promesa de la página:

| Mecanismo | Dónde |
|---|---|
| Cola de aprobación de un solo uso para toda acción con consecuencia | `app/autonomy.py` |
| Whitelist multi-raíz + denylist + escaneo de secretos | `app/mcp_ops.py` |
| Rollback de sintaxis: si el archivo no parsea, no llega al repo | `app/mcp_ops.py` |
| Veredicto desde la traza, nunca desde el texto del modelo | `app/veredicto.py` |
| Después de 6 h, todo dispositivo cae a estado seguro | en el diseño |
| TOTP en el Keystore de Android, no en almacenamiento de la app | `mobile/lib/core/auth/`, probada en `integration_test/` |

## Un aviso sobre el debug signing

Desde el 2026-10-13 la build de release se firma con una clave propia, en
`~/.config/aegis/key.properties` (fuera del repo). Antes usaba la clave de
debug del SDK de Android, que es pública.

No es «menos seguro»: en Android el Keystore se indexa por paquete **y**
certificado, así que cualquiera que genere un APK con el mismo
`com.aegis.aegis_console` firmado en debug obtiene **la misma identidad** y
acceso a ese almacén. Y como un APK firmado en debug funciona exactamente igual
que uno bien firmado, el error no se ve: la app abre, lista las cuentas y genera
códigos buenos.

Por eso `infra/mobile/install-phone.sh` comprueba la firma antes de instalar y
aborta, y por eso la build de release **falla** si no encuentra
`key.properties` en vez de caer a debug.

Para rotar la clave hay que **desinstalar y reinstalar**: Android no acepta que
el sustituto venga de otro firmante.