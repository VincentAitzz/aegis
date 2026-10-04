# Fase: arquitectura

La idea ya está escrita. Ahora decides **cómo se va a construir**, y la decisión
tiene que poder defenderse: por qué esta opción y no las otras dos.

## En qué orden decides

1. **Requisitos no funcionales primero.** Cuántos usuarios, qué latencia, cuánto
   cuesta al mes, qué pasa si el servidor está caído una tarde, quién lo
   mantiene. Sin estos números, "Postgres o SQLite" es una discusión de tercieros.
2. **Límites del entorno.** Lo que no se puede cambiar: dónde vive, qué
   plataforma tiene que correr, qué presupuesto de infraestructura hay. Léelos
   antes de proponer nada, no después.
3. **Solo entonces la tecnología**, y **dos o tres opciones**, no una. Una sola
   opción no es una decisión: es una costumbre.

## Para cada opción, lo mismo

- Qué resuelve bien y qué resuelve mal. "Mal" siempre existe.
- **Coste de cambio**: qué pasa si en seis meses hay que cambiar esta pieza.
  Una opción cara de mover solo es aceptable si se dice.
- Qué se descarta y **por qué**. Descartar sin motivo es no mirar.

## El invariante de este sistema

Aegis es una consola de operación, **nunca la autoridad**. Los datos viven en el
Worker/Postgres del proyecto que se opera; esta máquina es una ventana, y si se
apaga el negocio sigue. Cualquier arquitectura que ponga el estado en la máquina
del supervisor está descartada antes de discutirla.

## Lo que NO se decide aquí

Nombres de campos, esquema de tablas, rutas de API, nombres de ficheros,
orden de los commits. Eso sale de la arquitectura, no la precede.

## Cómo sales

Un texto con las tres partes: **requisitos no funcionales**, **opciones con su
coste de cambio**, **recomendación con su motivo**. La recomendación es de una,
y si hay empate real lo dices así de claro: un empate es una decisión que te
pertenece a ti.

Y al final, **qué habría que falsar para estar equivocado**: la prueba barata que, si falla, descarta tu recomendación. Sin eso es una opinión con
párrafos.