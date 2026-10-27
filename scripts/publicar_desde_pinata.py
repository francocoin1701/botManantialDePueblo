#!/usr/bin/env python3
"""PASO 2: toma un video etiquetado en Pinata (tipo=short_manantial), distinto al
ultimo publicado, y lo publica en IG Reels, FB Reels y YouTube Shorts. Despues
guarda en Pinata un JSON "ultimo_publicado" y borra el anterior.

Sin --publicar solo muestra que haria (no publica nada).
Uso (desde la raiz del repo, con las variables del .env cargadas):
    python3 scripts/publicar_desde_pinata.py
    python3 scripts/publicar_desde_pinata.py --publicar"""
import json
import os
import random
import sys
import tempfile
import time
from datetime import datetime, timezone

import requests

PINATA_API = "https://api.pinata.cloud"
GATEWAY = "https://gateway.pinata.cloud/ipfs/"
TIPO_VIDEO = "short_manantial"
TIPO_ULTIMO = "ultimo_publicado"

IG_ACCOUNT_ID = "29600427372879503"
IG_GRAPH = "https://graph.instagram.com/v26.0"
FB_GRAPH = "https://graph.facebook.com/v26.0"
HASHTAGS = "#ManantialDePueblo #AguaPotable #Guaca #Santander #Shorts"


def _h():
    return {"Authorization": f"Bearer {os.environ['PINATA_JWT'].strip()}"}


# ---------- Pinata ----------

def _pins():
    filas, off = [], 0
    while True:
        r = requests.get(f"{PINATA_API}/data/pinList", headers=_h(), timeout=60,
                         params={"status": "pinned", "pageLimit": 1000, "pageOffset": off})
        r.raise_for_status()
        rows = r.json().get("rows", [])
        filas += rows
        if len(rows) < 1000:
            return filas
        off += 1000


def _kv(fila):
    return (fila.get("metadata") or {}).get("keyvalues") or {}


def _por_tipo(filas, tipo):
    sel = [f for f in filas if _kv(f).get("tipo") == tipo]
    return sorted(sel, key=lambda f: f.get("date_pinned") or "", reverse=True)


GATEWAYS_LECTURA = [GATEWAY, "https://ipfs.io/ipfs/", "https://dweb.link/ipfs/"]


def _leer_ultimo(fila):
    """Lee ultimo_publicado probando varios gateways y esperando si hay 429."""
    ultimo_error = None
    for base in GATEWAYS_LECTURA:
        for intento in range(3):
            try:
                r = requests.get(base + fila["ipfs_pin_hash"], timeout=60)
                if r.status_code == 429:
                    ultimo_error = "429 Too Many Requests"
                    time.sleep(5 * (intento + 1))
                    continue
                r.raise_for_status()
                return r.json()["cid"]
            except (requests.exceptions.RequestException, ValueError, KeyError) as e:
                ultimo_error = e
                break
    raise RuntimeError(f"No se pudo leer ultimo_publicado: {ultimo_error}")


def _guardar_ultimo(cid, anteriores):
    cuerpo = {
        "pinataContent": {"cid": cid, "fecha": datetime.now(timezone.utc).isoformat()},
        "pinataMetadata": {"name": "ultimo_publicado.json", "keyvalues": {"tipo": TIPO_ULTIMO}},
    }
    r = requests.post(f"{PINATA_API}/pinning/pinJSONToIPFS", headers=_h(), json=cuerpo, timeout=60)
    r.raise_for_status()
    nuevo = r.json()["IpfsHash"]
    borrados = []
    for vieja in anteriores:  # solo despues de guardar bien el nuevo
        if vieja["ipfs_pin_hash"] == nuevo:
            continue
        d = requests.delete(f"{PINATA_API}/pinning/unpin/{vieja['ipfs_pin_hash']}",
                            headers=_h(), timeout=60)
        borrados.append({"cid": vieja["ipfs_pin_hash"], "http": d.status_code})
    return {"json_nuevo": nuevo, "borrados": borrados}


# ---------- Redes ----------

