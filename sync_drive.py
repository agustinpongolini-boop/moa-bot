"""
Trae el calendario desde una carpeta de Google Drive.

POR QUÉ EXISTE
El calendario vivía solo en el repo, y el único paso humano del sistema era
el push: sin la compu de Agustín y su click en "Commit changes", no entraba
el lote y el bot corría en vacío (14-15/09, 17/09, 30/09-03/10).

Ahora Claude deja cada lote como un CSV nuevo en la carpeta de Drive
"moa-bot · calendario" (el conector de Drive puede crear archivos sin pasar
por la compu de nadie) y el bot los lee de ahí.

CÓMO FUNCIONA
- Lista los .csv de la carpeta (GDRIVE_FOLDER_ID) con una cuenta de servicio
  de Google (GDRIVE_SA_JSON, la clave JSON entera como Secret).
- Junta todas las filas. Si dos archivos traen el mismo post (misma
  fecha+hora), gana el archivo más nuevo: así se corrige un precio subiendo
  un CSV nuevo, sin tocar el viejo.
- Escribe datos/calendario_drive.csv. Ese archivo NO se commitea: es un
  derivado. Si se commiteara, chocaría con el `git pull --rebase` del estado.
- Corre como mucho una vez cada SYNC_CADA_MIN minutos: el turno vive 5,5 h y
  un lote cargado a mitad de turno tiene que entrar sin esperar al próximo.

REGLA DE ORO: si Drive falla, NO se cae nada. Se loguea y el bot sigue con lo
que ya tenía (el último calendario_drive.csv bajado + datos/calendario.csv).
Un bot que publica con el calendario de hace media hora es mejor que uno que
se cae porque Google tardó.
"""

import csv
import io
import json
import os
import time

DESTINO = "datos/calendario_drive.csv"
SYNC_CADA_MIN = 20
DIAS_ATRAS = 21  # archivos más viejos que esto no se leen: ya no tienen nada vigente

_ultimo_sync = 0.0


def _log(msg):
    print(f"[drive] {msg}", flush=True)


def _sesion():
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession

    info = json.loads(os.environ["GDRIVE_SA_JSON"])
    cred = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return AuthorizedSession(cred)


def _listar(s, carpeta):
    desde = time.strftime(
        "%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - DIAS_ATRAS * 86400)
    )
    q = (
        f"'{carpeta}' in parents and trashed = false "
        f"and modifiedTime > '{desde}' "
        f"and (mimeType = 'text/csv' or name contains '.csv')"
    )
    archivos, token = [], None
    while True:
        params = {
            "q": q,
            "fields": "nextPageToken, files(id, name, modifiedTime)",
            "pageSize": 100,
            "orderBy": "modifiedTime",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if token:
            params["pageToken"] = token
        r = s.get("https://www.googleapis.com/drive/v3/files", params=params, timeout=30)
        r.raise_for_status()
        j = r.json()
        archivos += j.get("files", [])
        token = j.get("nextPageToken")
        if not token:
            return archivos


def _bajar(s, fid):
    r = s.get(
        f"https://www.googleapis.com/drive/v3/files/{fid}",
        params={"alt": "media", "supportsAllDrives": "true"},
        timeout=30,
    )
    r.raise_for_status()
    return r.content.decode("utf-8-sig")


def _textos(carpeta):
    """Contenido de cada CSV de la carpeta, del más viejo al más nuevo.

    Dos caminos, según qué traiga el Secret GDRIVE_SA_JSON:
    - {"url": ..., "token": ...} -> Apps Script publicado como app web, que
      corre como Agustín y lee la carpeta. Es el camino en uso: la
      organización de Google Cloud bloquea crear claves de cuenta de servicio
      (iam.disableServiceAccountKeyCreation, visto el 03/10/2026).
    - la clave JSON de una cuenta de servicio -> Drive API directa.
    """
    info = json.loads(os.environ["GDRIVE_SA_JSON"])
    if "url" in info:
        import requests

        r = requests.get(info["url"], params={"t": info["token"]}, timeout=90)
        r.raise_for_status()
        j = r.json()
        if "files" not in j:
            raise RuntimeError(f"respuesta inesperada del Apps Script: {str(j)[:200]}")
        return [f["content"] for f in sorted(j["files"], key=lambda f: f["modified"])]

    s = _sesion()
    return [_bajar(s, a["id"]) for a in _listar(s, carpeta)]


def sincronizar(forzar=False):
    """Devuelve True si quedó un calendario_drive.csv usable (nuevo o viejo)."""
    global _ultimo_sync
    carpeta = os.environ.get("GDRIVE_FOLDER_ID", "").strip()
    if not carpeta or not os.environ.get("GDRIVE_SA_JSON", "").strip():
        return os.path.exists(DESTINO)  # sin configurar: modo viejo, solo el repo

    if not forzar and time.time() - _ultimo_sync < SYNC_CADA_MIN * 60:
        return os.path.exists(DESTINO)
    _ultimo_sync = time.time()

    try:
        textos = _textos(carpeta)  # ordenados del más viejo al más nuevo
        archivos = textos
        filas, columnas = {}, None
        for texto in textos:
            texto = texto.lstrip("﻿")
            lector = csv.DictReader(io.StringIO(texto))
            if columnas is None:
                columnas = lector.fieldnames
            for fila in lector:
                if not fila.get("fecha") or not fila.get("hora"):
                    continue
                filas[f"{fila['fecha']}T{fila['hora']}"] = fila  # el más nuevo pisa
        if columnas is None:
            _log(f"carpeta sin CSV en los últimos {DIAS_ATRAS} días")
            return os.path.exists(DESTINO)

        os.makedirs(os.path.dirname(DESTINO), exist_ok=True)
        tmp = DESTINO + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
            w.writeheader()
            for k in sorted(filas):
                w.writerow(filas[k])
        os.replace(tmp, DESTINO)
        _log(f"{len(archivos)} archivo(s), {len(filas)} post(s) -> {DESTINO}")
        return True
    except Exception as e:  # nunca tumbar el turno por Drive
        _log(f"ERROR leyendo Drive, sigo con lo que había: {e!r}")
        return os.path.exists(DESTINO)
