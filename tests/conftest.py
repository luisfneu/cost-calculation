"""Fixtures compartilhadas: app com banco temporário isolado e client logado."""
import os
import tempfile

import pytest


@pytest.fixture()
def app():
    """App Flask apontando para um SQLite temporário (isolado por teste).

    A URI é passada via config_class porque o config.py lê DATABASE_URL só no
    import — mexer em os.environ depois não teria efeito entre testes.
    """
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)

    from config import Config
    from app import create_app

    class TestConfig(Config):
        TESTING = True
        APP_SENHA = "test"
        WTF_CSRF_ENABLED = False  # test client não envia token; CSRF é testado à parte
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + db_path

    application = create_app(TestConfig)

    yield application

    os.remove(db_path)


@pytest.fixture()
def db(app):
    """Sessão do banco dentro do contexto da aplicação."""
    from app.models import db as _db
    with app.app_context():
        yield _db


@pytest.fixture()
def client(app):
    """Client HTTP já autenticado (sessão logada)."""
    c = app.test_client()
    c.post("/login", data={"senha": "test"})
    return c


# ---- helpers de seed reutilizáveis ----
@pytest.fixture()
def seed(app):
    """Cria dados básicos e devolve os ids úteis."""
    from app.models import (
        db, Insumo, Peca, PecaInsumo, EstoquePeca, Cliente,
    )
    ids = {}
    with app.app_context():
        tecido = Insumo(nome="Tecido", unidade="m", custo_unitario=5.0, estoque=100.0)
        linha = Insumo(nome="Linha", unidade="rolo", custo_unitario=3.0, estoque=100.0)
        db.session.add_all([tecido, linha])
        db.session.commit()

        peca = Peca(nome="Vestido Flor", preco_etiqueta=200.0, sku="SH-0001")
        db.session.add(peca)
        db.session.commit()
        db.session.add_all([
            PecaInsumo(peca_id=peca.id, insumo_id=tecido.id, quantidade=2.0),
            PecaInsumo(peca_id=peca.id, insumo_id=linha.id, quantidade=1.0),
            EstoquePeca(peca_id=peca.id, tamanho="P", quantidade=5.0),
            EstoquePeca(peca_id=peca.id, tamanho="M", quantidade=3.0),
        ])
        cliente = Cliente(nome="Ana", telefone="11999998888")
        db.session.add(cliente)
        db.session.commit()

        ids = {
            "peca": peca.id, "tecido": tecido.id, "linha": linha.id,
            "cliente": cliente.id,
        }
    return ids
