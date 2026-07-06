"""Kits/combos e fluxo básico de venda com baixa de estoque."""


def test_kit_crud_e_preco_normal(client, app, seed):
    from app.models import Kit
    pid = seed["peca"]
    client.post("/console/erp/kits/novo", data={
        "nome": "Combo", "preco": "300",
        "peca_id": [str(pid)], "quantidade": ["2"],
    }, follow_redirects=True)
    with app.app_context():
        kit = Kit.query.filter_by(nome="Combo").first()
        assert kit is not None
        assert kit.preco == 300.0
        # 2 x preço efetivo (200) = 400
        assert kit.preco_normal == 400.0


def test_venda_baixa_estoque(client, app, seed):
    from app.models import Peca, Venda
    pid = seed["peca"]  # P = 5
    r = client.post("/console/erp/vendas/nova", data={
        "cliente_id": str(seed["cliente"]),
        "peca_id": [str(pid)], "tamanho": ["P"], "quantidade": ["2"],
        "preco_unitario": ["200"], "desconto": ["0"],
    }, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        assert Peca.query.get(pid).estoque_por_tamanho["P"] == 3.0  # 5 - 2
        assert Venda.query.count() == 1
