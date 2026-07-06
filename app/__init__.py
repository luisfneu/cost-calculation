"""Application factory."""
import logging
import os
from datetime import UTC
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Flask, g, render_template
from flask_migrate import Migrate
from flask_migrate import upgrade as _alembic_upgrade
from flask_wtf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config

from .extensions import cache, limiter
from .models import Parametro, db

# Versão exibida em /health (útil para saber o que está no ar). Suba a cada release.
APP_VERSION = "1.2.0"

FUSO_PADRAO = "America/Sao_Paulo"


def _fuso_atual():
    """Fuso configurado (Configurações). Cacheado por request para não consultar
    o banco a cada data formatada."""
    tz = getattr(g, "_fuso", None)
    if tz is None:
        try:
            tz = ZoneInfo(Parametro.obter("fuso", FUSO_PADRAO) or FUSO_PADRAO)
        except (ZoneInfoNotFoundError, ValueError):
            tz = ZoneInfo(FUSO_PADRAO)
        g._fuso = tz
    return tz

migrate = Migrate()
csrf = CSRFProtect()

# Diretório das migrações Alembic (raiz do projeto/migrations).
_MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Atrás do Cloudflare Tunnel (1 hop): confia em X-Forwarded-Proto/For/Host
    # para enxergar o esquema real (https), o IP real do cliente (throttling de
    # login) e o host público (url_for). Seguro pois só escuta em 127.0.0.1.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Segredos fracos: avisa sempre; e em produção (PRODUCAO=1) recusa subir.
    _checar_segredos(app)

    # Cache da vitrine pública: em memória do processo (NullCache em testes,
    # para não vazar dados entre requisições/casos).
    app.config.setdefault("CACHE_TYPE", "NullCache" if app.testing else "SimpleCache")
    app.config.setdefault("CACHE_DEFAULT_TIMEOUT", 60)
    cache.init_app(app)

    # Rate-limit nos endpoints públicos (desligado em testes).
    app.config.setdefault("RATELIMIT_ENABLED", not app.testing)
    app.config.setdefault("RATELIMIT_HEADERS_ENABLED", True)
    limiter.init_app(app)

    # Log em arquivo rotativo (além do stdout do Gunicorn). Desligado em testes.
    if not app.testing:
        _configurar_logging(app)

    # Cache-busting: adiciona ?v=<mtime> nas URLs de estáticos (css/js/logo).
    # Quando o arquivo muda, a URL muda e o navegador baixa a versão nova sozinho
    # (não precisa de "hard refresh"). Fotos (uploads/) têm nome único, não versiona.
    @app.url_defaults
    def _static_cache_bust(endpoint, values):
        if endpoint != "static" or "filename" not in values:
            return
        filename = values["filename"]
        if filename.startswith("uploads/"):
            return
        try:
            values["v"] = int(os.stat(os.path.join(app.static_folder, filename)).st_mtime)
        except OSError:
            pass

    # Garante que as pastas necessárias existem.
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    # render_as_batch=True: necessário para ALTER TABLE no SQLite via Alembic.
    migrate.init_app(app, db, directory=_MIGRATIONS_DIR, render_as_batch=True)
    csrf.init_app(app)  # proteção CSRF em todos os POST (token injetado nos forms)

    from .routes import bp, publico_bp
    app.register_blueprint(publico_bp)                     # vitrine + APIs públicas na raiz
    app.register_blueprint(bp, url_prefix="/console/erp")  # ERP (sistema) sob prefixo

    @app.template_filter("moeda")
    def moeda(valor):
        """Formata número no padrão brasileiro: R$ 1.234,56."""
        try:
            texto = f"{float(valor):,.2f}"
        except (TypeError, ValueError):
            texto = "0,00"
        texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {texto}"

    @app.template_filter("dt")
    def dt(valor):
        """Formata data/hora no fuso configurado: dd/mm/aaaa HH:MM.

        Os registros são gravados em UTC; aqui convertemos para o fuso do ateliê
        (Configurações → Fuso horário), padrão America/Sao_Paulo.
        """
        try:
            if valor.tzinfo is None:            # naïve = UTC (como é gravado)
                valor = valor.replace(tzinfo=UTC)
            return valor.astimezone(_fuso_atual()).strftime("%d/%m/%Y %H:%M")
        except (TypeError, ValueError, AttributeError):
            return ""

    @app.template_filter("num")
    def num(valor):
        """Número enxuto: 2 casas, sem zeros à direita desnecessários."""
        try:
            return f"{float(valor):g}"
        except (TypeError, ValueError):
            return valor

    # ----- Páginas de erro amigáveis -----
    @app.errorhandler(404)
    def _erro_404(e):
        return render_template(
            "erro.html", codigo=404, icone="bi-compass",
            titulo="Página não encontrada",
            msg="O endereço que você tentou acessar não existe ou foi movido.",
        ), 404

    @app.errorhandler(413)
    def _erro_413(e):
        return render_template(
            "erro.html", codigo=413, icone="bi-image",
            titulo="Arquivo muito grande",
            msg="O upload passou do limite de 8 MB. Reduza a imagem e tente de novo.",
        ), 413

    @app.errorhandler(500)
    def _erro_500(e):
        db.session.rollback()  # descarta transação possivelmente quebrada
        app.logger.exception("Erro interno não tratado")
        return render_template(
            "erro.html", codigo=500, icone="bi-exclamation-triangle",
            titulo="Algo deu errado",
            msg="Ocorreu um erro interno. Tente novamente; se persistir, verifique os logs.",
        ), 500

    with app.app_context():
        _inicializar_banco(app)

    return app


