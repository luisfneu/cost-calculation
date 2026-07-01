"""Ponto de entrada da aplicação. Rode com: python run.py"""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    # Porta configurável (padrão 8000). A 5000 costuma ser interceptada pelo
    # "AirPlay Receiver" do macOS, que devolve 403 no navegador.
    porta = int(os.environ.get("PORT", 8000))
    app.run(host="127.0.0.1", port=porta, debug=True)
