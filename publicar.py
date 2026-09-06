#!/usr/bin/env python3
"""
publicar.py — Publica el próximo post pendiente en X.

Lo corre el cron de GitHub Actions. No requiere que nadie esté mirando.

    python3 publicar.py              # modo prueba: arma todo, NO publica
    DRY_RUN=false python3 publicar.py  # publica de verdad

QUÉ HACE, EN ORDEN
  1. Lee datos/calendario.csv y busca el próximo post cuya hora ya pasó.
  2. Chequea contra datos/estado.json que no se haya publicado antes.
  3. Compone la imagen del producto (imagen del CDN + datos).
  4. Sube la imagen a X y publica el texto.
  5. Anota el resultado en estado.json.

POR QUÉ NO PUBLICA DOS VECES
  estado.json guarda el id de cada post ya publicado. El workflow hace commit
  de ese archivo al repo después de cada corrida, así el estado sobrevive
  aunque la máquina que corre sea distinta cada vez.

VARIABLES DE ENTORNO (secretos del repo)
  X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
  DRY_RUN=false para publicar de verdad (por defecto no publica)
  MAX_POR_CORRIDA  tope de posts por corrida (default 2, para recuperar atraso)
  ESPERA_ENTRE     segundos entre el primero y el segundo (default 180)
"""

import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

CALENDARIO = "datos/calendario.csv"
ESTADO = "datos/estado.json"
SALIDA = "salida"
TZ = timezone(timedelta(hours=-3))          # Argentina
VENTANA_MIN = int(os.environ.get("VENTANA_MIN", "30"))
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() != "false"

# CUANTOS POSTS PUEDE SACAR UNA CORRIDA
#
# Antes era uno fijo, y eso perdia un post por dia cada vez que el cron de
# GitHub no disparaba. Verificado por simulacion el 06/09/2026: si falla la
# corrida de las 12:40, la de las 15:20 publica el de las 12:40, la de las
# 18:10 publica el de las 15:20, y asi hasta que el post de las 23:15 queda
# pendiente. Al dia siguiente cae fuera de la ventana del dia y se descarta
# en silencio. Justo el de las 23:15 es el que suele llevar el cupon que
# vence esa noche.
#
# Con dos por corrida, una corrida perdida se recupera en la siguiente y el
# dia cierra completo. El segundo sale despues de una pausa para que no
# parezca un bot vaciando la cola.
MAX_POR_CORRIDA = int(os.environ.get("MAX_POR_CORRIDA", "2"))
ESPERA_ENTRE = int(os.environ.get("ESPERA_ENTRE", "180"))


_resumen = []


def log(msg):
    linea = f"[{datetime.now(TZ):%Y-%m-%d %H:%M:%S}] {msg}"
    print(linea, flush=True)
    _resumen.append(linea)


def volcar_resumen():
    """Deja el resultado en la pantalla de Summary de la corrida.

    Sin esto hay que abrir la corrida, entrar al job y expandir el paso para
    enterarse de que algo salio mal.
    """
    ruta = os.environ.get("GITHUB_STEP_SUMMARY")
    if not ruta:
        return
    try:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write("## Publicacion\n\n```\n" + "\n".join(_resumen) + "\n```\n")
    except Exception:
        pass


def cupon_vencido(fila, ahora):
    """El post lleva un cupon que ya expiro?

    Los cupones de Mercado Libre mueren a las 23:59 del dia que se anuncian.
    Un post de las 23:15 con un cupon muerto es peor que no publicar: la gente
    hace click, no puede aplicarlo, y la cuenta pierde credibilidad.

    Si `cupon_vence` esta vacio no bloquea nada. Si esta pero no se entiende,
    SI bloquea: ante la duda no se promete un descuento que no podemos validar.
    """
    v = (fila.get("cupon_vence") or "").strip()
    if not v:
        return False
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            t = datetime.strptime(v, fmt).replace(tzinfo=TZ)
            if fmt == "%Y-%m-%d":
                t = t.replace(hour=23, minute=59)
            return ahora > t
        except ValueError:
            continue
    log(f"no pude interpretar cupon_vence='{v}' - salteado por las dudas")
    return True


def cargar_estado():
    if os.path.exists(ESTADO):
        with open(ESTADO, encoding="utf-8") as f:
            return json.load(f)
    return {"publicados": [], "errores": []}


