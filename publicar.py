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
  VENTANA_MIN  cuántos minutos de atraso se toleran (default 30)
"""

import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

CALENDARIO = "datos/calendario.csv"
ESTADO = "datos/estado.json"
SALIDA = "salida"
TZ = timezone(timedelta(hours=-3))          # Argentina
VENTANA_MIN = int(os.environ.get("VENTANA_MIN", "30"))
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() != "false"


def log(msg):
    print(f"[{datetime.now(TZ):%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


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


def proximo_pendiente(estado):
    """El post más viejo que ya debería haber salido y todavía no salió."""
    ahora = datetime.now(TZ)
    limite = ahora - timedelta(minutes=VENTANA_MIN)
    with open(CALENDARIO, encoding="utf-8") as f:
        filas = list(csv.DictReader(f))

    candidatos = []
    for fila in filas:
        if id_post(fila) in estado["publicados"]:
            continue
        try:
            cuando = datetime.strptime(f"{fila['fecha']} {fila['hora']}",
                                       "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
        except ValueError:
            continue
        if limite <= cuando <= ahora:
            candidatos.append((cuando, fila))
        elif cuando < limite:
            # se pasó la ventana: lo marcamos como vencido y seguimos
            estado["publicados"].append(id_post(fila))
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
        with open(imagen, "rb") as f:
            r = x.post("https://upload.twitter.com/1.1/media/upload.json",
                       files={"media": f}, timeout=60)
        r.raise_for_status()
        media_ids.append(str(r.json()["media_id"]))

    cuerpo = {"text": texto}
    if media_ids:
        cuerpo["media"] = {"media_ids": media_ids}
    if respuesta_a:
        cuerpo["reply"] = {"in_reply_to_tweet_id": respuesta_a}

    r = x.post("https://api.twitter.com/2/tweets", json=cuerpo, timeout=60)
    r.raise_for_status()
    return r.json()["data"]["id"]


def main():
    if not os.path.exists(CALENDARIO):
        log(f"no existe {CALENDARIO} — nada que hacer")
        return 0

    estado = cargar_estado()
    fila = proximo_pendiente(estado)

    if not fila:
        log("sin posts pendientes en la ventana")
        guardar_estado(estado)
        return 0

    pid = id_post(fila)
    log(f"post pendiente: {pid} · {fila.get('titulo', '')[:45]}")

    try:
        imagen = armar_imagen(fila)
        log(f"imagen: {imagen or 'sin imagen'}")
    except Exception as e:
        log(f"ERROR armando la imagen: {e}")
        imagen = None

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


if __name__ == "__main__":
    sys.exit(main())
