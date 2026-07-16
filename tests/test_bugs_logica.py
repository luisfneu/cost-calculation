"""Regressão: bugs de lógica — usos do cupom na vitrine, revalidação de estoque
na confirmação, preço cheio vs sinal da encomenda, tamanho inválido, snapshot
de custo na edição, devolução × pago, _to_float com milhar, pagamento em
pré-pedido.
"""


def _pedido_vitrine(client, seed, itens, cupom=None):
    payload = {
        "cliente": {"nome": "Cliente Teste", "telefone": "51999990000"},
        "itens": itens,
    }
    if cupom:
        payload["cupom"] = {"codigo": cupom}
    return client.post("/publico/pedido", json=payload)


def test_cupom_conta_uso_ao_confirmar_pedido(client, app, seed):
    from app.models import Cupom, db
    with app.app_context():
        db.session.add(Cupom(codigo="UMAVEZ", tipo="percentual", valor=10.0,
                             ativo=True, max_usos=1))
        db.session.commit()
    d = _pedido_vitrine(client, seed, [{"id": seed["peca"], "tam": "M", "qtd": 1}],
                        cupom="UMAVEZ").get_json()
    with app.app_context():
        assert Cupom.query.filter_by(codigo="UMAVEZ").first().usos == 0  # pré-pedido não queima
    client.post(f"/console/erp/vendas/{d['pedido_id']}/confirmar-pedido", follow_redirects=True)
    with app.app_context():
        cupom = Cupom.query.filter_by(codigo="UMAVEZ").first()
        assert cupom.usos == 1                      # antes: nunca incrementava
        assert cupom.valido is False                # max_usos atingido
    # Próximo pedido com o mesmo cupom: sem desconto.
    r2 = _pedido_vitrine(client, seed, [{"id": seed["peca"], "tam": "M", "qtd": 1}],
                         cupom="UMAVEZ").get_json()
    from app.models import Venda
    with app.app_context():
        assert Venda.query.get(r2["pedido_id"]).desconto_total == 0.0


def test_confirmar_pedido_revalida_estoque(client, app, seed):
    """Estoque M=3. Pré-pedido de 2; balcão vende 2 antes da confirmação.
    Confirmar não pode deixar o estoque negativo — o item vira 'produzir'.

    Zera a reserva na mão para simular um pré-pedido LEGADO (criado antes da
    reserva automática) — hoje a reserva impede a corrida na origem, e este
    teste garante a rede de segurança da revalidação."""
    from app.models import EstoquePeca, Venda, db
    d = _pedido_vitrine(client, seed, [{"id": seed["peca"], "tam": "M", "qtd": 2}]).get_json()
    with app.app_context():
        linha = EstoquePeca.query.filter_by(peca_id=seed["peca"], tamanho="M").first()
        linha.reservado = 0.0
        db.session.commit()
    # Balcão vende 2 M nesse meio-tempo.
    client.post("/console/erp/vendas/nova", data={
        "peca_id": [str(seed["peca"])], "tamanho": ["M"], "quantidade": ["2"],
        "preco_unitario": ["200"], "desconto": [""], "frete": "", "desconto_total": "",
    }, follow_redirects=True)
    body = client.post(f"/console/erp/vendas/{d['pedido_id']}/confirmar-pedido",
                       follow_redirects=True).get_data(as_text=True)
    assert "sem estoque desde o pedido" in body
    with app.app_context():
        est = EstoquePeca.query.filter_by(peca_id=seed["peca"], tamanho="M").first()
        assert est.quantidade == 1.0                # 3−2 (balcão); nunca negativo
        venda = Venda.query.get(d["pedido_id"])
        assert venda.itens[0].produzir is True      # foi para produção


def test_encomenda_grava_preco_cheio_e_cobra_sinal(client, app, seed):
    """Peça sem estoque (sob encomenda): item registra o preço cheio; o total
    cobrado agora (Pix) é o sinal; o restante fica como saldo da venda."""
    from app.models import Peca, PecaInsumo, Venda, db
    with app.app_context():
        p = Peca(nome="Peça Encomenda", preco_etiqueta=200.0, sku="SH-ENC",
                 custo_mao_de_obra=0.0)
        db.session.add(p)
        db.session.commit()
        db.session.add(PecaInsumo(peca_id=p.id, insumo_id=seed["tecido"], quantidade=2.0))
        db.session.commit()
        pid = p.id
        assert p.sob_encomenda and not p.esgotado
        sinal = p.preco_vitrine                     # custo 10 → múltiplo de 5 = 10

    d = _pedido_vitrine(client, seed, [{"id": pid, "tam": "M", "qtd": 1}]).get_json()
    assert d["total"] == sinal                      # cobrado agora = sinal
    assert "sinal" in d["resumo"] and "Restante das encomendas" in d["resumo"]
    with app.app_context():
        venda = Venda.query.get(d["pedido_id"])
        assert venda.itens[0].preco_unitario == 200.0   # antes: gravava o sinal
        assert venda.receita == 200.0                   # saldo cheio registrado


