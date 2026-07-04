"""CSRF: com a proteção ligada, POST sem token é rejeitado."""
import os
import tempfile

import pytest


@pytest.fixture()
def app_csrf():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    from app import create_app
    from config import Config

    class Cfg(Config):
        TESTING = True
        APP_SENHA = "test"
        WTF_CSRF_ENABLED = True   # liga o CSRF (ao contrário do restante dos testes)
        SECRET_KEY = "csrf-test"
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + db_path

    yield create_app(Cfg)
    os.remove(db_path)


def test_login_tem_token(app_csrf):
    body = app_csrf.test_client().get("/login").get_data(as_text=True)
    assert 'name="csrf_token"' in body


def test_post_sem_token_bloqueado(app_csrf):
    r = app_csrf.test_client().post("/login", data={"senha": "test"})
    assert r.status_code == 400  # CSRF ausente → rejeitado


def test_meta_token_nas_paginas(app_csrf):
    c = app_csrf.test_client()
    # loga direto marcando a sessão (sem passar pelo form protegido)
    with c.session_transaction() as s:
        s["logado"] = True
        s["usuario"] = "Admin"
        s["admin"] = True
    body = c.get("/").get_data(as_text=True)
    assert 'name="csrf-token"' in body   # meta usada pelo JS que injeta o token
