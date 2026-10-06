# 001 — El objetivo es un asistente ambiental, y las invariantes cambian de forma

> 2026-10-05. Primera decisión del registro, y la que habilita todas las demás.

## El problema

Aegis está construido como un producto de **trazabilidad**: un agente que escribe
código y deja rastro de lo que hizo. El objetivo es un producto de **latencia**: un
asistente ambiental con voz, sentidos, manos, memoria e iniciativa.

Son dos productos con arquitecturas opuestas. Uno tolera esperar 58 segundos; el otro
muere si tarda un segundo. No se pueden tener los dos, y hoy solo existe uno.

## Opciones

**A. Mantener el producto actual y no ir a por el ambiente.** Coste: cero. Se
conserva un buen escritor de código con guardarraíles. Renuncia a voz, cámara y
omnipresencia, y al objetivo.

**B. Ambiental, cambiando las invariantes de forma.** Coste: hay que reescribir el
criterio de seguridad. Se acepta que Aegis tenga autoridad local, y se compensa con
la regla que de verdad importa: **ninguna acción irreversible sin aprobación de un
solo uso, y ningún pago automático**. Se acepta también que Aegis pueda caerse, y se
exige que se apaga bien.

**C. Ambiental sin cambiar las invariantes.** Coste: bajo, y es una trampa. Significa
un asistente que vigila tu casa y decide sobre tu dinero y que además no es
autoridad: o no hace nada útil, o hace cosas que no debería. Es peor que las otras
dos porque parece que las cumple.

## Recomendación

**B.** Motivo: las invariantes originales protegían algo bueno —que Aegis no actuara
en silencio— y eso **no cambia** cuando le das autoridad. Lo que cambia es *de dónde
viene el silencio*: antes venía de la ausencia de permisos, ahora tiene que venir de
un mecanismo concreto.

A es la opción honesta si el objetivo no es el ambiente. C no es una opción.

## Qué lo falsaría

Que F1 (voz cortocircuito) no se pueda hacer con < 1 s de latencia en el hardware
actual, después de F0. Si F0 no consigue bajar la latencia trivial, el problema no
son las invariantes: es que el hardware no da, y entonces la respuesta es A —
aceptar que Aegis es un escritor de código y no un asistente.

Es una prueba barata: se mide en una tarde.

## Qué invariante toca

Las tres. Se reescriben en `docs/vision.md` §4.

## Lo que queda fuera de esta decisión

El **reconocimiento facial** no está dentro. Es una cuestión de privacidad y legal,
no de ingeniería, y es de las pocas que no se pueden deshacer una vez dentro de una
casa. No se decide aquí: se decide en su propio documento, cuando F1-F3 funcionen.