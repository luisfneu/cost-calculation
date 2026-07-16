"""Reset de senha por e-mail: token assinado + fluxo esqueci/redefinir.
O envio real é substituído por um mock (não bate na rede)."""


class _ClienteFake:
    def __init__(self, cid=42, senha_hash="hash-x"):
        self.id = cid
        self.senha_hash = senha_hash


def test_token_roundtrip_e_expira(app):
    from app.emails import gerar_token_reset, ler_token_reset, token_confere_com
    with app.app_context():
        cliente = _ClienteFake()
        tok = gerar_token_reset(cliente)
        cid, versao = ler_token_reset(tok)
        assert cid == 42 and token_confere_com(cliente, versao)
        assert ler_token_reset(tok + "x") == (None, None)        # adulterado
        assert ler_token_reset("lixo") == (None, None)           # inválido
        assert ler_token_reset(tok, max_age=-1) == (None, None)  # expirado
        # Trocou a senha: a versão do token antigo deixa de conferir.
        cliente.senha_hash = "hash-novo"
        assert not token_confere_com(cliente, versao)


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
        token = gerar_token_reset(c)

    cli = app.test_client()
    assert cli.get(f"/conta/redefinir/{token}").status_code == 200
    cli.post(f"/conta/redefinir/{token}", data={"senha": "Novasenha9!"})
    with app.app_context():
        c = Cliente.query.get(cid)
        assert c.conferir_senha("Novasenha9!")
        assert not c.conferir_senha("antiga1")


def test_redefinir_token_invalido_redireciona(app):
    cli = app.test_client()
    r = cli.get("/conta/redefinir/tokenfalso")
    assert r.status_code == 302 and "login=1" in r.headers["Location"]