def publicar_instagram_reel(video_url, caption):
    token = os.environ["INSTAGRAM_ACCESS_TOKEN"].strip()

    r = None
    for intento in range(3):
        try:
            r = requests.post(f"{IG_GRAPH}/{IG_ACCOUNT_ID}/media", timeout=180, data={
                "media_type": "REELS", "video_url": video_url, "caption": caption,
                "share_to_feed": "true", "access_token": token}).json()
            break
        except Exception as e:
            if intento == 2:
                return {"ok": False, "paso": "crear_contenedor", "detalle": f"timeout tras 3 intentos: {e}"}
            time.sleep(15)

    if "id" not in r:
        return {"ok": False, "paso": "crear_contenedor", "detalle": r}
    cid = r["id"]

    for _ in range(60):
        time.sleep(5)
        try:
            st = requests.get(f"{IG_GRAPH}/{cid}", timeout=120, params={
                "fields": "status_code,status", "access_token": token}).json()
        except Exception:
            continue
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            return {"ok": False, "paso": "procesar", "detalle": st}
    else:
        return {"ok": False, "paso": "procesar", "detalle": "Instagram no termino de procesar a tiempo"}

    pub = None
    for intento in range(3):
        try:
            pub = requests.post(f"{IG_GRAPH}/{IG_ACCOUNT_ID}/media_publish", timeout=180, data={
                "creation_id": cid, "access_token": token}).json()
            break
        except Exception as e:
            if intento == 2:
                return {"ok": False, "paso": "publicar", "detalle": f"timeout tras 3 intentos: {e}"}
            time.sleep(15)

    return {"ok": "id" in pub, "detalle": pub}


def publicar_facebook_reel(video_url, caption):
    token = os.environ["FACEBOOK_PAGE_ACCESS_TOKEN_LONG"].strip()
    page = os.environ["FACEBOOK_PAGE_ID"].strip()
    ini = requests.post(f"{FB_GRAPH}/{page}/video_reels", timeout=60, data={
        "upload_phase": "start", "access_token": token}).json()
    if "video_id" not in ini:
        return {"ok": False, "paso": "start", "detalle": ini}
    vid = ini["video_id"]
    up = requests.post(ini["upload_url"], timeout=120, headers={
        "Authorization": f"OAuth {token}", "file_url": video_url}).json()
    if not up.get("success"):
        return {"ok": False, "paso": "upload", "detalle": up}
    for _ in range(24):
        time.sleep(5)
        st = requests.get(f"{FB_GRAPH}/{vid}", timeout=30, params={
            "fields": "status", "access_token": token}).json()
        fase = st.get("status", {}).get("uploading_phase", {}).get("status")
        if fase == "complete":
            break
        if fase == "error":
            return {"ok": False, "paso": "upload", "detalle": st}
    fin = requests.post(f"{FB_GRAPH}/{page}/video_reels", timeout=60, data={
        "upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
        "description": caption, "access_token": token}).json()
    return {"ok": bool(fin.get("success")), "video_id": vid, "detalle": fin}


def publicar_youtube_short(video_url, titulo, descripcion):
    """YouTube no acepta URL: se baja el video a un archivo temporal y se sube."""
    privacidad = os.environ.get("YOUTUBE_PRIVACIDAD", "private").strip()
    tok = requests.post("https://oauth2.googleapis.com/token", timeout=60, data={
        "client_id": os.environ["ID_CLIENT_API_YOUTUBE"].strip(),
        "client_secret": os.environ["SECRET_CLIENT_API_YOUTUBE"].strip(),
        "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"].strip(),
        "grant_type": "refresh_token"}).json()
    if "access_token" not in tok:
        return {"ok": False, "paso": "token", "detalle": tok}

    with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
        with requests.get(video_url, stream=True, timeout=120) as dl:
            dl.raise_for_status()
            for bloque in dl.iter_content(chunk_size=1024 * 1024):
                tmp.write(bloque)
        tmp.flush()
        tam = os.path.getsize(tmp.name)
        meta = {"snippet": {"title": titulo[:100], "description": descripcion, "categoryId": "22"},
                "status": {"privacyStatus": privacidad, "selfDeclaredMadeForKids": False}}
        ini = requests.post(
            "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
            json=meta, timeout=60, headers={
                "Authorization": f"Bearer {tok['access_token']}",
                "X-Upload-Content-Length": str(tam), "X-Upload-Content-Type": "video/mp4"})
        if ini.status_code != 200:
            return {"ok": False, "paso": "iniciar", "detalle": ini.text[:400]}
        res = None
        for intento in range(3):
            try:
                tmp.seek(0)
                res = requests.put(ini.headers["Location"], data=tmp, timeout=600,
                                   headers={"Content-Type": "video/mp4"})
                break
            except requests.exceptions.RequestException as e:
                if intento == 2:
                    return {"ok": False, "paso": "subir", "detalle": f"fallo tras 3 intentos: {e}"}
                time.sleep(10 * (intento + 1))
    datos = res.json() if res.status_code in (200, 201) else {}
    if "id" not in datos:
        return {"ok": False, "paso": "subir", "detalle": res.text[:400]}
    return {"ok": True, "privacidad": privacidad,
            "url": f"https://www.youtube.com/shorts/{datos['id']}"}


