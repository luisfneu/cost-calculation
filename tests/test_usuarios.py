"""Multiusuário, senha-mestre, auditoria e vendedor na venda."""


def test_login_senha_mestre_define_admin(client):
    # a fixture 'client' já logou com a senha-mestre (APP_SENHA=test)
    r = client.get("/usuarios")  # rota só de admin
    assert r.status_code == 200


def test_criar_usuario_e_login(app, client):
    from app.models import Usuario
    r = client.post("/usuarios/novo", data={
        "nome": "Sabrina", "login": "sabrina", "senha": "1234",
    }, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        u = Usuario.query.filter_by(login="sabrina").first()
        assert u is not None and u.conferir_senha("1234")
        assert u.admin is False

    # login como o novo usuário
    c2 = app.test_client()
    r = c2.post("/login", data={"login": "sabrina", "senha": "1234"}, follow_redirects=True)
    assert r.status_code == 200
    assert c2.get("/").status_code == 200
    # não é admin: gestão de usuários é bloqueada (redireciona)
    assert c2.get("/usuarios", follow_redirects=False).status_code == 302


def test_login_senha_errada_do_usuario(app, client):
    client.post("/usuarios/novo", data={"nome": "X", "login": "x", "senha": "certa"})
    c2 = app.test_client()
    c2.post("/login", data={"login": "x", "senha": "errada"})
    assert c2.get("/", follow_redirects=False).status_code == 302  # não logou


def test_vendedor_gravado_na_venda(client, app, seed):
    pid = seed["peca"]
    client.post("/vendas/nova", data={
        "cliente_id": str(seed["cliente"]),
        "peca_id": [str(pid)], "tamanho": ["P"], "quantidade": ["1"],
        "preco_unitario": ["200"], "desconto": ["0"],
    }, follow_redirects=True)
    from app.models import Venda
    with app.app_context():
        v = Venda.query.first()
        assert v.vendedor == "Admin"  # logado pela senha-mestre


def test_auditoria_registra_login_e_venda(client, app, seed):
    from app.models import Auditoria
    pid = seed["peca"]
    client.post("/vendas/nova", data={
        "peca_id": [str(pid)], "tamanho": ["P"], "quantidade": ["1"],
        "preco_unitario": ["200"], "desconto": ["0"],
    }, follow_redirects=True)
    with app.app_context():
        acoes = {a.acao for a in Auditoria.query.all()}
        assert "login" in acoes
        assert "venda" in acoes
    assert client.get("/auditoria").status_code == 200
