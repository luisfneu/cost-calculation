"""Crediário: gera parcelas, libera o pedido, recebe parcelas em contas a receber."""


def _pedido_com_saldo(client, app, seed):
    """Registra uma venda (P, 1x R$200) que fica com saldo total pendente."""
    client.post("/vendas/nova", data={
        "cliente_id": str(seed["cliente"]),
        "peca_id": [str(seed["peca"])], "tamanho": ["P"], "quantidade": ["1"],
        "preco_unitario": ["200"], "desconto": ["0"],
    }, follow_redirects=True)
    from app.models import Venda
    with app.app_context():
        return Venda.query.order_by(Venda.id.desc()).first().id


def test_crediario_gera_parcelas(client, app, seed):
    vid = _pedido_com_saldo(client, app, seed)
    client.post(f"/vendas/{vid}/pagamentos", data={
        "pag_forma": ["Crediário"], "pag_valor": ["200"], "pag_parcelas": ["1"], "pag_taxa": ["0"],
        "cred_parcelas": "3", "cred_inicio": "2026-08-10",
    }, follow_redirects=True)
    from app.models import Venda
    with app.app_context():
        v = Venda.query.get(vid)
        assert v.status == "crediario"
        assert v.pago is False
        assert len(v.parcelas) == 3
        # soma das parcelas = total
        assert round(sum(p.valor for p in v.parcelas), 2) == 200.0
        # vencimentos mensais
        vencs = [p.vencimento.isoformat() for p in v.parcelas]
        assert vencs == ["2026-08-10", "2026-09-10", "2026-10-10"]
        # ainda tem saldo (nada pago)
        assert v.saldo_receber > 199


def test_crediario_liberado_para_envio(client, app, seed):
    vid = _pedido_com_saldo(client, app, seed)
    client.post(f"/vendas/{vid}/pagamentos", data={
        "pag_forma": ["Crediário"], "pag_valor": ["200"], "pag_parcelas": ["1"], "pag_taxa": ["0"],
        "cred_parcelas": "2", "cred_inicio": "2026-08-10",
    }, follow_redirects=True)
    # mesmo com saldo, pode enviar (crediário libera)
    client.post(f"/vendas/{vid}/status/enviado", follow_redirects=True)
    from app.models import Venda
    with app.app_context():
        assert Venda.query.get(vid).status == "enviado"


def test_parcelas_em_contas_a_receber_e_pagar(client, app, seed):
    vid = _pedido_com_saldo(client, app, seed)
    client.post(f"/vendas/{vid}/pagamentos", data={
        "pag_forma": ["Crediário"], "pag_valor": ["200"], "pag_parcelas": ["1"], "pag_taxa": ["0"],
        "cred_parcelas": "2", "cred_inicio": "2026-08-10",
    }, follow_redirects=True)
    body = client.get("/contas-a-receber").get_data(as_text=True)
    assert "Crediário — parcelas em aberto" in body
    assert f"#{vid}" in body

    from app.models import Venda, Parcela
    with app.app_context():
        ids = [p.id for p in Venda.query.get(vid).parcelas]
    # paga as duas parcelas
    for pid in ids:
        client.post(f"/parcelas/{pid}/pagar", follow_redirects=True)
    with app.app_context():
        v = Venda.query.get(vid)
        assert v.crediario_quitado is True
        assert v.pago is True
        assert v.status == "pago"
        assert v.saldo_receber < 0.01
