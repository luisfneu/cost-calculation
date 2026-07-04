"""Configuração do Gunicorn (servidor de produção).

O Cloudflare Tunnel acessa este endereço local em HTTP; o HTTPS é feito pela
Cloudflare na borda. Por isso NÃO usamos certificado aqui.

SQLite gosta de um único processo escrevendo: usamos 1 worker com várias threads
(evita "database is locked" entre processos). Para um ateliê com poucos acessos
simultâneos é o ideal.
"""
import os

bind = os.environ.get("BIND", "127.0.0.1:8000")
workers = 1
threads = int(os.environ.get("THREADS", "4"))
worker_class = "gthread"
timeout = 60
graceful_timeout = 30
accesslog = "-"   # loga acessos no stdout
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")
