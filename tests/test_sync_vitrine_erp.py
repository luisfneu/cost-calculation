"""Regressão: sincronização vitrine ↔ ERP — invalidação seletiva do cache,
reserva de estoque no pré-pedido e favoritos persistidos na conta.
"""


def _pedido_vitrine(client, seed, itens):
    return client.post("/publico/pedido", json={
        "cliente": {"nome": "Cliente Teste", "telefone": "51999990000"},
        "itens": itens,
    })


def _reservado(app, peca_id, tam):
    from app.models import EstoquePeca
    with app.app_context():
        linha = EstoquePeca.query.filter_by(peca_id=peca_id, tamanho=tam).first()
        return linha.reservado if linha else 0.0


# ---------------- cache seletivo ----------------
def test_cache_invalida_so_com_mudanca_de_vitrine(app, seed, monkeypatch):
    from app.models import Auditoria, Peca, db
    chamadas = []
    monkeypatch.setattr("app.routes.helpers._limpar_cache_vitrine",
                        lambda: chamadas.append(1))
    with app.app_context():
        # Commit que NÃO toca a vitrine (auditoria — ex.: login de cliente).
        db.session.add(Auditoria(usuario="x", acao="login"))
        db.session.commit()
        assert chamadas == []                      # antes: limpava em todo commit
        # Commit que toca a vitrine (preço da peça).
        Peca.query.get(seed["peca"]).preco_etiqueta = 250.0
        db.session.commit()
        assert chamadas == [1]


# ---------------- reserva no pré-pedido ----------------
def test_pre_pedido_reserva_estoque(client, app, seed):
    _pedido_vitrine(client, seed, [{"id": seed["peca"], "tam": "M", "qtd": 2}])
    assert _reservado(app, seed["peca"], "M") == 2.0
    with app.app_context():
        from app.models import Peca
        # Disponível cai para 1 (3 − 2 reservadas) na vitrine e no balcão.
        assert Peca.query.get(seed["peca"]).disponivel_por_tamanho["M"] == 1.0


def test_balcao_nao_vende_estoque_reservado(client, app, seed):
    from app.models import Venda
    _pedido_vitrine(client, seed, [{"id": seed["peca"], "tam": "M", "qtd": 2}])
    body = client.post("/console/erp/vendas/nova", data={
        "peca_id": [str(seed["peca"])], "tamanho": ["M"], "quantidade": ["2"],
        "preco_unitario": ["200"], "desconto": [""], "frete": "", "desconto_total": "",
    }, follow_redirects=True).get_data(as_text=True)
    assert "Estoque insuficiente" in body          # só 1 disponível (2 reservadas)
    with app.app_context():
        assert Venda.query.filter_by(tipo="venda", status="realizado").count() == 0


def test_confirmar_libera_reserva_e_baixa(client, app, seed):
    from app.models import EstoquePeca
    d = _pedido_vitrine(client, seed, [{"id": seed["peca"], "tam": "M", "qtd": 2}]).get_json()
    client.post(f"/console/erp/vendas/{d['pedido_id']}/confirmar-pedido", follow_redirects=True)
    with app.app_context():
        linha = EstoquePeca.query.filter_by(peca_id=seed["peca"], tamanho="M").first()
        assert linha.reservado == 0.0              # reserva liberada
        assert linha.quantidade == 1.0             # baixa efetivada (3−2)


def test_descartar_lead_libera_reserva(client, app, seed):
    d = _pedido_vitrine(client, seed, [{"id": seed["peca"], "tam": "M", "qtd": 2}]).get_json()
    assert _reservado(app, seed["peca"], "M") == 2.0
    client.post(f"/console/erp/leads/{d['lead_id']}/descartar", follow_redirects=True)
    assert _reservado(app, seed["peca"], "M") == 0.0


def test_excluir_pre_pedido_libera_reserva(client, app, seed):
    d = _pedido_vitrine(client, seed, [{"id": seed["peca"], "tam": "M", "qtd": 2}]).get_json()
    client.post(f"/console/erp/vendas/{d['pedido_id']}/excluir", follow_redirects=True)
    assert _reservado(app, seed["peca"], "M") == 0.0


# ---------------- favoritos na conta ----------------
def _cliente_logado(app):
    from app.models import Cliente, db
    with app.app_context():
        c = Cliente(nome="Fa Vorita", email="fa@ex.com", telefone="51911110000")
        c.set_senha("Segredo1!")
        db.session.add(c)
        db.session.commit()
        cid = c.id
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["cliente_id"] = cid
    return cli, cid


def test_favoritos_sync_merge_e_replace(app, seed):
    from app.models import Cliente
    cli, cid = _cliente_logado(app)
    # merge: aparelho traz [peca]; conta vazia → conta = [peca].
    r = cli.post("/conta/favoritos/sync", json={"ids": [seed["peca"]], "modo": "merge"})
    assert r.get_json()["ids"] == [seed["peca"]]
    # merge em outro aparelho sem nada local → recebe o favorito da conta.
    r = cli.post("/conta/favoritos/sync", json={"ids": [], "modo": "merge"})
    assert r.get_json()["ids"] == [seed["peca"]]
    # replace: removeu no aparelho → conta esvazia.
    r = cli.post("/conta/favoritos/sync", json={"ids": [], "modo": "replace"})
    assert r.get_json()["ids"] == []
    with app.app_context():
        assert Cliente.query.get(cid).favoritos_ids == []


def test_favoritos_sync_exige_login(app):
    cli = app.test_client()
    assert cli.post("/conta/favoritos/sync", json={"ids": [1]}).status_code == 401
