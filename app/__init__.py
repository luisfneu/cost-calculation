"""Application factory."""
import os

from flask import Flask

from config import Config
from .models import db


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Garante que as pastas necessárias existem.
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)

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
        db.create_all()

    return app