def _seguro(fn, *args):
    try:
        return fn(*args)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ---------- Programa ----------

class SinVideo(Exception):
    """No hay un video que publicar (no es un error del programa)."""


def _avance_consola(texto):
    print("-> " + texto)


def publicar_siguiente(publicar=True, avance=_avance_consola):
    """Escoge un video etiquetado distinto al ultimo publicado y lo publica.
    Devuelve un diccionario con el resultado. Con publicar=False solo elige."""
    requeridas = ["PINATA_JWT"]
    if publicar:
        requeridas += ["INSTAGRAM_ACCESS_TOKEN", "FACEBOOK_PAGE_ACCESS_TOKEN_LONG", "FACEBOOK_PAGE_ID",
                       "ID_CLIENT_API_YOUTUBE", "SECRET_CLIENT_API_YOUTUBE", "YOUTUBE_REFRESH_TOKEN"]
    faltan = [v for v in requeridas if not (os.environ.get(v) or "").strip()]
    if faltan:
        raise RuntimeError("faltan variables de entorno: " + ", ".join(faltan))

    filas = _pins()
    videos = _por_tipo(filas, TIPO_VIDEO)
    ultimos = _por_tipo(filas, TIPO_ULTIMO)
    avance(f"Videos etiquetados en Pinata: {len(videos)}")

    ultimo_cid = None
    if ultimos:
        ultimo_cid = _leer_ultimo(ultimos[0])
        avance(f"Ultimo publicado: {ultimo_cid}")
    else:
        avance("Todavia no hay registro de ultimo publicado (primera vez)")

    candidatos = [v for v in videos if v["ipfs_pin_hash"] != ultimo_cid]
    if not candidatos:
        raise SinVideo("No hay un video distinto al ultimo publicado. Crea uno nuevo con crear_video_pinata.py")

    video = random.choice(candidatos)
    cid = video["ipfs_pin_hash"]
    kv = _kv(video)
    frases = [kv[k] for k in ("f1", "f2", "f3") if kv.get(k)]
    if not frases:
        raise SinVideo(f"el video {cid} no tiene frases (f1, f2, f3) en su etiqueta")
    caption = " ".join(frases) + "\n\n" + HASHTAGS
    url = GATEWAY + cid
    avance(f"Video elegido: {url}")
    avance(f"Texto del post:\n{caption}")

    info = {"video_url": url, "texto": caption, "publicado": False}
    if not publicar:
        return info

    avance("Publicando en Instagram Reels")
    info["instagram"] = _seguro(publicar_instagram_reel, url, caption)
    avance("Publicando en Facebook Reels")
    info["facebook"] = _seguro(publicar_facebook_reel, url, caption)
    avance("Publicando en YouTube Shorts")
    info["youtube"] = _seguro(publicar_youtube_short, url, "Manantial de Pueblo #Shorts", caption)

    if any(info[k].get("ok") for k in ("instagram", "facebook", "youtube")):
        avance("Guardando ultimo_publicado en Pinata")
        info["registro"] = _seguro(_guardar_ultimo, cid, ultimos)
        info["publicado"] = True
    else:
        avance("No se publico en ninguna red: no se actualiza ultimo_publicado")
    return info


def main():
    publicar = "--publicar" in sys.argv
    try:
        info = publicar_siguiente(publicar=publicar)
    except (SinVideo, RuntimeError) as e:
        raise SystemExit(str(e))
    if not publicar:
        print("\nPRUEBA: no se publico nada. Agrega --publicar para publicar de verdad.")
        return
    print(json.dumps(info, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
