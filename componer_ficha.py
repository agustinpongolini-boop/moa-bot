#!/usr/bin/env python3
"""
componer_ficha.py — Genera la imagen del post SIN intervención humana.

    python3 componer_ficha.py datos.json --salida foto.png

POR QUÉ ASÍ Y NO CON SCREENSHOT
    Verificado el 01/09/2026 desde un servidor:
      · https://www.mercadolibre.com.ar/...   →  HTTP 403  (bloquea datacenter)
      · https://http2.mlstatic.com/...(imagen) →  HTTP 200  (CDN abierto)
    Un screenshot headless de la publicación va a fallar en el VPS. La foto del
    producto, en cambio, se descarga sin problema. Así que la ficha se COMPONE:
    imagen oficial del producto + los datos capturados en el lote semanal.

VENTAJAS SOBRE EL SCREENSHOT
    · No depende de que Mercado Libre no cambie su HTML.
    · No depende de anti-bot ni de sesión iniciada.
    · Es marca propia y consistente en los 800 posts del trimestre.
    · Pesa y tarda una fracción de lo que tarda un navegador headless.

Entrada: un dict/JSON con titulo, precio, precio_lista, off, cuotas,
cuotas_sin_interes, cupon, envio_gratis, rank, rank_categoria,
unidades_vendidas, imagen (URL del CDN).
"""

import argparse
import io
import json
import urllib.request

from PIL import Image, ImageDraw, ImageFont

W, H = 1600, 900
MARGEN = 60
COL_IMG = 760

AZUL = (52, 131, 250)
VERDE = (0, 166, 80)
NARANJA = (255, 122, 0)
NEGRO = (28, 28, 30)
GRIS = (120, 120, 128)
GRIS_CLARO = (232, 232, 236)
BLANCO = (255, 255, 255)

F = "/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf"


def fuente(px, bold=False):
    return ImageFont.truetype(F % ("-Bold" if bold else ""), px)


def ars(n):
    try:
        return "$" + f"{int(n):,}".replace(",", ".")
    except (TypeError, ValueError):
        return ""


