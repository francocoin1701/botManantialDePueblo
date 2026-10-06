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


@app.route("/panel")
def panel():
    return """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Manantial de Pueblo - Panel de publicacion</title>
<style>
body{font-family:sans-serif;background:#16332B;color:#EFEADD;display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:20px;}
button{background:#2B6F63;color:white;border:none;padding:18px 36px;font-size:1.1rem;border-radius:6px;cursor:pointer;margin-top:20px;}
button:disabled{opacity:.5;cursor:wait;}
pre{background:#0d1f1a;padding:16px;border-radius:6px;max-width:600px;overflow-x:auto;margin-top:20px;white-space:pre-wrap;}
</style>
</head>
<body>
<h2>Manantial de Pueblo</h2>
<p>Presiona el boton para generar y publicar un post nuevo en Instagram y Facebook.</p>
<button id="btn" onclick="publicar()">Publicar ahora</button>
<pre id="resultado"></pre>
<script>
async function publicar(){
  let clave = localStorage.getItem('clave_panel');
  if(!clave){
    clave = prompt('Ingresa la clave del panel:');
    if(!clave) return;
    localStorage.setItem('clave_panel', clave);
  }
  const btn = document.getElementById('btn');
  const out = document.getElementById('resultado');
  btn.disabled = true;
  out.textContent = 'Publicando, espera unos segundos...';
  try {
    const resp = await fetch('/ciclo_completo?clave=' + encodeURIComponent(clave), {method:'POST'});
    const data = await resp.json();
    if(resp.status === 403){
      localStorage.removeItem('clave_panel');
      out.textContent = 'Clave incorrecta, intenta de nuevo.';
    } else {
      out.textContent = JSON.stringify(data, null, 2);
    }
  } catch(e) {
    out.textContent = 'Error: ' + e;
  }
  btn.disabled = false;
}
</script>
</body>
</html>
"""


@app.route("/youtube_callback")
def youtube_callback():
    codigo = request.args.get("code")
    if not codigo:
        return jsonify({"error": "no llego el parametro code"}), 400

    client_id = os.environ.get("ID_CLIENT_API_YOUTUBE")
    client_secret = os.environ.get("SECRET_CLIENT_API_YOUTUBE")
    redirect_uri = "https://botmanantialdepueblo.onrender.com/youtube_callback"

    datos = urllib.parse.urlencode({
        "code": codigo,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=datos, method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            tokens = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return jsonify({"error": "fallo el intercambio", "detalle": e.read().decode()}), 400

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        return jsonify({
            "aviso": "No llego refresh_token. Probablemente ya autorizaste antes. Revoca el acceso en https://myaccount.google.com/permissions y repite el proceso.",
            "tokens_recibidos": tokens,
        })

    return f"""
    <h2>Autorizacion exitosa</h2>
    <p>Copia este refresh_token y guardalo en Render como YOUTUBE_REFRESH_TOKEN:</p>
    <pre style="background:#eee;padding:16px;word-break:break-all;">{refresh_token}</pre>
    """


@app.route("/ciclo_completo", methods=["POST"])
def ciclo_completo():
    clave_esperada = os.environ.get("ADMIN_SECRET")
    if clave_esperada:
        clave_recibida = request.args.get("clave", "")
        if clave_recibida != clave_esperada:
            return jsonify({"error": "clave invalida"}), 403

    groq_key = os.environ.get("GROQ_API_KEY")
    ig_token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    fb_token = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN_LONG")
    fb_page_id = os.environ.get("FACEBOOK_PAGE_ID")

    faltantes = [n for n, v in [
        ("GROQ_API_KEY", groq_key), ("INSTAGRAM_ACCESS_TOKEN", ig_token),
        ("FACEBOOK_PAGE_ACCESS_TOKEN_LONG", fb_token), ("FACEBOOK_PAGE_ID", fb_page_id),
    ] if not v]
    if faltantes:
        return jsonify({"error": "faltan variables de entorno", "faltan": faltantes}), 500

    productos = gen.cargar_json(gen.PRODUCTOS_PATH, [])
    if not productos:
        return jsonify({"error": "no hay productos configurados"}), 500

    import random
    estado = gen.cargar_json(gen.ESTADO_PATH, {"ultima_foto_id": None})
    candidatos = [p for p in productos if p["id"] != estado.get("ultima_foto_id")]
    if not candidatos:
        candidatos = productos
    producto = random.choice(candidatos)
    estado["ultima_foto_id"] = producto["id"]
    gen.guardar_json(gen.ESTADO_PATH, estado)

    if not producto.get("imagen_pinata_url"):
        return jsonify({"error": f"el producto {producto['id']} no tiene imagen_pinata_url"}), 500

    imagen_url = producto["imagen_pinata_url"]
    caption = gen.llamar_groq(groq_key, producto)

    crear = _graph_post(
        f"{IG_GRAPH}/{IG_ACCOUNT_ID}/media",
        {"image_url": imagen_url, "caption": caption, "access_token": ig_token},
    )
    resultado_ig = {"ok": False, "detalle": crear}
    if "id" in crear:
        time.sleep(5)
        pub = _graph_post(
            f"{IG_GRAPH}/{IG_ACCOUNT_ID}/media_publish",
            {"creation_id": crear["id"], "access_token": ig_token},
        )
        resultado_ig = {"ok": "id" in pub, "detalle": pub}

    resultado_fb = _graph_post(
        f"{FB_GRAPH}/{fb_page_id}/photos",
        {"url": imagen_url, "caption": caption, "access_token": fb_token},
    )
    resultado_fb = {"ok": "id" in resultado_fb, "detalle": resultado_fb}

    entrada = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "producto_id": producto["id"],
        "producto_nombre": producto["nombre"],
        "caption": caption,
        "imagen_url": imagen_url,
        "instagram": resultado_ig,
        "facebook": resultado_fb,
        "estado": "publicado" if resultado_ig["ok"] and resultado_fb["ok"] else "con_errores",
    }
    with open(gen.CALENDARIO_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entrada, ensure_ascii=False) + "\n")

    return jsonify(entrada)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)))
