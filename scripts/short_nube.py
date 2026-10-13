#!/usr/bin/env python3
"""Short vertical para correr en Render: Groq escribe, edge-tts habla,
ffmpeg arma el video, Pinata lo hospeda y se publica en IG, FB y YouTube."""
import asyncio
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time

import edge_tts
import imageio_ffmpeg
import requests

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import generar_contenido as gen

BASE = os.path.dirname(AQUI)
ESTADO_PATH = os.path.join(BASE, "contenido", "estado_short.json")
CANTIDAD_FOTOS = 3
VOZ = "es-CO-SalomeNeural"
PAUSA = 0.5
ANCHO, ALTO = 720, 1280
FUENTE = os.path.join(AQUI, "fuentes", "LiberationSans-Bold.ttf")
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

IG_ACCOUNT_ID = "29600427372879503"
IG_GRAPH = "https://graph.instagram.com/v26.0"
FB_GRAPH = "https://graph.facebook.com/v26.0"
PINATA_URL = "https://api.pinata.cloud/pinning/pinFileToIPFS"
PINATA_GATEWAY = "https://gateway.pinata.cloud/ipfs/"
HASHTAGS = "#ManantialDePueblo #AguaPotable #Guaca #Santander #Shorts"

SYSTEM_PROMPT = (
    "Eres el locutor de videos cortos de Manantial de Pueblo, una marca de agua "
    "potable tratada y envasada en Guaca, Santander, Colombia. Escribe en espanol "
    "neutro colombiano, tono cercano, confiable y familiar. NUNCA inventes datos del "
    "producto que no se te den explicitamente (no inventes precios, promesas de "
    "salud, ni caracteristicas). Responde SOLO con un arreglo JSON de textos, sin "
    "explicaciones ni formato markdown."
)


def elegir_productos(productos):
    if len(productos) < CANTIDAD_FOTOS:
        raise RuntimeError(f"hacen falta al menos {CANTIDAD_FOTOS} productos")
    estado = gen.cargar_json(ESTADO_PATH, {"ultimo_grupo": []})
    ultimo = set(estado.get("ultimo_grupo", []))
    for _ in range(50):
        grupo = random.sample(productos, CANTIDAD_FOTOS)
        if {p["id"] for p in grupo} != ultimo:
            break
    return grupo


def _extraer_frases(texto, n):
    t = (texto or "").strip()
    i, f = t.find("["), t.rfind("]")
    if i == -1 or f == -1:
        return None
    try:
        datos = json.loads(t[i:f + 1])
    except ValueError:
        return None
    frases = [str(x).strip() for x in datos if str(x).strip()]
    return frases if len(frases) == n else None


def pedir_frases_groq(api_key, grupo):
    n = len(grupo)
    lista = "\n".join(f"{i + 1}. {p['nombre']} (uso: {p['uso']})" for i, p in enumerate(grupo))
    prompt = (
        f"Escribe la narracion de un video vertical corto con {n} fotos de productos, "
        f"en este orden:\n{lista}\n\n"
        f"Devuelve un arreglo JSON con exactamente {n} frases, una por foto y en el mismo "
        "orden. Cada frase: maximo 12 palabras, sin hashtags ni emojis. Escribe los "
        "numeros con letras (por ejemplo 'cuatro litros'). La primera frase debe nombrar "
        "la marca Manantial de Pueblo y la ultima puede cerrar con una invitacion corta. "
        "Deben sonar bien seguidas, como una sola narracion."
    )
    payload = {
        "model": gen.GROQ_MODEL, "temperature": 0.9,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": prompt}],
    }
    for _ in range(3):
        r = requests.post(
            gen.GROQ_URL, json=payload, timeout=60,
            headers={"Authorization": f"Bearer {api_key}", "User-Agent": "curl/8.5.0"},
        )
        if r.status_code != 200:
            raise RuntimeError(f"Groq HTTP {r.status_code}: {r.text[:200]}")
        frases = _extraer_frases(r.json()["choices"][0]["message"]["content"], n)
        if frases:
            return frases
    raise RuntimeError("Groq no devolvio frases validas")