def guardar_estado(e):
    os.makedirs(os.path.dirname(ESTADO), exist_ok=True)
    with open(ESTADO, "w", encoding="utf-8") as f:
        json.dump(e, f, indent=1, ensure_ascii=False)


def id_post(fila):
    return f"{fila['fecha']}T{fila['hora']}"


def ya_procesado(estado, pid):
    """Publicado o descartado: en cualquiera de los dos casos no se reintenta."""
    return pid in estado["publicados"] or pid in estado.get("saltados", [])


def proximo_pendiente(estado):
    """El post más viejo que ya debería haber salido y todavía no salió.

    REGLA: se publica cualquier post PENDIENTE DE HOY cuya hora ya pasó.
    No se publica nada de días anteriores.

    Antes esto usaba una ventana de 90 minutos y fue un error: el 05/09/2026
    el cron disparó con MÁS DE DOS HORAS de atraso —el triple de lo que
    documenta GitHub— y descartó un post que estaba perfecto. Una oferta
    publicada dos horas tarde sigue sirviendo; una de ayer no. El día es el
    límite natural, y no depende de la puntualidad de GitHub.
    """
    ahora = datetime.now(TZ)
    limite = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    with open(CALENDARIO, encoding="utf-8") as f:
        filas = list(csv.DictReader(f))

    candidatos = []
    for fila in filas:
        if ya_procesado(estado, id_post(fila)):
            continue
        try:
            cuando = datetime.strptime(f"{fila['fecha']} {fila['hora']}",
                                       "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
        except ValueError:
            continue
        if limite <= cuando <= ahora:
            if cupon_vencido(fila, ahora):
                log(f"cupon vencido, se saltea: {id_post(fila)} - {fila.get('cupon_codigo','')}")
                estado.setdefault("saltados", []).append(id_post(fila))
                estado.setdefault("cupon_vencido", []).append(id_post(fila))
                continue
            candidatos.append((cuando, fila))
        elif cuando < limite:
            # es de un día anterior: se descarta, NO se publica una oferta vieja
            estado.setdefault("saltados", []).append(id_post(fila))
            estado.setdefault("vencidos", []).append(id_post(fila))
    candidatos.sort(key=lambda c: c[0])
    return candidatos[0][1] if candidatos else None


def armar_imagen(fila):
    if not fila.get("imagen_url"):
        return None
    from componer_ficha import componer
    os.makedirs(SALIDA, exist_ok=True)
    destino = os.path.join(SALIDA, f"{id_post(fila).replace(':', '')}.png")
    datos = {
        "titulo": fila.get("titulo", ""),
        "precio": fila.get("precio"),
        "precio_lista": fila.get("precio_lista"),
        "off": fila.get("off", ""),
        "cuotas": fila.get("cuotas", ""),
        "cuotas_sin_interes": str(fila.get("cuotas_sin_interes", "")).lower() in ("si", "sí", "true", "1"),
        "cupon": fila.get("cupon", ""),
        "cupon_codigo": fila.get("cupon_codigo", ""),
        "envio_gratis": str(fila.get("envio_gratis", "")).lower() in ("si", "sí", "true", "1"),
        "rank": fila.get("rank", ""),
        "rank_categoria": fila.get("rank_categoria", ""),
        "unidades_vendidas": fila.get("unidades_vendidas", 0),
        "imagen": fila["imagen_url"],
    }
    return componer(datos, destino)



def publicar_en_x(texto, imagen=None, respuesta_a=None):
    """Sube la imagen y postea. Requiere las 4 claves de X."""
    from requests_oauthlib import OAuth1Session

    faltan = [k for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")
              if not os.environ.get(k)]
    if faltan:
        raise RuntimeError(f"faltan secretos: {', '.join(faltan)}")

    x = OAuth1Session(os.environ["X_API_KEY"], os.environ["X_API_SECRET"],
                      os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_SECRET"])

    media_ids = []
    if imagen:
        # ENDPOINT v1.1 A PROPOSITO. El 06/09/2026 crei que estaba retirado
        # porque dos posts parecian haber salido sin foto, y lo reemplace por
        # v2. Era un error de MEDICION: X carga las imagenes en diferido y yo
        # las consultaba demasiado pronto. Los dos posts tenian su foto.
        # No se cambia un componente que anda por uno sin probar.
        with open(imagen, "rb") as f:
            r = x.post("https://upload.twitter.com/1.1/media/upload.json",
                       files={"media": f}, timeout=90)
        r.raise_for_status()
        mid = r.json().get("media_id_string") or r.json().get("media_id")
        if not mid:
            raise RuntimeError(f"la subida no devolvio media_id: {r.text[:200]}")
        log(f"imagen subida: {mid}")
        media_ids.append(str(mid))

    cuerpo = {"text": texto}
    if media_ids:
        cuerpo["media"] = {"media_ids": media_ids}
    if respuesta_a:
        cuerpo["reply"] = {"in_reply_to_tweet_id": respuesta_a}

    r = x.post("https://api.twitter.com/2/tweets", json=cuerpo, timeout=60)
    r.raise_for_status()
    return r.json()["data"]["id"]


def publicar_uno(fila, estado):
    """Publica una fila. Devuelve 0 si salio bien, 1 si no."""
    pid = id_post(fila)
    log(f"post pendiente: {pid} · {fila.get('titulo', '')[:45]}")

    # La foto es requisito del negocio: un post de producto sin imagen rinde
    # mucho menos y ya se pago igual. Si la fila pide foto y no se puede
    # armar, se aborta el post en vez de publicarlo pelado.
    try:
        imagen = armar_imagen(fila)
        log(f"imagen: {imagen or 'sin imagen'}")
    except Exception as e:
        log(f"ERROR armando la imagen: {e}")
        imagen = None
    if fila.get("imagen_url") and not imagen:
        log("el post pide foto y no se pudo armar - NO se publica")
        estado["errores"].append({"post": pid, "error": "no se pudo armar la imagen",
                                  "cuando": datetime.now(TZ).isoformat()})
        guardar_estado(estado)
        return 1

    texto = fila["texto"].replace("\\n", "\n")

    if DRY_RUN:
        os.makedirs(SALIDA, exist_ok=True)
        with open(os.path.join(SALIDA, f"{pid.replace(':', '')}.txt"), "w",
                  encoding="utf-8") as f:
            f.write(texto)
        log("MODO PRUEBA — no se publicó. Texto:")
        print("-" * 50)
        print(texto)
        print("-" * 50)
        log(f"({len(texto)} caracteres)")
        return 0

    try:
        tid = publicar_en_x(texto, imagen)
        log(f"publicado: https://x.com/i/status/{tid}")
        if fila.get("respuesta"):
            rid = publicar_en_x(fila["respuesta"].replace("\\n", "\n"), respuesta_a=tid)
            log(f"respuesta encadenada: {rid}")
        estado["publicados"].append(pid)
    except Exception as e:
        log(f"ERROR publicando: {e}")
        estado["errores"].append({"post": pid, "error": str(e)[:200],
                                  "cuando": datetime.now(TZ).isoformat()})
        guardar_estado(estado)
        return 1

    guardar_estado(estado)
    return 0


def main():
    if not os.path.exists(CALENDARIO):
        log(f"no existe {CALENDARIO} — nada que hacer")
        return 0

    estado = cargar_estado()
    salidos = 0

    for intento in range(MAX_POR_CORRIDA):
        fila = proximo_pendiente(estado)
        if not fila:
            if salidos == 0:
                log("sin posts pendientes de hoy")
                guardar_estado(estado)
            break

        if intento > 0:
            # Recuperando una corrida perdida. La pausa evita que los dos
            # posts salgan con segundos de diferencia.
            log(f"vengo atrasado: hay otro pendiente, espero {ESPERA_ENTRE}s")
            if not DRY_RUN:
                time.sleep(ESPERA_ENTRE)

        codigo = publicar_uno(fila, estado)
        if codigo != 0:
            return codigo
        salidos += 1

        if DRY_RUN:
            # En modo prueba no se toca estado.json, asi que el siguiente
            # pendiente seria el mismo y quedaria en bucle.
            break

    if salidos > 1:
        log(f"{salidos} posts en esta corrida (recuperando atraso)")
    return 0


if __name__ == "__main__":
    codigo = main()
    volcar_resumen()
    sys.exit(codigo)
