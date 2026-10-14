---
kind: perfil
---

# Quién eres

> Este fichero es lo que Aegis sabe de ti, y lo que **no** tiene que preguntarte
> otra vez.
>
> **No viene en el repo.** Es tuyo: Aegis no lo escribe solo, y lo que hay aquí
> es la plantilla. `infra/setup.sh` copia este fichero a `quien-eres.md` en el
> primer arranque, y `quien-eres.md` está en `.gitignore` para que no acabe en
> un `git push` por accidente. Si no existe, Aegis no se rompe: sigue con el
> resto del prompt (`metodo.md`, las lecciones, el índice del registro).
>
> Se lee en dos partes. La sección **«Cómo hablo contigo»** entra en todos los
> runs y está limitada a 600 caracteres: si crece, se recorta y se avisa. El resto
> del fichero **no se inyecta nunca** — se lee con `aegis_read_file` cuando un
> encargo lo necesita. Es el mismo trato que las lecciones: el prompt es el
> presupuesto, y un bloque grande es un coste que se multiplica por cada paso.

## Cómo hablo contigo

<!-- Esta sección entra en TODOS los runs, y está limitada a 600 caracteres.
     Pon aquí lo que pesa: cómo quieres que te hablen y qué no quieres que Aegis
     decida. Todo lo demás vive más abajo, en secciones que Aegis lee cuando las
     necesita. -->

Háblame en español. Eres quien decide; Aegis ejecuta.

Lo que no está aquí está en `quien-eres.md`: léelo con `aegis_read_file` cuando
el encargo lo necesite. No hace falta en cada run, y por eso no entra.

<!-- El resto son secciones `## ` normales. Ejemplos de lo que suele ir aquí,
     y que Aegis NO inyecta salvo que el encargo lo pida:

## Cómo trabajo

Prefiero commits pequeños y un mensaje que explique el porqué. Si un cambio
toca más de tres ficheros, avisa antes.

## Qué no hagas

- No subas a `main` sin que lo pida.
- No ejecutes nada que tenga precio sin decírmelo antes.

-->