def _duracion(ruta):
    r = subprocess.run([FFMPEG, "-i", ruta], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", r.stderr)
    if not m:
        raise RuntimeError(f"no pude medir la duracion de {ruta}")
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


def _ffmpeg(args):
    r = subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-threads", "1"] + args,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg fallo: " + r.stderr[-500:])


def generar_voz(frases, tmp):
    wavs, duraciones = [], []
    for i, frase in enumerate(frases):
        mp3 = os.path.join(tmp, f"v{i}.mp3")
        wav = os.path.join(tmp, f"v{i}.wav")
        asyncio.run(edge_tts.Communicate(frase, VOZ).save(mp3))
        _ffmpeg(["-i", mp3, "-af", f"apad=pad_dur={PAUSA}", "-ar", "24000", "-ac", "1", wav])
        wavs.append(wav)
        duraciones.append(_duracion(wav))
    lista = os.path.join(tmp, "lista.txt")
    with open(lista, "w") as f:
        f.write("".join(f"file '{w}'\n" for w in wavs))
    voz = os.path.join(tmp, "voz.wav")
    _ffmpeg(["-f", "concat", "-safe", "0", "-i", lista, "-c", "copy", voz])
    return voz, duraciones


def _ruta_imagen(p, tmp, i):
    local = os.path.join(BASE, "imagenes_productos", p["imagen"])
    if os.path.exists(local):
        return local
    destino = os.path.join(tmp, f"img{i}.jpg")
    r = requests.get(p["imagen_pinata_url"], timeout=60, headers={"User-Agent": "curl/8.5.0"})
    r.raise_for_status()
    with open(destino, "wb") as f:
        f.write(r.content)
    return destino


from PIL import Image, ImageDraw, ImageFont


def _png_texto(frase, ruta):
    """Dibuja la frase sobre un PNG transparente del tamano del video."""
    img = Image.new("RGBA", (ANCHO, ALTO), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fuente = ImageFont.truetype(FUENTE, 40)
    texto = textwrap.fill(frase, width=24)
    caja = d.multiline_textbbox((0, 0), texto, font=fuente, spacing=8, align="center")
    tw, th = caja[2] - caja[0], caja[3] - caja[1]
    x, y, pad = (ANCHO - tw) // 2, ALTO - 280, 16
    d.rectangle([x - pad, y - pad, x + tw + pad, y + th + pad], fill=(0, 0, 0, 140))
    d.multiline_text((x - caja[0], y - caja[1]), texto, font=fuente,
                     fill=(255, 255, 255, 255), spacing=8, align="center")
    img.save(ruta)


def armar_video(grupo, frases, voz, duraciones, tmp):
    salida = os.path.join(tmp, "short.mp4")
    n = len(grupo)
    entradas, filtros, etiquetas = [], [], []
    for i, (p, dur) in enumerate(zip(grupo, duraciones)):
        entradas += ["-loop", "1", "-t", f"{dur:.3f}", "-i", _ruta_imagen(p, tmp, i)]
    for i, (frase, dur) in enumerate(zip(frases, duraciones)):
        png = os.path.join(tmp, f"t{i}.png")
        _png_texto(frase, png)
        entradas += ["-loop", "1", "-t", f"{dur:.3f}", "-i", png]
    for i in range(n):
        filtros.append(
            f"[{i}:v]split=2[bg{i}][fg{i}];"
            f"[bg{i}]scale={ANCHO}:{ALTO}:force_original_aspect_ratio=increase,"
            f"crop={ANCHO}:{ALTO},boxblur=20:3[b{i}];"
            f"[fg{i}]scale={ANCHO}:-2[f{i}];"
            f"[b{i}][f{i}]overlay=(W-w)/2:(H-h)/2[m{i}];"
            f"[m{i}][{n + i}:v]overlay=0:0,"
            f"format=yuv420p,setsar=1,fps=30[v{i}]"
        )
        etiquetas.append(f"[v{i}]")
    filtros.append("".join(etiquetas) + f"concat=n={n}:v=1:a=0[out]")
    _ffmpeg(
        entradas + ["-i", voz, "-filter_complex", ";".join(filtros),
                    "-map", "[out]", "-map", f"{2 * n}:a",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                    "-shortest", "-movflags", "+faststart", salida]
    )
    return salida


def subir_pinata(ruta):
    jwt = os.environ["PINATA_JWT"].strip()
    with open(ruta, "rb") as f:
        r = requests.post(PINATA_URL, files={"file": ("short.mp4", f, "video/mp4")},
                          headers={"Authorization": f"Bearer {jwt}"}, timeout=300)
    r.raise_for_status()
    return PINATA_GATEWAY + r.json()["IpfsHash"]


def publicar_instagram_reel(video_url, caption):
    token = os.environ["INSTAGRAM_ACCESS_TOKEN"].strip()

    # 1) Crear contenedor con reintentos (Instagram a veces tarda y da timeout)
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

    # 2) Esperar a que Instagram procese (hasta ~5 min)
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

    # 3) Publicar con reintentos
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


def publicar_youtube_short(ruta, titulo, descripcion):
    privacidad = os.environ.get("YOUTUBE_PRIVACIDAD", "private").strip()
    tok = requests.post("https://oauth2.googleapis.com/token", timeout=60, data={
        "client_id": os.environ["ID_CLIENT_API_YOUTUBE"].strip(),
        "client_secret": os.environ["SECRET_CLIENT_API_YOUTUBE"].strip(),
        "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"].strip(),
        "grant_type": "refresh_token"}).json()
    if "access_token" not in tok:
        return {"ok": False, "paso": "token", "detalle": tok}
    tam = os.path.getsize(ruta)
    meta = {"snippet": {"title": titulo[:100], "description": descripcion, "categoryId": "22"},
            "status": {"privacyStatus": privacidad, "selfDeclaredMadeForKids": False}}
    ini = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        json=meta, timeout=60, headers={
            "Authorization": f"Bearer {tok['access_token']}",
            "X-Upload-Content-Length": str(tam), "X-Upload-Content-Type": "video/mp4"})
    if ini.status_code != 200:
        return {"ok": False, "paso": "iniciar", "detalle": ini.text[:400]}
    with open(ruta, "rb") as f:
        res = requests.put(ini.headers["Location"], data=f, timeout=600,
                           headers={"Content-Type": "video/mp4"})
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


