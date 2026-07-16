"""Regressão: pré-pedido órfão de lead descartado, badge de pré-pedidos,
ledger sem entradas de inventário/reabertura, logout do ERP × sessão da vitrine.
"""


def _pedido_vitrine(client, seed, itens=None):
    return client.post("/publico/pedido", json={
        "cliente": {"nome": "Cliente Teste", "telefone": "51999990000"},
        "itens": itens or [{"id": seed["peca"], "tam": "M", "qtd": 1}],
    })


def test_descartar_lead_cancela_pre_pedido(client, app, seed):
    from app.models import Venda
    d = _pedido_vitrine(client, seed).get_json()
    body = client.post(f"/console/erp/leads/{d['lead_id']}/descartar",
                       follow_redirects=True).get_data(as_text=True)
    assert "cancelado" in body
    with app.app_context():
        assert Venda.query.get(d["pedido_id"]) is None    # antes ficava órfão


def test_excluir_lead_cancela_pre_pedido(client, app, seed):
    from app.models import Venda
    d = _pedido_vitrine(client, seed).get_json()
    client.post(f"/console/erp/leads/{d['lead_id']}/excluir", follow_redirects=True)
    with app.app_context():
        assert Venda.query.get(d["pedido_id"]) is None


def test_lead_confirmado_nao_perde_venda_ao_excluir(client, app, seed):
    """Venda já confirmada (status != pre-pedido) não é apagada com o lead."""
    from app.models import Venda
    d = _pedido_vitrine(client, seed).get_json()
    client.post(f"/console/erp/vendas/{d['pedido_id']}/confirmar-pedido", follow_redirects=True)
    client.post(f"/console/erp/leads/{d['lead_id']}/excluir", follow_redirects=True)
    with app.app_context():
        assert Venda.query.get(d["pedido_id"]) is not None


def test_badge_pre_pedidos_no_menu(client, app, seed):
    d = _pedido_vitrine(client, seed).get_json()
    body = client.get("/console/erp/vendas").get_data(as_text=True)
    assert "pré-pedido" in body                       # badge no menu Vendas
    client.post(f"/console/erp/vendas/{d['pedido_id']}/confirmar-pedido", follow_redirects=True)
    body = client.get("/console/erp/vendas").get_data(as_text=True)
    assert "1 pré-pedido" not in body                 # confirmou: badge some


def test_inventario_nao_vira_compra_no_ledger(client, app, seed):
    # Correção de inventário: +10 no estoque do tecido (nenhum dinheiro saiu).
    client.post("/console/erp/estoque/inventario-insumos",
                data={f"cont_{seed['tecido']}": "110"}, follow_redirects=True)
    body = client.get("/console/erp/contabilidade").get_data(as_text=True)
    assert "Inventário (correção)" not in body        # antes: listado como compra


def test_logout_erp_preserva_sessao_da_vitrine(app):
    from app.models import Cliente, db
    with app.app_context():
        c = Cliente(nome="Dona", email="dona@ex.com")
        c.set_senha("Segredo1!")
        db.session.add(c)
        db.session.commit()
        cid = c.id
    cli = app.test_client()
    cli.post("/console/erp/login", data={"senha": "test"})
    with cli.session_transaction() as s:
        s["cliente_id"] = cid                         # logada também na vitrine
    cli.post("/console/erp/logout", follow_redirects=True)
    with cli.session_transaction() as s:
        assert "logado" not in s                      # saiu do ERP
        assert s.get("cliente_id") == cid             # vitrine continua logada
