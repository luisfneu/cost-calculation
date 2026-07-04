"""Entrada WSGI para produção (Gunicorn).

Rode com:
    gunicorn -c gunicorn.conf.py wsgi:app

O Cloudflare Tunnel conecta no endereço local (127.0.0.1:8000) e cuida do HTTPS.
"""
from app import create_app

app = create_app()