def crear_y_publicar(avance=lambda t: None, publicar=True):
    api_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("falta GROQ_API_KEY")
    if not os.path.exists(FUENTE):
        raise RuntimeError(f"falta la fuente {FUENTE}")

    tmp = tempfile.mkdtemp(prefix="short_")
    try:
        avance("Eligiendo fotos")
        grupo = elegir_productos(gen.cargar_json(gen.PRODUCTOS_PATH, []))
        avance("Escribiendo la narracion (Groq)")
        frases = pedir_frases_groq(api_key, grupo)
        avance("Generando la voz")
        voz, duraciones = generar_voz(frases, tmp)
        avance("Armando el video (puede tardar unos minutos)")
        video = armar_video(grupo, frases, voz, duraciones, tmp)
        gen.guardar_json(ESTADO_PATH, {"ultimo_grupo": [p["id"] for p in grupo]})

        info = {"productos": [p["id"] for p in grupo], "frases": frases}
        if not publicar:
            shutil.copy(video, "/tmp/short_nube.mp4")
            info["video"] = "/tmp/short_nube.mp4"
            return info

        caption = " ".join(frases) + "\n\n" + HASHTAGS
        avance("Subiendo el video a Pinata")
        info["video_url"] = video_url = subir_pinata(video)
        avance("Publicando en Instagram Reels")
        info["instagram"] = _seguro(publicar_instagram_reel, video_url, caption)
        avance("Publicando en Facebook Reels")
        info["facebook"] = _seguro(publicar_facebook_reel, video_url, caption)
        avance("Publicando en YouTube Shorts")
        info["youtube"] = _seguro(publicar_youtube_short, video,
                                  "Manantial de Pueblo #Shorts", caption)
        info["ok"] = all(info[k].get("ok") for k in ("instagram", "facebook", "youtube"))
        return info
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    publicar = "--publicar" in sys.argv
    print(json.dumps(crear_y_publicar(lambda t: print("->", t), publicar=publicar),
                     ensure_ascii=False, indent=2))
