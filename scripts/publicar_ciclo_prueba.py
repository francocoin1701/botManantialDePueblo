#!/usr/bin/env python3
"""Ciclo de prueba: genera caption con Groq y publica en Instagram + Facebook,
usando una imagen que YA está en Pinata (URL fija, sin subir nada)."""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generar_contenido as gen

IMAGEN_URL = "https://gateway.pinata.cloud/ipfs/bafybeiev7wmqr24ukaaa6ft43tomd77iaitn6wtilmjrllu633v6lmsa3u"
PRODUCTO_ID = "600ml_azul"  # la botella azul, la misma de la imagen


def publicar_instagram(ig_user_id, token, imagen_url, caption):
    params1 = urllib.parse.urlencode({
        "image_url": imagen_url, "caption": caption, "access_token": token
    }).encode()
    req1 = urllib.request.Request(
        f"https://graph.instagram.com/v26.0/{ig_user_id}/media",
        data=params1, method="POST")
    with urllib.request.urlopen(req1) as r:
        data1 = json.load(r)
    if "id" not in data1:
        return {"ok": False, "error": data1}
    params2 = urllib.parse.urlencode({
        "creation_id": data1["id"], "access_token": token
    }).encode()
    req2 = urllib.request.Request(
        f"https://graph.instagram.com/v26.0/{ig_user_id}/media_publish",
        data=params2, method="POST")
    with urllib.request.urlopen(req2) as r:
        data2 = json.load(r)
    return {"ok": "id" in data2, "respuesta": data2}


def publicar_facebook(page_id, token, imagen_url, caption):
    params = urllib.parse.urlencode({
        "url": imagen_url, "caption": caption, "access_token": token
    }).encode()
    req = urllib.request.Request(
        f"https://graph.facebook.com/v26.0/{page_id}/photos",
        data=params, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            data = json.load(r)
        return {"ok": "id" in data or "post_id" in data, "respuesta": data}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": json.loads(e.read().decode())}


def main():
    groq_key = os.environ["GROQ_API_KEY"]
    ig_token = os.environ["INSTAGRAM_ACCESS_TOKEN"]
    ig_user_id = os.environ["INSTAGRAM_USER_ID"]
    fb_token = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN_LONG") or os.environ["FACEBOOK_PUBLIC_TOKEN"]
    fb_page_id = os.environ["FACEBOOK_PAGE_ID"]

    productos = gen.cargar_json(gen.PRODUCTOS_PATH, [])
    producto = next(p for p in productos if p["id"] == PRODUCTO_ID)

    print(f"-> Producto: {producto['nombre']}")
    print("-> Generando caption con Groq...")
    caption = gen.llamar_groq(groq_key, producto)
    print(f"   {caption}\n")

    print("-> Publicando en Instagram...")
    r_ig = publicar_instagram(ig_user_id, ig_token, IMAGEN_URL, caption)
    print(f"   {r_ig}\n")

    print("-> Publicando en Facebook...")
    r_fb = publicar_facebook(fb_page_id, fb_token, IMAGEN_URL, caption)
    print(f"   {r_fb}\n")

    entrada = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "producto_id": producto["id"],
        "caption": caption,
        "imagen_url": IMAGEN_URL,
        "instagram": r_ig,
        "facebook": r_fb,
        "estado": "publicado" if r_ig.get("ok") and r_fb.get("ok") else "con_errores",
    }
    with open(gen.CALENDARIO_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entrada, ensure_ascii=False) + "\n")

    print("=" * 50)
    print("✓ CICLO COMPLETO" if entrada["estado"] == "publicado" else "⚠ Hubo errores")


if __name__ == "__main__":
    main()
