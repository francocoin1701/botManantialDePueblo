Paso 1: crear el contenedor. Esto todavía no publica, solo devuelve un ID:

```bash
set -a; source .env; set +a; curl -s -X POST "https://graph.instagram.com/v26.0/29600427372879503/media" --data-urlencode "image_url=https://gateway.pinata.cloud/ipfs/bafybeiev7wmqr24ukaaa6ft43tomd77iaitn6wtilmjrllu633v6lmsa3u" --data-urlencode "caption=prueba 2" --data-urlencode "access_token=$INSTAGRAM_ACCESS_TOKEN" | python3 -m json.tool

```
luego con el id que este comando nos entrega que es el de el contenedor lo usamos para publicar con el siguiente comando 

```bash
curl -s -X POST -H "Content-Type: application/json" -d '{"caption":"prueba 3"}' http://127.0.0.1:5001/publicar_instagram | python3 -m json.tool
```

comando para inicializar todo el ciclo de forma manual con instagram y n8n desde la creacion hasta la publicacion se nesecita el servidor corriendo en el puerto 5001 ...

```bash
docker exec n8n n8n execute --id=manantialPublicarPrueba1 2>&1 | grep -v -E "Permissions 0644|Error tracking|punycode|trace-deprecation"
```

