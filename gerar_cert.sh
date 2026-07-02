#!/usr/bin/env bash
# Gera um certificado self-signed para rodar o app em HTTPS na rede local.
# Inclui o IP do notebook no SAN, para o celular acessar sem erro de certificado.
# Rode de novo se o IP da rede mudar.  Uso:  ./gerar_cert.sh
set -e
cd "$(dirname "$0")"
mkdir -p certs

IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo 127.0.0.1)"
echo "Gerando certificado para: localhost, 127.0.0.1 e ${IP}"

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout certs/key.pem -out certs/cert.pem -days 825 \
  -subj "/C=BR/O=Sabrina Hansen Atelier/CN=${IP}" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:${IP}" 2>/dev/null

echo "Certificado gerado em certs/. Acesse no celular:  https://${IP}:8000"
