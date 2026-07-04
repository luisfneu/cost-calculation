"""Endpoint /health: público, 200 + versão."""


def test_health_publico_sem_login(app):
    c = app.test_client()  # sem login
    r = c.get("/health")
    assert r.status_code == 200
    dados = r.get_json()
    assert dados["status"] == "ok"
    assert dados["banco"] == "ok"
    assert "version" in dados and dados["version"]


def test_health_reporta_versao(app):
    from app import APP_VERSION
    r = app.test_client().get("/health")
    assert r.get_json()["version"] == APP_VERSION
