#!/usr/bin/env python3
"""
verificar_claves.py - Confirma que las 4 claves de X funcionan, sin publicar.

    python3 verificar_claves.py

POR QUE EXISTE
    El modo prueba de publicar.py nunca llama a X, asi que no sirve para saber
    si las claves estan bien. Y la alternativa -publicar de verdad- cuesta
    USD 0,20 y ensucia el timeline si algo esta mal.

    Esto hace una sola lectura (GET /2/users/me, USD 0,010) y responde tres
    preguntas de una: si las 4 claves estan cargadas, si la firma OAuth 1.0a
    es valida, y a que cuenta pertenecen.

QUE NO PRUEBA
    El permiso de escritura. X no lo devuelve en v2. Se intenta leer la
    cabecera x-access-level de la API v1.1, que si lo dice, pero puede no
    estar disponible. La confirmacion definitiva de escritura es el primer
    post real.
"""

import os
import sys

CLAVES = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")


def main():
    faltan = [k for k in CLAVES if not os.environ.get(k)]
    if faltan:
        print("FALTAN SECRETOS EN GITHUB:")
        for k in faltan:
            print(f"  - {k}")
        print("\nSettings -> Secrets and variables -> Actions -> New repository secret")
        print("El nombre tiene que coincidir exactamente, en mayusculas.")
        return 1

    # Aviso temprano de un error clasico: pegar el valor con espacios o comillas.
    for k in CLAVES:
        v = os.environ[k]
        if v != v.strip():
            print(f"OJO: {k} tiene espacios al principio o al final. Recargalo sin espacios.")
            return 1
        if v[0] in "\"'" or v[-1] in "\"'":
            print(f"OJO: {k} quedo con comillas. Se pega el valor pelado, sin comillas.")
            return 1

    from requests_oauthlib import OAuth1Session

    x = OAuth1Session(os.environ["X_API_KEY"], os.environ["X_API_SECRET"],
                      os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_SECRET"])

    r = x.get("https://api.x.com/2/users/me", timeout=30)

    if r.status_code == 401:
        print("401 - las claves no son validas.")
        print("Causa mas comun: se regenero la Consumer Key despues del Access Token,")
        print("lo que invalida el token. Regenera primero Consumer Key, despues Access Token.")
        return 1
    if r.status_code == 403:
        print("403 - las claves son validas pero la app no tiene permiso.")
        print("En User authentication settings pone 'Read and Write' y REGENERA el Access Token:")
        print("los tokens viejos conservan el permiso viejo.")
        return 1
    if r.status_code != 200:
        print(f"{r.status_code} - respuesta inesperada de X:")
        print(r.text[:400])
        return 1

    datos = r.json().get("data", {})
    print("CLAVES OK")
    print(f"  cuenta:  @{datos.get('username', '?')}")
    print(f"  nombre:  {datos.get('name', '?')}")
    print(f"  id:      {datos.get('id', '?')}")

    # La v1.1 devuelve el nivel de acceso en una cabecera. Si contesta, nos
    # ahorra descubrir en el primer post que el token es solo de lectura.
    try:
        r2 = x.get("https://api.x.com/1.1/account/verify_credentials.json", timeout=20)
        nivel = r2.headers.get("x-access-level")
        if nivel:
            print(f"  permiso: {nivel}")
            if "write" not in nivel:
                print("\nEL TOKEN ES SOLO DE LECTURA. No va a poder publicar.")
                print("Pone 'Read and Write' en la app y regenera el Access Token.")
                return 1
        else:
            print("  permiso: X no lo informo - se confirma con el primer post real")
    except Exception:
        print("  permiso: no se pudo consultar - se confirma con el primer post real")

    return 0


if __name__ == "__main__":
    sys.exit(main())
