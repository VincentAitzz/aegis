# Aegis

Asistente ambiental local-first: un agente que vive en tu propia máquina, oye lo
que le dices, ejecuta sobre tus herramientas y te avisa de los problemas que
encuentra. Sin nube, sin cuenta, y sin una sola petición a un tercero.

Copyright (C) 2025-2026 los autores de Aegis (ver `git log`).

Este programa es software libre: puedes redistribuirlo y modificarlo bajo los
términos de la Licencia Affero General Pública v3.0, publicada por la Free
Software Foundation.

Este programa se distribuye SIN GARANTÍA ALGUNA, sin siquiera la garantía
implícita de COMERCIALIZACIÓN o IDONEIDAD PARA UN PROPÓSITO PARTICULAR. Ver la
`LICENSE` para el texto completo.

## Por qué AGPL y no MIT

Porque Aegis tiene una parte que se ejecuta en la máquina de otra persona: el
bridge aplica guardarraíles sobre lo que el agente escribe, y decide qué cuenta
como una acción con consecuencias. Esa parte **es** el proyecto.

Con MIT, alguien podría montar un servicio comercial sobre este código y
cerrarlo. Con AGPL-3.0, si lo haces **por red**, tienes que ofrecer el
código fuente de lo que hayas modificado.

No es una cláusula de «si vendes, compartes» sobre el uso: afecta a lo que pasa
cuando Aegis deja de ser solo tuyo.

## Lo que la AGPL no restringe

- Usarlo, modificarlo y distribuirlo, incluso comercialmente, publicando tus
  cambios.
- Escribir tus propias herramientas y conectarlas: la capa de tools es pública
  y es la única forma de extender Aegis con acciones nuevas.
- Contribuir, sin ningún acuerdo previo.

Si tu caso es «quiero ofrecer Aegis como servicio» y no encaja, abre una
issue y lo hablamos. Una licencia dual es posible y prefiero que descubras el
problema antes de invertir en él, no después.