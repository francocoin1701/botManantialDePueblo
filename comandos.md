PARA AGREGAR ALGO A GITIGNORE
echo ".env" >> .gitignore

PARA CARGAR LAS VARIABLES DE .ENV EN LA SECION ACTUAL DE LA TERMINAL
export $(grep -v '^#' .env | xargs)
echo "✓ Clave cargada: ${GROQ_API_KEY:0:8}..." # solo muestra los primeros 8 caracteres, por seguridad

PARA VER LA LISTA DE MODELOS DISPONIBLES CON GORQ
curl -s https://api.groq.com/openai/v1/models \
  -H "Authorization: Bearer $GROQ_API_KEY" | python3 -m json.tool

PARA VER SI LA API DE GROQ FUNCIONA 
curl -s https://api.groq.com/openai/v1/chat/completions \
  -H "Authorization: Bearer $GROQ_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-oss-120b",
    "messages": [{"role": "user", "content": "di hola en una palabra"}]
  }' | python3 -m json.tool