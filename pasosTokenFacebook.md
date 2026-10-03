Aquí está el proceso completo, limpio, para repetirlo cuando lo necesites (guárdalo, te va a servir cada vez que el token expire):

## Checklist: generar token de Facebook de larga duración

### 1. Consigue el App Secret y App ID (solo la primera vez, ya no cambia)
- developers.facebook.com → tu app → **Configuración → Básica**
- Copia **"Clave secreta de la app"**
- Guarda en `.env`:
```
FACEBOOK_APP_ID=1402760974839725
FACEBOOK_APP_SECRET=tu_clave_secreta
```

### 2. Genera un token de usuario corto desde el Explorador
- Ve a **developers.facebook.com/tools/explorer/**
- Selecciona tu app arriba a la derecha
- "Usuario o página" → **"Token del usuario"**
- Marca permisos: `pages_show_list`, `business_management`, `pages_read_engagement`, `pages_manage_posts`
- Clic en **"Generate Access Token"** → acepta
- Copia el token y guárdalo:
```
FACEBOOK_USER_ACCESS_TOKEN=el_token_corto
```

### 3. Intercambia por uno de larga duración (60 días)
```bash
export $(grep -v '^#' .env | xargs)
curl -s "https://graph.facebook.com/v26.0/oauth/access_token?grant_type=fb_exchange_token&client_id=${FACEBOOK_APP_ID}&client_secret=${FACEBOOK_APP_SECRET}&fb_exchange_token=${FACEBOOK_USER_ACCESS_TOKEN}" | python3 -m json.tool
```
Guarda el `access_token` que te devuelva:
```
FACEBOOK_USER_ACCESS_TOKEN_LONG=el_token_largo
```

### 4. Saca el token de PÁGINA (este es el que no expira)
```bash
export $(grep -v '^#' .env | xargs)
curl -s "https://graph.facebook.com/v26.0/me/accounts?fields=id,name,access_token&access_token=${FACEBOOK_USER_ACCESS_TOKEN_LONG}" | python3 -m json.tool
```
Del resultado, guarda el `access_token` que aparece junto a "Manantial de pueblo":
```
FACEBOOK_PAGE_ACCESS_TOKEN=el_token_de_pagina
FACEBOOK_PAGE_ID=1399596943232047
```

### 5. Prueba que funciona (publicación de solo texto)
```bash
export $(grep -v '^#' .env | xargs)
curl -s -X POST "https://graph.facebook.com/v26.0/${FACEBOOK_PAGE_ID}/feed" \
  -F "message=Prueba de token nuevo" \
  -F "access_token=${FACEBOOK_PAGE_ACCESS_TOKEN}" \
  | python3 -m json.tool
```
Si devuelve un `id`, el token de página quedó bien.

---

Este es el proceso completo que ya hicimos hoy — guárdalo como referencia. Cuando quieras, seguimos con lo de Instagram.

comando para saber la expiracion de un token en facebook 
```bash
export $(grep -v '^#' .env | xargs)
curl -s "https://graph.facebook.com/v26.0/debug_token?input_token=${FACEBOOK_PAGE_ACCESS_TOKEN_LONG}&access_token=${FACEBOOK_PAGE_ACCESS_TOKEN_LONG}" | python3 -m json.tool
```

comando para instagram distinto al de facebook
```bash
export $(grep -v '^#' .env | xargs)
curl -s "https://graph.instagram.com/v26.0/me?fields=id,username&access_token=${INSTAGRAM_ACCESS_TOKEN}" | python3 -m json.tool
```