#!/usr/bin/env python3
"""
Servicio web que expone el generador de contenido para que n8n
(u otra herramienta) lo pueda llamar por HTTP.
"""
import json
import os
import sys
import hmac
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from flask import Flask, request, jsonify

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generar_contenido as gen
import publicar_desde_pinata as pdp

app = Flask(__name__)

import post_foto
app.register_blueprint(post_foto.bp)

# Quita espacios y saltos de linea sobrantes al inicio/final de las variables de entorno
for _k, _v in list(os.environ.items()):
    if _v != _v.strip():
        os.environ[_k] = _v.strip()
        print(f"[entorno] variable limpiada: {_k}", flush=True)

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


@app.route("/manifest.json")
def manifest_app():
    datos = {
        "name": "App Publicar",
        "short_name": "Publicar",
        "description": "Panel de publicacion de Manantial de Pueblo",
        "start_url": "/panel",
        "scope": "/",
        "display": "standalone",
        "background_color": "#16332B",
        "theme_color": "#16332B",
        "icons": [
            {"src": "/static/icono-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icono-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
    return app.response_class(json.dumps(datos), mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    codigo = "self.addEventListener('install',function(e){self.skipWaiting();});self.addEventListener('activate',function(e){e.waitUntil(self.clients.claim());});self.addEventListener('fetch',function(e){e.respondWith(fetch(e.request));});"
    return app.response_class(codigo, mimetype="application/javascript")


@app.route("/panel")
def panel():
    return """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Manantial de Pueblo - Panel de publicacion</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#16332B">
<link rel="manifest" href="/manifest.json">
<link rel="icon" href="/static/icono-192.png">
<link rel="apple-touch-icon" href="/static/icono-192.png">
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
<button id="btn_shorts" onclick="publicarShorts()">Publicar Shorts (IG + FB + YouTube)</button>
<hr style="width:100%;max-width:600px;border-color:#2B6F63;margin-top:30px">
<h3>Post con tu foto</h3>
<input type="file" id="pf_foto" accept="image/*" style="max-width:100%">
<input type="text" id="pf_sug" placeholder="Sugerencia (opcional)" maxlength="300" style="margin-top:10px;padding:12px;width:90%;max-width:560px;border-radius:6px;border:none">
<button id="pf_gen" onclick="pfGenerar()">Generar post</button>
<div id="pf_vista" style="display:none;max-width:600px;margin-top:20px;text-align:center">
<img id="pf_img" style="max-width:100%;border-radius:8px">
<textarea id="pf_txt" rows="6" style="width:100%;margin-top:10px;padding:10px;border-radius:6px;border:none;box-sizing:border-box"></textarea>
<button id="pf_pub" onclick="pfPublicar()">Publicar (IG + FB)</button>
<button id="pf_rep" onclick="pfRepetir()" style="background:#555">Repetir texto</button>
</div>
<pre id="resultado"></pre>
<script>
if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js');}
var pfUrl = '';
function pfClave(){
  var c = localStorage.getItem('clave_panel');
  if(!c){ c = prompt('Ingresa la clave del panel:'); if(!c) return null; localStorage.setItem('clave_panel', c); }
  return c;
}
function pfReducir(file){
  return new Promise(function(ok, mal){
    var img = new Image();
    img.onload = function(){
      var r = Math.min(1, 1080 / Math.max(img.width, img.height));
      var cv = document.createElement('canvas');
      cv.width = Math.round(img.width * r); cv.height = Math.round(img.height * r);
      cv.getContext('2d').drawImage(img, 0, 0, cv.width, cv.height);
      cv.toBlob(function(b){ b ? ok(b) : mal(new Error('no pude reducir la foto')); }, 'image/jpeg', 0.82);
    };
    img.onerror = function(){ mal(new Error('no pude leer la foto')); };
    img.src = URL.createObjectURL(file);
  });
}
function pfBloquear(v){ ['pf_gen','pf_pub','pf_rep'].forEach(function(i){ document.getElementById(i).disabled = v; }); }
async function pfGenerar(){
  var clave = pfClave(); if(!clave) return;
  var f = document.getElementById('pf_foto').files[0];
  var out = document.getElementById('resultado');
  if(!f){ out.textContent = 'Escoge una foto primero.'; return; }
  pfBloquear(true); out.textContent = 'Subiendo foto y escribiendo el texto...';
  try {
    var blob = await pfReducir(f);
    var fd = new FormData();
    fd.append('foto', blob, 'foto.jpg');
    fd.append('sugerencia', document.getElementById('pf_sug').value);
    var resp = await fetch('/post_foto/generar?clave=' + encodeURIComponent(clave), {method:'POST', body: fd});
    var d = await resp.json();
    if(resp.status === 403){ localStorage.removeItem('clave_panel'); out.textContent = 'Clave incorrecta, intenta de nuevo.'; }
    else if(!resp.ok){ out.textContent = JSON.stringify(d, null, 2); }
    else {
      pfUrl = d.foto_url;
      document.getElementById('pf_img').src = pfUrl;
      document.getElementById('pf_txt').value = d.caption;
      document.getElementById('pf_vista').style.display = 'block';
      out.textContent = 'Revisa el texto. Puedes editarlo, repetirlo o publicar.';
    }
  } catch(e){ out.textContent = 'Error: ' + e; }
  pfBloquear(false);
}
async function pfRepetir(){
  var clave = pfClave(); if(!clave) return;
  var out = document.getElementById('resultado');
  pfBloquear(true); out.textContent = 'Escribiendo otro texto...';
  try {
    var resp = await fetch('/post_foto/repetir?clave=' + encodeURIComponent(clave), {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({sugerencia: document.getElementById('pf_sug').value, caption: document.getElementById('pf_txt').value})});
    var d = await resp.json();
    if(resp.ok){ document.getElementById('pf_txt').value = d.caption; out.textContent = 'Texto nuevo listo.'; }
    else { out.textContent = JSON.stringify(d, null, 2); }
  } catch(e){ out.textContent = 'Error: ' + e; }
  pfBloquear(false);
}
async function pfPublicar(){
  var clave = pfClave(); if(!clave) return;
  var out = document.getElementById('resultado');
  pfBloquear(true); out.textContent = 'Publicando en Instagram y Facebook...';
  try {
    var resp = await fetch('/post_foto/publicar?clave=' + encodeURIComponent(clave), {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({foto_url: pfUrl, caption: document.getElementById('pf_txt').value})});
    var d = await resp.json();
    out.textContent = JSON.stringify(d, null, 2);
  } catch(e){ out.textContent = 'Error: ' + e; }
  pfBloquear(false);
}

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

async function publicarShorts(){
  let clave = localStorage.getItem('clave_panel');
  if(!clave){
    clave = prompt('Ingresa la clave del panel:');
    if(!clave) return;
    localStorage.setItem('clave_panel', clave);
  }
  const btn = document.getElementById('btn_shorts');
  const out = document.getElementById('resultado');
  btn.disabled = true;
  out.textContent = 'Enviando...';
  try {
    const resp = await fetch('/publicar_shorts?clave=' + encodeURIComponent(clave), {method:'POST'});
    const data = await resp.json();
    if(resp.status === 403){
      localStorage.removeItem('clave_panel');
      out.textContent = 'Clave incorrecta, intenta de nuevo.';
      btn.disabled = false;
      return;
    }
    if(resp.status !== 202){
      out.textContent = JSON.stringify(data, null, 2);
      btn.disabled = false;
      return;
    }
    while(true){
      await new Promise(r => setTimeout(r, 5000));
      const st = await (await fetch('/estado_short?clave=' + encodeURIComponent(clave))).json();
      if(st.estado === 'publicando'){
        out.textContent = 'Publicando... ' + (st.paso || '') + ' (no cierres esta pestana)';
      } else {
        out.textContent = JSON.stringify(st, null, 2);
        break;
      }
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


_short_lock = threading.Lock()
_short_estado = {"estado": "sin_trabajos"}


def _clave_panel_ok():
    esperada = os.environ.get("ADMIN_SECRET", "")
    return bool(esperada) and hmac.compare_digest(request.args.get("clave", ""), esperada)


def _trabajo_short():
    def avance(texto):
        _short_estado["paso"] = texto
    try:
        _short_estado["resultado"] = pdp.publicar_siguiente(publicar=True, avance=avance)
        _short_estado["estado"] = "terminado"
    except pdp.SinVideo as e:
        _short_estado.update({"estado": "sin_video", "mensaje": str(e)})
    except Exception as e:
        _short_estado.update({"estado": "error", "mensaje": f"{type(e).__name__}: {e}"})
    finally:
        _short_estado["fin"] = datetime.now(timezone.utc).isoformat()
        _short_lock.release()


@app.route("/publicar_shorts", methods=["POST"])
def publicar_shorts():
    if not os.environ.get("ADMIN_SECRET"):
        return jsonify({"error": "ADMIN_SECRET no esta configurada en Render"}), 500
    if not _clave_panel_ok():
        return jsonify({"error": "clave invalida"}), 403
    if not _short_lock.acquire(blocking=False):
        return jsonify({"error": "ya hay un video publicandose", "estado": _short_estado}), 409
    _short_estado.clear()
    _short_estado.update({"estado": "publicando", "paso": "Empezando",
                          "inicio": datetime.now(timezone.utc).isoformat()})
    threading.Thread(target=_trabajo_short, daemon=True).start()
    return jsonify({"aceptado": True}), 202


@app.route("/estado_short")
def estado_short():
    if not _clave_panel_ok():
        return jsonify({"error": "clave invalida"}), 403
    return jsonify(_short_estado)


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


def _youtube_access_token():
    datos = urllib.parse.urlencode({
        "client_id": os.environ["ID_CLIENT_API_YOUTUBE"].strip(),
        "client_secret": os.environ["SECRET_CLIENT_API_YOUTUBE"].strip(),
        "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"].strip(),
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=datos, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())["access_token"]


def _youtube_subir(access_token, video_url, titulo, descripcion, privacidad):
    import tempfile
    req_dl = urllib.request.Request(video_url, headers={"User-Agent": "curl/8.5.0"})
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        ruta = tmp.name
        with urllib.request.urlopen(req_dl, timeout=120) as r:
            while True:
                bloque = r.read(1024 * 1024)
                if not bloque:
                    break
                tmp.write(bloque)

    tam = os.path.getsize(ruta)
    meta = {
        "snippet": {"title": titulo, "description": descripcion, "categoryId": "22"},
        "status": {"privacyStatus": privacidad, "selfDeclaredMadeForKids": False},
    }
    inicio = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        data=json.dumps(meta).encode(),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(tam),
            "X-Upload-Content-Type": "video/mp4",
        },
        method="POST",
    )
    with urllib.request.urlopen(inicio, timeout=60) as r:
        url_subida = r.headers["Location"]

    with open(ruta, "rb") as f:
        datos_video = f.read()
    os.remove(ruta)

    subida = urllib.request.Request(
        url_subida, data=datos_video,
        headers={"Content-Type": "video/mp4", "Content-Length": str(tam)},
        method="PUT",
    )
    with urllib.request.urlopen(subida, timeout=600) as r:
        return json.loads(r.read().decode())


@app.route("/publicar_youtube", methods=["POST"])
def publicar_youtube():
    clave_esperada = os.environ.get("ADMIN_SECRET")
    if clave_esperada and request.args.get("clave", "") != clave_esperada:
        return jsonify({"error": "clave invalida"}), 403

    faltan = [v for v in ("ID_CLIENT_API_YOUTUBE", "SECRET_CLIENT_API_YOUTUBE", "YOUTUBE_REFRESH_TOKEN")
              if not os.environ.get(v)]
    if faltan:
        return jsonify({"error": "faltan variables de entorno", "faltan": faltan}), 500

    videos = gen.cargar_json(os.path.join(gen.BASE_DIR, "contenido", "videos.json"), [])
    if not videos:
        return jsonify({"error": "no hay videos en contenido/videos.json"}), 500

    body = request.get_json(silent=True) or {}
    privacidad = body.get("privacidad", "private")
    video = videos[0]

    try:
        token = _youtube_access_token()
        res = _youtube_subir(
            token, video["video_pinata_url"], video["titulo"],
            "Publicado automaticamente por Manantial de Pueblo Bot.", privacidad,
        )
    except urllib.error.HTTPError as e:
        return jsonify({"ok": False, "error": e.read().decode()}), 502

    return jsonify({
        "ok": "id" in res,
        "youtube_id": res.get("id"),
        "privacidad": res.get("status", {}).get("privacyStatus"),
        "url": f"https://www.youtube.com/watch?v={res.get('id')}" if res.get("id") else None,
    })


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


@app.route("/")
def pagina_inicio():
    return """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Manantial de Pueblo Bot</title></head>
<body style="font-family:sans-serif;max-width:700px;margin:40px auto;padding:0 16px">
<h1>Manantial de Pueblo Bot</h1>
<p>Herramienta interna de Manantial de Pueblo, empresa de agua potable envasada en Guaca, Santander (Colombia). Genera contenido promocional y lo publica de forma automatica en las redes sociales de la empresa (Facebook, Instagram y YouTube).</p>
<p>Para YouTube, la aplicacion solicita unicamente el permiso de subir videos al canal propio de la empresa.</p>
<p><a href="/privacidad">Politica de privacidad</a></p>
<p>Contacto: manantialdepueblo@gmail.com</p>
</body></html>"""


@app.route("/privacidad")
def pagina_privacidad():
    return """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Politica de privacidad - Manantial de Pueblo Bot</title></head>
<body style="font-family:sans-serif;max-width:700px;margin:40px auto;padding:0 16px">
<h1>Politica de privacidad</h1>
<p>Manantial de Pueblo Bot es una herramienta de uso interno. No es una aplicacion publica ni ofrece servicios a terceros.</p>
<h2>Datos de Google que se usan</h2>
<p>Con la autorizacion del propietario de la cuenta, la aplicacion usa el permiso de YouTube para subir videos (youtube.upload) al canal de Manantial de Pueblo. No lee ni recopila datos personales de otros usuarios.</p>
<h2>Almacenamiento y uso</h2>
<p>Las credenciales de acceso (tokens) se guardan en el servidor de la aplicacion y se usan solo para publicar contenido en el canal del propietario. No se venden, no se comparten ni se transfieren a terceros.</p>
<h2>Revocar el acceso o pedir eliminacion de datos</h2>
<p>El acceso se puede revocar en https://myaccount.google.com/permissions . Para pedir la eliminacion de datos, escribe a manantialdepueblo@gmail.com.</p>
<p><a href="/">Volver al inicio</a></p>
</body></html>"""


@app.route("/diag_youtube")
def diag_youtube():
    cid = os.environ.get("ID_CLIENT_API_YOUTUBE")
    sec = os.environ.get("SECRET_CLIENT_API_YOUTUBE")
    return jsonify({
        "client_id": repr(cid),
        "secret_largo": len(sec) if sec else None,
        "secret_ultimos4": repr(sec[-4:]) if sec else None,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)))
