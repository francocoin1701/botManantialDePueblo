#!/usr/bin/env python3
"""
Generador de contenido para Manantial de Pueblo.
Usa Groq (openai/gpt-oss-120b) para redactar captions de Instagram
y los guarda en contenido/calendario_contenido.jsonl
"""
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRODUCTOS_PATH = os.path.join(BASE_DIR, "contenido", "productos.json")
CALENDARIO_PATH = os.path.join(BASE_DIR, "contenido", "calendario_contenido.jsonl")
ESTADO_PATH = os.path.join(BASE_DIR, "contenido", "estado_rotacion.json")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"

SYSTEM_PROMPT = (
    "Eres el redactor de marketing de Manantial de Pueblo, una marca de agua "
    "potable tratada y envasada en Guaca, Santander, Colombia, con registro "
    "sanitario INVIMA RSA-3628-2026. Escribe en espanol neutro colombiano, "
    "tono cercano, confiable y familiar. NUNCA inventes datos del producto "
    "que no se te den explicitamente (no inventes precios, promesas de salud, "
    "ni caracteristicas). Responde SOLO con el caption final, sin explicaciones "
    "adicionales, sin comillas envolventes, y termina con 3 hashtags relevantes."
)


IMAGENES_DIR = os.path.join(BASE_DIR, "imagenes_productos")


def construir_entrada(producto, caption):
    imagen_rel = producto.get("imagen")
    imagen_path = os.path.join(IMAGENES_DIR, imagen_rel) if imagen_rel else None
    imagen_existe = bool(imagen_path and os.path.exists(imagen_path))
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "producto_id": producto["id"],
        "producto_nombre": producto["nombre"],
        "caption": caption,
        "imagen": imagen_path,
        "imagen_existe": imagen_existe,
        "estado": "borrador",
        "red": "instagram",
    }


def cargar_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def llamar_groq(api_key, producto):
    prompt_usuario = (
        f"Escribe un caption corto para Instagram promocionando: {producto['nombre']}. "
        f"Uso ideal: {producto['uso']}. Maximo 3-4 lineas."
    )
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt_usuario},
        ],
    }
    req = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "curl/8.5.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode("utf-8")
        print(f"ERROR HTTP {e.code} llamando a Groq: {cuerpo}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"ERROR de conexion llamando a Groq: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("ERROR: la variable GROQ_API_KEY no esta cargada en esta sesion.", file=sys.stderr)
        print("Corre primero: export $(grep -v '^#' .env | xargs)", file=sys.stderr)
        sys.exit(1)

    productos = cargar_json(PRODUCTOS_PATH, [])
    if not productos:
        print(f"ERROR: no se encontraron productos en {PRODUCTOS_PATH}", file=sys.stderr)
        sys.exit(1)

    modo_todos = "--todos" in sys.argv

    estado = cargar_json(ESTADO_PATH, {"ultimo_indice": -1})
    generados = []

    if modo_todos:
        objetivo = productos
    else:
        siguiente_indice = (estado["ultimo_indice"] + 1) % len(productos)
        objetivo = [productos[siguiente_indice]]
        estado["ultimo_indice"] = siguiente_indice

    for producto in objetivo:
        print(f"-> Generando caption para: {producto['nombre']} ...")
        caption = llamar_groq(api_key, producto)
        entrada = construir_entrada(producto, caption)
        generados.append(entrada)
        with open(CALENDARIO_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entrada, ensure_ascii=False) + "\n")
        print(f"   OK: {caption}\n")

    guardar_json(ESTADO_PATH, estado)
    print(f"Listo. {len(generados)} entrada(s) guardadas en {CALENDARIO_PATH}")


if __name__ == "__main__":
    main()
