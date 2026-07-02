"""Ponto de entrada da aplicação. Rode com: python run.py

HTTPS (para acessar do celular e liberar a câmera do scanner):
  1) gere o certificado uma vez:   ./gerar_cert.sh
  2) rode:                         python run.py
  Se os arquivos em certs/ existirem, o app sobe em HTTPS ligado à rede local
  (0.0.0.0), acessível por https://<ip-do-notebook>:8000 no celular.
  Sem certificado, roda em HTTP no localhost, como antes.
"""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    # Porta configurável (padrão 8000). A 5000 costuma ser interceptada pelo
    # "AirPlay Receiver" do macOS, que devolve 403 no navegador.
    porta = int(os.environ.get("PORT", 8000))

    base = os.path.dirname(os.path.abspath(__file__))
    cert = os.path.join(base, "certs", "cert.pem")
    key = os.path.join(base, "certs", "key.pem")

    if os.path.exists(cert) and os.path.exists(key):
        # HTTPS na rede local: aceite o aviso de certificado uma vez no navegador.
        # threaded=True atende as requisições em paralelo (evita a lentidão de
        # ficar serializando os handshakes TLS de CSS/JS/ícones).
        app.run(host="0.0.0.0", port=porta, debug=True, threaded=True,
                ssl_context=(cert, key))
    else:
        app.run(host="127.0.0.1", port=porta, debug=True, threaded=True)
