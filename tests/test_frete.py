"""Frete público da vitrine (/publico/frete)."""


def test_frete_publico_sem_login_e_carrinho_vazio(app):
    c = app.test_client()  # sem login: endpoint é público
    r = c.post("/publico/frete", json={"cep": "01310100", "itens": []})
    assert r.status_code == 400
    assert "vazio" in r.get_json()["erro"].lower()


def test_frete_publico_calcula(client, app, seed, monkeypatch):
    # Evita a chamada externa ao Melhor Envio: substitui o helper por um retorno fixo.
    def fake(cep, peso_g=0, altura_cm=0, largura_cm=0, comprimento_cm=0, valor_seguro=0):
        assert peso_g >= 0  # dimensões vieram somadas do banco
        assert valor_seguro > 0  # sempre segura pelo valor do carrinho
        return ([{"nome": "SEDEX", "preco": "34.60", "prazo": 2, "rapido": True},
                 {"nome": "PAC", "preco": "17.50", "prazo": 6}], None)
    monkeypatch.setattr("app.routes.catalogo._frete_opcoes", fake)

    r = client.post("/publico/frete", json={
        "cep": "01310-100", "itens": [{"id": seed["peca"], "qtd": 2}],
    })
    assert r.status_code == 200
    dados = r.get_json()
    assert dados["ok"] is True
    assert len(dados["opcoes"]) == 2
    assert dados["opcoes"][0]["nome"] == "SEDEX"


def test_frete_publico_erro_config(client, app, seed, monkeypatch):
    def fake(*a, **k):
        return ([], "Frete não configurado. Defina MELHOR_ENVIO_TOKEN e CEP_ORIGEM.")
    monkeypatch.setattr("app.routes.catalogo._frete_opcoes", fake)
    r = client.post("/publico/frete", json={"cep": "01310100", "itens": [{"id": seed["peca"], "qtd": 1}]})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_cupom_publico_geral_aplica(client, app):
    from app.models import Cupom, db
    with app.app_context():
        db.session.add(Cupom(codigo="VITRINE10", tipo="percentual", valor=10, ativo=True))
        db.session.commit()
    r = client.post("/publico/cupom", json={"codigo": "vitrine10", "subtotal": 200})
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True
    assert d["desconto"] == 20.0   # 10% de 200


def test_cupom_publico_invalido(client, app):
    r = client.post("/publico/cupom", json={"codigo": "NAOEXISTE", "subtotal": 100})
    assert r.get_json()["ok"] is False


def test_cupom_publico_pessoal_nao_aplica(client, app):
    from app.models import Cliente, Cupom, db
    with app.app_context():
        cli = Cliente(nome="Dona")
        db.session.add(cli)
        db.session.flush()
        db.session.add(Cupom(codigo="NIVER5", tipo="valor", valor=5, ativo=True, cliente_id=cli.id))
        db.session.commit()
    r = client.post("/publico/cupom", json={"codigo": "NIVER5", "subtotal": 100})
    d = r.get_json()
    assert d["ok"] is False and d.get("pessoal") is True
