#!/usr/bin/env python3
"""
verificar_claves.py — Confirma que las 4 claves de X funcionan, sin publicar.

    python3 verificar_claves.py

POR QUÉ EXISTE
    El modo prueba de publicar.py nunca llama a X, así que no sirve para saber
    si las claves están bien. Y la alternativa —publicar de verdad— cuesta
    USD 0,20 y ensucia el timeline si algo está mal.

    Esto hace una sola lectura (GET /2/users/me, USD 0,010) y responde tres
    preguntas de una: si las 4 claves están cargadas, si la firma OAuth 1.0a
    es válida, y a qué cuenta pertenecen.

QUÉ NO PRUEBA
    El permiso de escritura. X no lo devuelve en v2. Se intenta leer la
    cabecera x-access-level de la API v1.1, que sí lo dice, pero puede no
    estar disponible. La confirmación definitiva de escritura es el primer
    post real.
"""

import os
import sys

CLAVES = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")

_resumen = []


def di(msg=""):
    """Imprime en el log Y en el resumen de la corrida.

    Sin esto el resultado queda enterrado dentro de un paso colapsado del log,
    a tres clicks. GITHUB_STEP_SUMMARY lo pone en la pantalla de Summary,
    que es la primera que se ve al abrir la corrida.
    """
    print(msg, flush=True)
    _resumen.append(msg)


def volcar_resumen():
    ruta = os.environ.get("GITHUB_STEP_SUMMARY")
    if not ruta:
        return
    try:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write("## Verificación de claves de X\n\n```\n")
            f.write("\n".join(_resumen))
            f.write("\n```\n")
    except Exception:
        pass


def main():
    faltan = [k for k in CLAVES if not os.environ.get(k)]
    if faltan:
        di("FALTAN SECRETOS EN GITHUB:")
        for k in faltan:
            di(f"  · {k}")
        di("\nSettings → Secrets and variables → Actions → New repository secret")
        di("El nombre tiene que coincidir exactamente, en mayúsculas.")
        return 1

    # Aviso temprano de un error clásico: pegar el valor con espacios o comillas.
    for k in CLAVES:
        v = os.environ[k]
        if v != v.strip():
            di(f"OJO: {k} tiene espacios al principio o al final. Recargalo sin espacios.")
            return 1
        if v[0] in "\"'" or v[-1] in "\"'":
            di(f"OJO: {k} quedó con comillas. Se pega el valor pelado, sin comillas.")
            return 1

    from requests_oauthlib import OAuth1Session

    x = OAuth1Session(os.environ["X_API_KEY"], os.environ["X_API_SECRET"],
                      os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_SECRET"])

    r = x.get("https://api.x.com/2/users/me", timeout=30)

    if r.status_code == 401:
        di("401 — las claves no son válidas.")
        di("Causa más común: se regeneró la Consumer Key después del Access Token,")
        di("lo que invalida el token. Regenerá primero Consumer Key, después Access Token.")
        return 1
    if r.status_code == 403:
        di("403 — las claves son válidas pero la app no tiene permiso.")
        di("En User authentication settings poné 'Read and Write' y REGENERÁ el Access Token:")
        di("los tokens viejos conservan el permiso viejo.")
        return 1
    if r.status_code != 200:
        di(f"{r.status_code} — respuesta inesperada de X:")
        di(r.text[:400])
        return 1

    datos = r.json().get("data", {})
    di("CLAVES OK")
    di(f"  cuenta:  @{datos.get('username', '?')}")
    di(f"  nombre:  {datos.get('name', '?')}")
    di(f"  id:      {datos.get('id', '?')}")

    # La v1.1 devuelve el nivel de acceso en una cabecera. Si contesta, nos
    # ahorra descubrir en el primer post que el token es solo de lectura.
    try:
        r2 = x.get("https://api.x.com/1.1/account/verify_credentials.json", timeout=20)
        nivel = r2.headers.get("x-access-level")
        if nivel:
            di(f"  permiso: {nivel}")
            if "write" not in nivel:
                di("\nEL TOKEN ES SOLO DE LECTURA. No va a poder publicar.")
                di("Poné 'Read and Write' en la app y regenerá el Access Token.")
                return 1
        else:
            di("  permiso: X no lo informó — se confirma con el primer post real")
    except Exception:
        di("  permiso: no se pudo consultar — se confirma con el primer post real")

    return 0


if __name__ == "__main__":
    codigo = main()
    volcar_resumen()
    sys.exit(codigo)
