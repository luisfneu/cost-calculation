"""Autenticação e rotas públicas."""


def test_exige_login(app):
    c = app.test_client()
    r = c.get("/console/erp/", follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_login_senha_errada(app):
    c = app.test_client()
    c.post("/console/erp/login", data={"senha": "errada"})
    r = c.get("/console/erp/", follow_redirects=False)
    assert r.status_code == 302  # continua deslogado


def test_login_ok(client):
    r = client.get("/console/erp/")
    assert r.status_code == 200


def test_vitrine_publica_sem_login(app):
    c = app.test_client()
    r = c.get("/publico/vitrine")
    assert r.status_code == 200
