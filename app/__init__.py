"""Application factory."""
import os

from flask import Flask
from flask_migrate import Migrate
from flask_migrate import upgrade as _alembic_upgrade
from flask_wtf import CSRFProtect

from config import Config
from .models import db

migrate = Migrate()
csrf = CSRFProtect()

# Diretório das migrações Alembic (raiz do projeto/migrations).
_MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Garante que as pastas necessárias existem.
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    # render_as_batch=True: necessário para ALTER TABLE no SQLite via Alembic.
    migrate.init_app(app, db, directory=_MIGRATIONS_DIR, render_as_batch=True)
    csrf.init_app(app)  # proteção CSRF em todos os POST (token injetado nos forms)

    from .routes import bp
    app.register_blueprint(bp)

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
        """Formata data/hora: dd/mm/aaaa HH:MM."""
        try:
            return valor.strftime("%d/%m/%Y %H:%M")
        except (TypeError, ValueError, AttributeError):
            return ""

    @app.template_filter("num")
    def num(valor):
        """Número enxuto: 2 casas, sem zeros à direita desnecessários."""
        try:
            return f"{float(valor):g}"
        except (TypeError, ValueError):
            return valor

    with app.app_context():
        _inicializar_banco(app)

    return app


def _inicializar_banco(app):
    """Prepara o schema no boot.

    O Alembic é a fonte de verdade do schema (aplica `upgrade`). Se o diretório
    de migrações não existir (ou o Alembic falhar), o fallback é apenas
    `db.create_all()` — cria as tabelas que faltarem a partir dos modelos.
    """
    tem_migracoes = os.path.isdir(os.path.join(_MIGRATIONS_DIR, "versions"))
    if tem_migracoes and app.config.get("USE_ALEMBIC", True):
        try:
            _alembic_upgrade(directory=_MIGRATIONS_DIR)
            return
        except Exception as exc:  # pragma: no cover - salvaguarda de boot
            app.logger.warning("Alembic upgrade falhou (%s); usando create_all().", exc)

    db.create_all()
