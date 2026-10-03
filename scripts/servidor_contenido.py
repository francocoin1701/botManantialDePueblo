#!/usr/bin/env python3
"""
Servicio web que expone el generador de contenido para que n8n
(u otra herramienta) lo pueda llamar por HTTP.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from flask import Flask, request, jsonify

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generar_contenido as gen

app = Flask(__name__)

IG_ACCOUNT_ID = "29600427372879503"
IG_GRAPH = "https://graph.instagram.com/v26.0"
FB_GRAPH = "https://graph.facebook.com/v26.0"
IMAGEN_URL = "https://gateway.pinata.cloud/ipfs/bafybeiev7wmqr24ukaaa6ft43tomd77iaitn6wtilmjrllu633v6lmsa3u"


def _graph_post(url, datos):
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(datos).encode("utf-8"),
        headers={"User-Agent": "curl/8.5.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"error": f"HTTP {e.code} sin cuerpo JSON"}


@app.route("/salud", methods=["GET"])
def salud():
    return jsonify({"estado": "vivo"})


@app.route("/generar", methods=["POST"])
def generar():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return jsonify({"error": "GROQ_API_KEY no configurada en el entorno del servidor"}), 500

    body = request.get_json(silent=True) or {}
    productos = gen.cargar_json(gen.PRODUCTOS_PATH, [])
    if not productos:
        return jsonify({"error": "no hay productos configurados"}), 500

    producto_id = body.get("producto_id")

    if producto_id:
        objetivo = [p for p in productos if p["id"] == producto_id]
        if not objetivo:
            return jsonify({"error": f"producto_id '{producto_id}' no existe"}), 404
    elif body.get("todos"):
        objetivo = productos
    else:
        estado = gen.cargar_json(gen.ESTADO_PATH, {"ultimo_indice": -1})
        siguiente = (estado["ultimo_indice"] + 1) % len(productos)
        objetivo = [productos[siguiente]]
        estado["ultimo_indice"] = siguiente
        gen.guardar_json(gen.ESTADO_PATH, estado)

    resultados = []
    for producto in objetivo:
        caption = gen.llamar_groq(api_key, producto)
        entrada = gen.construir_entrada(producto, caption)
        with open(gen.CALENDARIO_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entrada, ensure_ascii=False) + "\n")
        resultados.append(entrada)

    return jsonify({"generados": resultados})


@app.route("/publicar_instagram", methods=["POST"])
def publicar_instagram():
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    if not token:
        return jsonify({"error": "INSTAGRAM_ACCESS_TOKEN no configurada en el entorno del servidor"}), 500

    body = request.get_json(silent=True) or {}
    caption = (body.get("caption") or "").strip()
    if not caption:
        return jsonify({"error": "falta 'caption' en el cuerpo"}), 400

    crear = _graph_post(
        f"{IG_GRAPH}/{IG_ACCOUNT_ID}/media",
        {"image_url": IMAGEN_URL, "caption": caption, "access_token": token},
    )
    if "id" not in crear:
        return jsonify({"ok": False, "paso": "crear_contenedor", "respuesta": crear}), 502

    time.sleep(5)  # damos tiempo a que Instagram procese la imagen

    pub = _graph_post(
        f"{IG_GRAPH}/{IG_ACCOUNT_ID}/media_publish",
        {"creation_id": crear["id"], "access_token": token},
    )
    if "id" not in pub:
        return jsonify({"ok": False, "paso": "publicar", "contenedor": crear["id"], "respuesta": pub}), 502

    return jsonify({"ok": True, "instagram_id": pub["id"], "contenedor": crear["id"]})


@app.route("/publicar_facebook", methods=["POST"])
def publicar_facebook():
    token = os.environ.get("FACEBOOK_PUBLIC_TOKEN")
    page_id = os.environ.get("FACEBOOK_PAGE_ID")
    if not token or not page_id:
        return jsonify({"error": "FACEBOOK_PUBLIC_TOKEN o FACEBOOK_PAGE_ID no configuradas en el entorno del servidor"}), 500

    body = request.get_json(silent=True) or {}
    caption = (body.get("caption") or "").strip()
    if not caption:
        return jsonify({"error": "falta 'caption' en el cuerpo"}), 400

    res = _graph_post(
        f"{FB_GRAPH}/{page_id}/photos",
        {"url": IMAGEN_URL, "caption": caption, "access_token": token},
    )
    if "id" not in res:
        return jsonify({"ok": False, "respuesta": res}), 502

    return jsonify({"ok": True, "facebook_id": res["id"], "post_id": res.get("post_id")})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