_SECRETS_FRACOS = {
    "SECRET_KEY": {"", "troque-esta-chave", "troque-esta-chave-em-producao"},
    "APP_SENHA": {"", "atelier"},
}


def _checar_segredos(app):
    """Impede rodar em produção com SECRET_KEY/APP_SENHA no valor padrão."""
    if app.testing:
        return
    fracos = [nome for nome, ruins in _SECRETS_FRACOS.items()
              if str(app.config.get(nome, "")) in ruins]
    if not fracos:
        return
    lista = ", ".join(fracos)
    if os.environ.get("PRODUCAO", "0") == "1":
        raise RuntimeError(
            f"Defina {lista} fortes no .env antes de rodar em produção (PRODUCAO=1)."
        )
    app.logger.warning("⚠️  %s com valor padrão/fraco — troque no .env antes de expor.", lista)


def _configurar_logging(app):
    """Adiciona um handler de arquivo rotativo (além do stdout do servidor).

    Pasta configurável por LOG_DIR (padrão instance/logs). Mantém 5 arquivos de
    até ~1 MB, evitando que o log cresça sem limite.
    """
    # `or` (não `get` com default) para tratar LOG_DIR="" (vazio no .env) como não definido.
    log_dir = os.environ.get("LOG_DIR") or os.path.join(app.instance_path, "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as exc:  # pragma: no cover - ambiente sem permissão de escrita
        app.logger.warning("Não foi possível criar a pasta de logs (%s).", exc)
        return
    handler = RotatingFileHandler(
        os.path.join(log_dir, "app.log"),
        maxBytes=1_000_000, backupCount=5, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    nivel = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    handler.setLevel(nivel)
    app.logger.addHandler(handler)
    app.logger.setLevel(nivel)


def _inicializar_banco(app):
    """Aplica as migrações do Alembic no boot.

    O Alembic é a única fonte de verdade do schema — não há fallback para
    `db.create_all()` (mascararia divergências de migração). Se as migrações
    não existirem, é erro de configuração e a aplicação não deve subir.
    """
    versions = os.path.join(_MIGRATIONS_DIR, "versions")
    if not os.path.isdir(versions):
        raise RuntimeError(
            "Migrações do Alembic ausentes (migrations/versions). "
            "O schema é definido pelo Alembic; rode as migrações antes de subir."
        )
    _alembic_upgrade(directory=_MIGRATIONS_DIR)
