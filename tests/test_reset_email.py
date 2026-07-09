"""Reset de senha por e-mail: token assinado + fluxo esqueci/redefinir.
O envio real é substituído por um mock (não bate na rede)."""


def test_token_roundtrip_e_expira(app):
    from app.emails import gerar_token_reset, ler_token_reset
    with app.app_context():
        tok = gerar_token_reset(42)
        assert ler_token_reset(tok) == 42
        assert ler_token_reset(tok + "x") is None        # adulterado
        assert ler_token_reset("lixo") is None           # inválido
        assert ler_token_reset(tok, max_age=-1) is None   # expirado


def test_esqueci_envia_link_para_conta_existente(app, monkeypatch):
    from app.models import Cliente, db
    enviados = []
    monkeypatch.setattr("app.routes.conta.enviar_email",
                        lambda destino, assunto, html: enviados.append((destino, html)) or True)
    with app.app_context():
        c = Cliente(nome="Ana", email="ana@ex.com", telefone="51999998888")
        c.set_senha("antiga1")
        db.session.add(c); db.session.commit()

    cli = app.test_client()
    r = cli.post("/conta/esqueci", data={"email": "ana@ex.com"})
    assert r.status_code == 302
    assert len(enviados) == 1 and enviados[0][0] == "ana@ex.com"
    assert "/conta/redefinir/" in enviados[0][1]          # link no corpo do e-mail


def test_esqueci_email_desconhecido_nao_envia_nem_vaza(app, monkeypatch):
    enviados = []
    monkeypatch.setattr("app.routes.conta.enviar_email",
                        lambda *a, **k: enviados.append(a) or True)
    cli = app.test_client()
    r = cli.post("/conta/esqueci", data={"email": "ninguem@ex.com"}, follow_redirects=True)
    assert r.status_code == 200
    assert enviados == []                                  # nada enviado
    assert "enviamos um link" in r.get_data(as_text=True)  # resposta genérica


def test_redefinir_com_token_valido_troca_senha(app):
    from app.emails import gerar_token_reset
    from app.models import Cliente, db
    with app.app_context():
        c = Cliente(nome="Bea", email="bea@ex.com", telefone="51988887777")
        c.set_senha("antiga1")
        db.session.add(c); db.session.commit()
        cid = c.id
        token = gerar_token_reset(cid)

    cli = app.test_client()
    assert cli.get(f"/conta/redefinir/{token}").status_code == 200
    cli.post(f"/conta/redefinir/{token}", data={"senha": "novasenha9"})
    with app.app_context():
        c = Cliente.query.get(cid)
        assert c.conferir_senha("novasenha9")
        assert not c.conferir_senha("antiga1")


def test_redefinir_token_invalido_redireciona(app):
    cli = app.test_client()
    r = cli.get("/conta/redefinir/tokenfalso")
    assert r.status_code == 302 and "/conta/esqueci" in r.headers["Location"]
