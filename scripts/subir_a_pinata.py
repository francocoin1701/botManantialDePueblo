#!/usr/bin/env python3
"""Sube las imágenes de producto a Pinata y guarda sus URLs en productos.json"""
import json
import os
import sys
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRODUCTOS_PATH = os.path.join(BASE_DIR, "contenido", "productos.json")
IMAGENES_DIR = os.path.join(BASE_DIR, "imagenes_productos")
PINATA_URL = "https://api.pinata.cloud/pinning/pinFileToIPFS"
PINATA_GATEWAY = "https://gateway.pinata.cloud/ipfs/"


def subir(imagen_path, jwt):
    with open(imagen_path, "rb") as f:
        files = {"file": (os.path.basename(imagen_path), f, "image/jpeg")}
        resp = requests.post(
            PINATA_URL, files=files,
            headers={"Authorization": f"Bearer {jwt}"}, timeout=60,
        )
    resp.raise_for_status()
    cid = resp.json()["IpfsHash"]
    return PINATA_GATEWAY + cid


def main():
    jwt = os.environ.get("PINATA_JWT")
    if not jwt:
        print("ERROR: falta PINATA_JWT en el entorno")
        sys.exit(1)

    with open(PRODUCTOS_PATH, "r", encoding="utf-8") as f:
        productos = json.load(f)

    for p in productos:
        if p.get("imagen_pinata_url"):
            print(f"-> {p['nombre']}: ya tiene URL, se omite")
            continue
        ruta = os.path.join(IMAGENES_DIR, p["imagen"])
        print(f"-> Subiendo {p['imagen']} ...")
        url = subir(ruta, jwt)
        p["imagen_pinata_url"] = url
        print(f"   OK: {url}")

    with open(PRODUCTOS_PATH, "w", encoding="utf-8") as f:
        json.dump(productos, f, ensure_ascii=False, indent=2)

    print("\n✓ productos.json actualizado con todas las URLs")


if __name__ == "__main__":
    main()
