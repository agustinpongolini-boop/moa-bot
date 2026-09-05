# moa-bot — publicación automática en X

Publica en X sin que nadie esté mirando. El cron de GitHub lo despierta, arma la
imagen del producto, publica y anota qué salió.

**Probado el 05/09/2026**: encuentra el post pendiente, compone la ficha (189 KB, imagen real
bajada del CDN de Mercado Libre), escribe el texto, no repite un post ya publicado.

---

## Cómo está partido el trabajo

| Cuándo | Dónde | Quién | Qué |
|---|---|---|---|
| **Semanal** (30-45 min) | tu navegador | vos + Claude | Ranking → filtro → Barra de Afiliados → links, IDs, datos, URLs de imagen → `datos/calendario.csv` |
| **Diario** (segundos) | GitHub | nadie | Cron → arma la ficha → publica en X → guarda el estado |

La parte de Mercado Libre **no se puede automatizar**: necesita tu sesión con la Barra activa, y
hacerlo headless es lo que los T&C sancionan. La parte de publicar sí, y es la que consume tiempo
todos los días.

---

## Puesta en marcha

1. **Crear el repo en GitHub** (privado) y subir estos archivos.

2. **Correrlo en modo prueba.** Andá a *Actions → Publicar en X → Run workflow*, dejá
   `publicar_de_verdad` en `false`. Arma el post y la imagen sin publicar nada. La salida queda en
   *Artifacts*, para que la descargues y la mires.

3. **Cargar los secretos** en *Settings → Secrets and variables → Actions*:
   `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET`.
   Se ponen una vez y nunca más se ven. No van en el código.

4. **Primera publicación real:** *Run workflow* con `publicar_de_verdad` en `true`.
   Un post. Mirá que salga bien en X antes de dejar el cron suelto.

5. **Listo.** El cron ya está configurado para 09:10, 13:20, 18:40 y 21:15 hora argentina.

---

## Usar tu computadora en vez de la de GitHub

En `.github/workflows/publicar.yml`, cambiá una línea:

```yaml
runs-on: ubuntu-latest      →      runs-on: self-hosted
```

Después instalás el runner de GitHub en tu máquina (*Settings → Actions → Runners → New runner*,
son tres comandos que la propia página te da).

**Cuándo conviene:** solo si es una máquina de escritorio que queda prendida siempre.
**Cuándo no:** si es una notebook. El post de las 21:15 sale si la máquina está prendida a las
21:15 — con la tapa cerrada no sale, y no te enterás hasta el otro día.

Ventaja del runner propio: puntual al segundo y sin límite de minutos.
Ventaja de GitHub: no dependés de nada tuyo.

---

## Los archivos

```
publicar.py                      el que hace todo
componer_ficha.py                arma la imagen del producto
datos/calendario.csv             la cola de posts (lo genera el lote semanal)
datos/estado.json                qué se publicó ya — no lo edites a mano
.github/workflows/publicar.yml   el cron
salida/                          lo que produjo la última corrida
```

### Columnas del calendario

`fecha`, `hora`, `texto`, `respuesta`, `titulo`, `precio`, `precio_lista`, `off`, `cuotas`,
`cuotas_sin_interes`, `cupon`, `envio_gratis`, `rank`, `rank_categoria`, `unidades_vendidas`,
`imagen_url`

Los saltos de línea del texto van como `\n`. Si `imagen_url` está vacío, el post sale sin imagen
(así salen los orgánicos).

---

## Detalles que evitan problemas

**No publica dos veces.** `estado.json` guarda el id de cada post publicado, y el workflow lo
commitea de vuelta al repo. Aunque la máquina que corre sea distinta cada vez, el estado persiste.

**No publica un post viejo.** Si el cron falló y pasaron más de 30 minutos, el post se marca como
vencido y se saltea. Mejor no publicar que publicar una oferta de ayer con precio de ayer.

**Si algo falla, queda anotado** en `estado.json` y GitHub te manda un mail.

**Los secretos nunca están en el código.** Van en el gestor de GitHub, cifrados. Ni siquiera se
pueden volver a leer desde la interfaz.

---

## Costo

| | |
|---|---|
| GitHub Actions | **$0** — 270 min/mes contra 2.000 del plan gratuito *(confirmar límites vigentes)* |
| X API — posts con link | ~USD 54/mes a 9 posts/día |
| X API — posts con ID de producto, sin link | **~USD 4/mes** |

La diferencia depende de un test pendiente: **si el ID de producto atribuye la comisión.**
Generá el ID del mismo producto bajo dos etiquetas distintas — si el código cambia, atribuye.
