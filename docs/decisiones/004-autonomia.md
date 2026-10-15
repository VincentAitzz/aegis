# 004 — Autonomía sobre el método, y que te enteres de lo que importa

> 2026-10-14. Convierte cuatro peticiones —«máxima autonomía», «replanifica solo y
> me informas», «cayo en mí revisar lo que hizo en mi ausencia», y una definición
> de qué es irreversible— en cinco piezas con sus números.

## El problema

Aegis tenía una puerta, una traza y un veredicto. Le faltaba lo que hace que un
asistente pueda trabajar solo:

| le faltaba | consecuencia |
|---|---|
| un objeto «lo que estoy trabajando» | no había forma de decir «encaja este plan con el actual» |
| un informe de cierre | había que ir a `GET /runs/{id}` a buscar qué pasó |
| «continuar» como instrucción | el 19 % de los prompts reales no llegaba a ningún sitio |
| memoria entre reinicios | los runs viven en `_AUTOPILOT_RUNS`, un dict en memoria |

El último es el que hace inviable todo lo demás: **autonomía con estado efímero
es trabajo perdido**, y si vas a revisar lo que hizo en tu ausencia, lo primero
que tiene que aguantar es que se caiga a mitad.

## La línea de lo irreversible, escrita el 2026-10-14

> lo irreversible es en cuanto a pagos, despliegues, migraciones, contactar
> clientes esencialmente

Traducida a código en `app/autonomy.py::IRREVERSIBLES`. Lo que separa una cosa de
otra no es lo difícil que sea, ni lo caro, ni lo lejano: es **si alguien se
entera fuera de esta máquina cuando pase**. Un fichero que se reescribe lo notas
tú; una factura que sale la nota tu banco.

| categoría | tools | ¿existe alguna? |
|---|---|---|
| `pago` | — | **ninguna**. Aegis no puede pagar |
| `despliegue` | `build_apk`, `install_apk`, `deploy_smoke`, `adb_connect` | sí |
| `migracion` | `db_migrate`, `neon_branch` | sí |
| `contacto` | — | **ninguna**. Aegis no puede escribir a nadie |

**Dos de las cuatro están vacías, y eso es una propiedad que hay que mantener, no
un hueco que rellenar.** El día que alguien añada `enviar_correo`, un test falla y
obliga a decidir. Por eso existen.

### Lo que se dejó en la cola y no es de las cuatro categorías

`project_create` y `quien_eres_actualiza` siguen pidiendo, y ninguna es de las
cuatro. Se dice en voz alta y no escondido:

- `project_create` escribe fuera de los proyectos declarados.
- `quien_eres_actualiza` reescribe lo que Aegis sabe de ti, y ese fichero entra
  en el prompt de **todos** los runs. Quitarle la puerta haría que Aegis pudiera
  reescribir sus propias instrucciones sin que nadie se entere.

Si alguien quiere el modelo literal —solo las cuatro categorías—, la que hay que
debatir primero es la segunda, y con nombre.

### Lo que no cambió

`docs/vision.md` §6: «pagos automáticos: nunca, sin excepción ni con permiso de
antemano». Y `nivel_de()` sigue cayendo en `requiere_ok` para **todo lo que no
conoce**. Esa es la propiedad que hace segura la autonomía: el caso
desconocido pregunta. Invertirla sería «máxima autonomía» y sería también la
forma de que la autonomía dependiera de que nadie añadiera una tool nueva.

## Qué se construyó

### `app/plan.py` — el objeto que no existía

Un plan con objetivo, proyecto, **prioridad**, criterios de aceptación, estado
(`en_cola` · `en_curso` · `reformulado` · `bloqueado` · `cerrado`), run
asociado, motivo de reformulación y enlace al cierre.

Tres reglas que hacen que signifique algo:

1. **Solo uno en curso.** No es una comodidad: es lo que permite que «esto se
   replanifica» tenga un sujeto. Con dos habría que elegir, y esa elección no
   tiene criterio.
2. **Prioridad estrictamente mayor desplaza.** Con `>=`, cualquier plan nuevo
   sacaría al que está trabajando y Aegis no terminaría nada: siempre
   empezando. El 50 por defecto es neutro a propósito.
3. **`cerrar` exige el cierre.** Sin él, `cerrado` sería la palabra del modelo
   diciendo que acabó — el falso éxito de A-016 con otro nombre.

Y una que se salió de la intención y que salió bien: **el plan desplazado vuelve
a la cola con su prioridad, no se pierde**. Abandonar no es cancelar, y la
diferencia se ve después en el informe.

