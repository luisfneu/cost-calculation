"""Configuração central da aplicação."""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # Chave usada por sessões e mensagens flash. Em produção, use variável de ambiente.
    SECRET_KEY = os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao")

    # Banco SQLite salvo na pasta instance/ (criada automaticamente pelo Flask).
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'costcalc.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Upload de fotos
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "app", "static", "uploads")
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # 8 MB por upload
