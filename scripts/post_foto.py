#!/usr/bin/env python3
"""Post con foto nueva: sube la foto a Pinata, escribe el texto con Groq
y publica en Instagram + Facebook. Rutas protegidas con ADMIN_SECRET."""
import hmac
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from flask import Blueprint, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generar_contenido as gen
import publicar_desde_pinata as pdp

bp = Blueprint("post_foto", __name__)
MAX_BYTES = 8 * 1024 * 1024


def _clave_ok():
    esperada = os.environ.get("ADMIN_SECRET", "")
    return bool(esperada) and hmac.compare_digest(request.args.get("clave", ""), esperada)


def _caption(sugerencia, anterior=""):
    api_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY no configurada")
    prompt = ("Escribe un caption corto para Instagram y Facebook de Manantial de Pueblo, "
              "para acompanar una foto que subio el cliente. Maximo 3-4 lineas.")
    if sugerencia:
        prompt += f" Indicacion del cliente, respetala: {sugerencia}."
    if anterior:
        prompt += f" Escribe uno claramente distinto a este:\n{anterior}"
    r = requests.post(
        gen.GROQ_URL, timeout=45,
        headers={"Authorization": f"Bearer {api_key}", "User-Agent": "curl/8.5.0"},
        json={"model": gen.GROQ_MODEL, "temperature": 0.9,
              "messages": [{"role": "system", "content": gen.SYSTEM_PROMPT},
                           {"role": "user", "content": prompt}]})
    if r.status_code != 200:
        raise RuntimeError(f"Groq HTTP {r.status_code}")
    return r.json()["choices"][0]["message"]["content"].strip()


def _ig(url, caption):
    token = os.environ["INSTAGRAM_ACCESS_TOKEN"].strip()
    c = requests.post(f"{pdp.IG_GRAPH}/{pdp.IG_ACCOUNT_ID}/media", timeout=60, data={
        "image_url": url, "caption": caption, "access_token": token}).json()
    if "id" not in c:
        return {"ok": False, "paso": "crear_contenedor", "detalle": c}
    for _ in range(10):
        time.sleep(3)
        st = requests.get(f"{pdp.IG_GRAPH}/{c['id']}", timeout=30, params={
            "fields": "status_code", "access_token": token}).json()
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            return {"ok": False, "paso": "procesar", "detalle": st}
    pub = requests.post(f"{pdp.IG_GRAPH}/{pdp.IG_ACCOUNT_ID}/media_publish", timeout=60, data={
        "creation_id": c["id"], "access_token": token}).json()
    return {"ok": "id" in pub, "detalle": pub}


def _fb(url, caption):
    token = (os.environ.get("FACEBOOK_PUBLIC_TOKEN")
             or os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN_LONG") or "").strip()
    page = os.environ["FACEBOOK_PAGE_ID"].strip()
    res = requests.post(f"{pdp.FB_GRAPH}/{page}/photos", timeout=60, data={
        "url": url, "caption": caption, "access_token": token}).json()
    return {"ok": "id" in res, "detalle": res}


@bp.route("/post_foto/generar", methods=["POST"])
def generar():
    if not _clave_ok():
        return jsonify({"error": "clave invalida"}), 403
    foto = request.files.get("foto")
    sugerencia = (request.form.get("sugerencia") or "").strip()[:300]
    if not foto:
        return jsonify({"error": "falta la foto"}), 400
    datos = foto.read(MAX_BYTES + 1)
    if len(datos) > MAX_BYTES:
        return jsonify({"error": "la foto pesa mas de 8 MB"}), 413
    if datos[:3] != b"\xff\xd8\xff":
        return jsonify({"error": "la foto debe ser JPEG"}), 400
    try:
        meta = json.dumps({"name": "foto_post.jpg", "keyvalues": {"tipo": "foto_post"}})
        r = requests.post(f"{pdp.PINATA_API}/pinning/pinFileToIPFS", headers=pdp._h(), timeout=120,
                          files={"file": ("foto_post.jpg", datos, "image/jpeg")},
                          data={"pinataMetadata": meta})
        r.raise_for_status()
        url = pdp.GATEWAY + r.json()["IpfsHash"]
        texto = _caption(sugerencia)
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 502
    return jsonify({"foto_url": url, "caption": texto})


@bp.route("/post_foto/repetir", methods=["POST"])
def repetir():
    if not _clave_ok():
        return jsonify({"error": "clave invalida"}), 403
    d = request.get_json(silent=True) or {}
    try:
        texto = _caption(str(d.get("sugerencia", "")).strip()[:300],
                         str(d.get("caption", "")).strip()[:1500])
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 502
    return jsonify({"caption": texto})


@bp.route("/post_foto/publicar", methods=["POST"])
def publicar():
    if not _clave_ok():
        return jsonify({"error": "clave invalida"}), 403
    d = request.get_json(silent=True) or {}
    url = str(d.get("foto_url", ""))
    caption = str(d.get("caption", "")).strip()
    if not url.startswith(pdp.GATEWAY):
        return jsonify({"error": "foto_url invalida"}), 400
    if not caption or len(caption) > 2200:
        return jsonify({"error": "caption vacio o demasiado largo"}), 400
    with ThreadPoolExecutor(max_workers=2) as ex:
        fi = ex.submit(pdp._seguro, _ig, url, caption)
        ff = ex.submit(pdp._seguro, _fb, url, caption)
        res = {"instagram": fi.result(), "facebook": ff.result()}
    return jsonify(res)