### `app/cierre.py` — los cinco apartados

`RESULTADOS` · `CAMBIOS DRÁSTICOS` · `ERRORES` · `DECISIONES` ·
`RECOMENDACIONES`. Cada uno sale de la traza, y el módulo lo enseña en `sostiene`
para que el informe sea **auditable** y no haya que creerle.

**Las recomendaciones no las escribe el modelo**, y es la decisión de diseño de
este documento. Es el único apartado donde podría hacerlo sin que nadie se
enterara: los otros cuatro describen hechos, y una opinión generada suena igual
de profesional que un dato. Salen de cinco reglas que están a la vista, y como
mucho tres por run. Una recomendación que siempre sale es un aviso, y un aviso
que siempre sale es ruido.

**El filtro de vitalidad**: cuando Aegis trabaja en tu ausencia no te interrumpe.
El cierre se escribe siempre y se consulta cuando quieras, y un run donde no hubo
errores, ni reformulación, ni decisiones, **no produce nada que leer**.

### `app/intents.py::procede` — el 19 % que no llegaba a ningún sitio

Medido sobre 500 prompts reales del usuario:

| patrón | % |
|---|---|
| continuar — `procede`, `continua`, `dale` | **19 %** |
| corregir | 12 % |
| aprobar | 6 % |

Y antes de este trabajo, en la máquina:

```
'procede'   -> (no casa con ningún intent)
'continua'  -> (no casa con ningún intent)
```

Caían a T1 —el modelo sin herramientas— y el modelo no tenía con qué continuar.

La parte que no es trivial: **de 88 «procede» reales, 44 llevan requisitos
pegados** («Procede, los sin número también inclúyelos pero haz la separación»).
Eso no es continuar, es cambiar los requisitos de lo que ya se estaba haciendo.
El intent separa los dos casos, y en el segundo **reformula el plan en curso por
su cuenta** y escribe el motivo —que es lo que hace que se pueda auditar después.

## Lo medido

`bridge/bin/medir-cobertura` lee las sesiones reales y mide el reparto entre «lo
entiende sin modelo» y «se lo pasa al modelo»:

```
prompts reales: 216   (sesiones de aegis)
  los entiende sin modelo: 60 (27 %)
  se los pasa al modelo:   156 (72 %)
```

**Antes eran 0.** Los 216 son solo de `aegis`: los otros cinco proyectos de las
sesiones no están en `PROJECTS` y Aegis no opera ninguno, así que no se abren.

Del total de 545 (500 reales tras descartar 45 del arnés) el 27 % es solo de
aegis, porque las sesiones de este repo son más de metacomandos —«Comitea»,
«aplicálo»— que de conversación.

### Tres falsos positivos que encontró la medición

Los 40 «procede» con requisitos incluyó tres que no lo eran:

```
'Procede tal cual como dices'      -> resto: «tal cual como dices»
'Dale procede asi entonces'        -> resto: «procede asi entonces»
'Procede nomas rey'                -> resto: «nomas rey»
```

Son **énfasis**, no requisitos. Sin corregirlos, Aegis reformula el plan con un
requisito que dice «tal cual», y eso va a aparecer en el informe como si hubiera
sido una decisión. Se corrigieron con una lista de énfasis en `_RELLENO` y
quitando un verbo repetido.

**Es el mismo modo de fallo de A-124**: un detector que casa con más de lo que
debe no es una ayuda, es ruido con forma de ayuda.

## Lo que NO se hace aquí

- **No se quita la cola.** Ni un modo que la dispense (A-036). JARVIS no es «sin
  cola», es **cola solo para consecuencias**.
- **No se toca `docs/vision.md` §4.** La invariante sobrevive; lo que cambia es
  qué entra en la cola.
- **No se abren las sesiones de los otros proyectos.**
- **No se Avisa durante el run.** Las interrupciones se deciden aparte.

## Lo que falta, y es lo importante

**El trabajo en vuelo sigue sin sobrevivir a un reinicio.** `_AUTOPILOT_RUNS` es
un dict en memoria, sin carga al arrancar. El plan persiste; el **run** no. Con
`aegis-bridge.service` en `Restart=always`, un reinicio borra el trabajo en
marcha aunque el plan siga en la cola.

Es la pieza que hace falta para «revisar lo que hizo en mi ausencia» y es la
siguiente, no la última: hasta que el run sobreviva, un plan que se retoma
empieza de cero.