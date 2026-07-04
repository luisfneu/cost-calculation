"""Editar venda reusa a tela de venda e preserva pagamentos/estoque."""


def _cria_venda(client, seed, qtd=2):
    client.post("/vendas/nova", data={
        "cliente_id": str(seed["cliente"]),
        "peca_id": [str(seed["peca"])], "tamanho": ["P"], "quantidade": [str(qtd)],
        "preco_unitario": ["200"], "desconto": ["0"],
    }, follow_redirects=True)
    from flask import current_app

    from app.models import Venda
    with current_app.app_context():
        return Venda.query.order_by(Venda.id.desc()).first().id


def test_get_edicao_usa_tela_de_venda(client, app, seed):
    with app.app_context():
        vid = _cria_venda(client, seed)
    body = client.get(f"/vendas/{vid}/editar").get_data(as_text=True)
    assert f"Editar pedido #{vid}" in body
    assert "Salvar alterações" in body
    assert "peca-picker" in body          # mesmo seletor de peça com foto da venda
    assert "prefill-itens" in body


def test_edicao_ajusta_estoque_e_preserva_pagamento(client, app, seed):
    from app.models import Pagamento, Venda
    with app.app_context():
        vid = _cria_venda(client, seed, qtd=2)   # P: 5 -> 3
        v = Venda.query.get(vid)
        v.pagamentos.append(Pagamento(forma="Pix", valor=400))
        v.pago = True
        from app.models import db
        db.session.commit()

    # edita para 1 unidade
    client.post(f"/vendas/{vid}/editar", data={
        "peca_id": [str(seed["peca"])], "tamanho": ["P"], "quantidade": ["1"],
        "preco_unitario": ["200"], "desconto": ["0"],
        "frete": "", "marketplace_pct": "", "desconto_total": "",
    }, follow_redirects=True)

    from app.models import Peca
    with app.app_context():
        v = Venda.query.get(vid)
        assert v.quantidade_total == 1
        # devolveu 1 ao estoque: 3 -> 4
        assert Peca.query.get(seed["peca"]).estoque_por_tamanho["P"] == 4
        # pagamento NÃO foi apagado
        assert len(v.pagamentos) == 1
        assert v.total_pago == 400
        assert v.pago is True


def test_edicao_bloqueia_sem_itens(client, app, seed):
    with app.app_context():
        vid = _cria_venda(client, seed)
    r = client.post(f"/vendas/{vid}/editar", data={
        "peca_id": [""], "tamanho": [""], "quantidade": [""],
        "preco_unitario": [""], "desconto": [""],
    }, follow_redirects=True)
    assert r.status_code == 200
    assert "Adicione ao menos um item" in r.get_data(as_text=True)
