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
threads = int(os.environ.get("THREADS", "8"))
worker_class = "gthread"
timeout = 60
graceful_timeout = 30
accesslog = "-"   # loga acessos no stdout
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

# macOS: evita o abort de "fork safety" do Objective-C quando um worker forkado
# toca em frameworks do sistema (ex.: detecção de proxy via _scproxy). Sem efeito
# em Linux. Rede de segurança — o código de frete já evita o proxy do sistema.
raw_env = ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES"]
