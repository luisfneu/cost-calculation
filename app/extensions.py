"""Extensões compartilhadas (evita import circular entre app e rotas).

- cache: cache em memória do processo (Flask-Caching). Usado na vitrine pública,
  que é pesada de montar e não muda a cada segundo.
- limiter: rate-limit por IP (Flask-Limiter) nos endpoints públicos (login e
  vitrine), para conter abuso/brute-force. Armazenamento em memória — combina
  com o deploy de 1 worker do Gunicorn.
"""
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

cache = Cache()

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",
    strategy="fixed-window",
)