def bajar_imagen(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return Image.open(io.BytesIO(r.read())).convert("RGB")


def envolver(draw, texto, fnt, ancho):
    palabras, lineas, actual = texto.split(), [], ""
    for p in palabras:
        prueba = (actual + " " + p).strip()
        if draw.textlength(prueba, font=fnt) <= ancho:
            actual = prueba
        else:
            if actual:
                lineas.append(actual)
            actual = p
    if actual:
        lineas.append(actual)
    return lineas


def pastilla(draw, x, y, texto, fnt, fondo, color=BLANCO, pad=(14, 8)):
    an = draw.textlength(texto, font=fnt)
    al = fnt.size + pad[1] * 2
    draw.rounded_rectangle([x, y, x + an + pad[0] * 2, y + al], radius=6, fill=fondo)
    draw.text((x + pad[0], y + pad[1] - 1), texto, font=fnt, fill=color)
    return x + an + pad[0] * 2, y + al


def _panel(dr, d, x, ancho, y):
    """Dibuja la columna de datos desde y y devuelve la y final.

    Se llama dos veces: la primera sobre un lienzo descartable, solo para medir
    cuanto ocupa; la segunda sobre el lienzo real, ya centrada verticalmente.
    Sin esto la ficha queda pegada arriba y con medio cuadro en blanco.
    """
    # --- señales de conversión ---------------------------------------------
    if d.get("rank"):
        xf, _ = pastilla(dr, x, y, "MÁS VENDIDO", fuente(24, True), NARANJA)
        etiqueta = f"{d['rank']}º en {d.get('rank_categoria','su categoría')}"
        dr.text((xf + 14, y + 9), etiqueta, font=fuente(24), fill=AZUL)
        y += 56
    if d.get("unidades_vendidas"):
        u = int(d["unidades_vendidas"])
        txt = f"+{u//1000} mil vendidos" if u >= 1000 else f"+{u} vendidos"
        dr.text((x, y), f"Nuevo  |  {txt}", font=fuente(24), fill=GRIS)
        y += 44

    # --- título -------------------------------------------------------------
    ft = fuente(44, True)
    for linea in envolver(dr, d.get("titulo", ""), ft, ancho)[:3]:
        dr.text((x, y), linea, font=ft, fill=NEGRO)
        y += 54
    y += 18

    # --- precios ------------------------------------------------------------
    if d.get("precio_lista") and int(d["precio_lista"]) > int(d.get("precio", 0)):
        t = ars(d["precio_lista"])
        dr.text((x, y), t, font=fuente(30), fill=GRIS)
        an = dr.textlength(t, font=fuente(30))
        dr.line([x, y + 20, x + an, y + 20], fill=GRIS, width=2)
        y += 46

    fp = fuente(78, True)
    dr.text((x, y), ars(d.get("precio")), font=fp, fill=NEGRO)
    anp = dr.textlength(ars(d.get("precio")), font=fp)
    if d.get("off"):
        pastilla(dr, x + anp + 22, y + 22, str(d["off"]), fuente(30, True), VERDE)
    y += 100

    if d.get("cuotas"):
        txt = d["cuotas"] + (" SIN INTERÉS" if d.get("cuotas_sin_interes") else "")
        dr.text((x, y), txt, font=fuente(30, True),
                fill=VERDE if d.get("cuotas_sin_interes") else GRIS)
        y += 46

    if d.get("cupon"):
        y += 8
        cup = f"  {ars(str(d['cupon']).replace('.',''))} con Cupón  "
        dr.rounded_rectangle([x, y, x + dr.textlength(cup, font=fuente(32, True)) + 20,
                              y + 56], radius=8, fill=(232, 242, 255))
        dr.text((x + 12, y + 12), cup.strip(), font=fuente(32, True), fill=AZUL)
        y += 74

    if d.get("envio_gratis"):
        dr.text((x, y), "Envío gratis", font=fuente(30, True), fill=VERDE)
        y += 46

    return y


def componer(d, salida="foto.png", marca="@MejorOfertaArg"):
    lienzo = Image.new("RGB", (W, H), BLANCO)
    dr = ImageDraw.Draw(lienzo)

    x = COL_IMG + 40
    ancho = W - x - MARGEN

    # --- medir la columna de datos para centrarla ---------------------------
    borrador = ImageDraw.Draw(Image.new("RGB", (W, H), BLANCO))
    alto = _panel(borrador, d, x, ancho, 0)
    tope_marca = H - MARGEN - 46            # la linea de la firma
    y0 = max(MARGEN, (tope_marca - alto) // 2)

    # --- producto -----------------------------------------------------------
    if d.get("imagen"):
        try:
            prod = bajar_imagen(d["imagen"])
            caja = COL_IMG - MARGEN
            prod.thumbnail((caja, tope_marca - MARGEN), Image.LANCZOS)
            lienzo.paste(prod, (MARGEN + (caja - prod.width) // 2,
                                (tope_marca - prod.height) // 2))
        except Exception as e:
            dr.text((MARGEN, H // 2), f"(sin imagen: {e})", font=fuente(20), fill=GRIS)

    _panel(dr, d, x, ancho, y0)

    # --- marca --------------------------------------------------------------
    dr.line([x, tope_marca, W - MARGEN, tope_marca], fill=GRIS_CLARO, width=2)
    dr.text((x, H - MARGEN - 32), marca, font=fuente(26, True), fill=GRIS)

    lienzo.save(salida, "PNG", optimize=True)
    return salida


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("datos", help="archivo JSON con los datos del producto")
    ap.add_argument("--salida", default="foto.png")
    a = ap.parse_args()
    with open(a.datos, encoding="utf-8") as f:
        d = json.load(f)
    print(componer(d, a.salida))


if __name__ == "__main__":
    main()