def test_tam_invalido_cai_no_padrao(client, app, seed):
    from app.models import Venda
    d = _pedido_vitrine(client, seed, [{"id": seed["peca"], "tam": "XXL", "qtd": 1}]).get_json()
    with app.app_context():
        assert Venda.query.get(d["pedido_id"]).itens[0].tamanho == "M"   # antes: "XXL"


def test_editar_venda_preserva_custo_historico(client, app, seed):
    from app.models import Peca, Venda, db
    client.post("/console/erp/vendas/nova", data={
        "peca_id": [str(seed["peca"])], "tamanho": ["M"], "quantidade": ["1"],
        "preco_unitario": ["200"], "desconto": [""], "frete": "", "desconto_total": "",
    }, follow_redirects=True)
    with app.app_context():
        vid = Venda.query.order_by(Venda.id.desc()).first().id
        custo_original = Venda.query.get(vid).itens[0].custo_unitario
        # Custo da peça sobe depois da venda.
        Peca.query.get(seed["peca"]).custo_mao_de_obra = 50.0
        db.session.commit()
    client.post(f"/console/erp/vendas/{vid}/editar", data={
        "peca_id": [str(seed["peca"])], "tamanho": ["M"], "quantidade": ["1"],
        "preco_unitario": ["190"], "desconto": [""], "frete": "", "desconto_total": "",
    }, follow_redirects=True)
    with app.app_context():
        assert Venda.query.get(vid).itens[0].custo_unitario == custo_original


def test_devolucao_recalcula_pago(client, app, seed):
    """Venda de 2 un (R$400), pagamento parcial de R$200; devolver 1 un deixa a
    receita em R$200 — a venda deve virar paga."""
    from app.models import Venda
    client.post("/console/erp/vendas/nova", data={
        "peca_id": [str(seed["peca"])], "tamanho": ["M"], "quantidade": ["2"],
        "preco_unitario": ["200"], "desconto": [""], "frete": "", "desconto_total": "",
    }, follow_redirects=True)
    with app.app_context():
        venda = Venda.query.order_by(Venda.id.desc()).first()
        vid, item_id = venda.id, venda.itens[0].id
    client.post(f"/console/erp/vendas/{vid}/receber",
                data={"valor": "200", "forma": "Pix"}, follow_redirects=True)
    with app.app_context():
        assert Venda.query.get(vid).pago is False
    client.post(f"/console/erp/vendas/{vid}/devolucao",
                data={f"qtd_{item_id}": "1"}, follow_redirects=True)
    with app.app_context():
        venda = Venda.query.get(vid)
        assert venda.receita == 200.0
        assert venda.pago is True                   # antes: continuava pendente


def test_to_float_milhar_brasileiro(app):
    from app.routes.helpers import _to_float
    assert _to_float("1.200") == 1200.0             # antes: 1.2
    assert _to_float("1.234.567") == 1234567.0
    assert _to_float("1.234,56") == 1234.56
    assert _to_float("1.5") == 1.5                  # decimal comum segue decimal
    assert _to_float("0.500") == 0.5                # quantidade decimal preservada
    assert _to_float("1200") == 1200.0
    assert _to_float("12,5") == 12.5


def test_pagamento_bloqueado_em_pre_pedido(client, app, seed):
    from app.models import Venda
    d = _pedido_vitrine(client, seed, [{"id": seed["peca"], "tam": "M", "qtd": 1}]).get_json()
    vid = d["pedido_id"]
    for url, data in [
        (f"/console/erp/vendas/{vid}/pagar", {}),
        (f"/console/erp/vendas/{vid}/receber", {"valor": "50"}),
        (f"/console/erp/vendas/{vid}/pagamentos",
         {"pag_forma": ["Pix"], "pag_valor": ["50"], "pag_parcelas": ["1"], "pag_taxa": [""]}),
    ]:
        body = client.post(url, data=data, follow_redirects=True).get_data(as_text=True)
        assert "Confirme o pré-pedido" in body
    with app.app_context():
        venda = Venda.query.get(vid)
        assert venda.pago is False and not venda.pagamentos
