"""Regressão: sincronização da etapa do pedido (stepper do cliente) após
pagamento, flag `pago` derivada dos pagamentos reais, cupom pessoal no ERP.
"""


def _venda_erp(client, app, seed, cupom="", cliente_id=""):
    from app.models import Venda
    client.post("/console/erp/vendas/nova", data={
        "peca_id": [str(seed["peca"])], "tamanho": ["M"], "quantidade": ["1"],
        "preco_unitario": ["200"], "desconto": [""],
        "frete": "", "desconto_total": "", "cupom": cupom,
        "cliente_id": cliente_id,
    }, follow_redirects=True)
    with app.app_context():
        return Venda.query.order_by(Venda.id.desc()).first().id


def _etapa(app, vid):
    from app.models import Venda
    with app.app_context():
        v = Venda.query.get(vid)
        return v.etapa_pedido, v.pago, v.status


def test_receber_pagamentos_avanca_etapa(client, app, seed):
    vid = _venda_erp(client, app, seed)
    client.post(f"/console/erp/vendas/{vid}/pagamentos", data={
        "pag_forma": ["Pix"], "pag_valor": ["200"], "pag_parcelas": ["1"], "pag_taxa": [""],
    }, follow_redirects=True)
    etapa, pago, status = _etapa(app, vid)
    assert pago and status == "pago"
    assert etapa == "pgto_aprovado"        # antes ficava em "recebido"/"aguard_pgto"


def test_marcar_pago_avanca_etapa(client, app, seed):
    vid = _venda_erp(client, app, seed)
    client.post(f"/console/erp/vendas/{vid}/pagar", follow_redirects=True)
    etapa, pago, _ = _etapa(app, vid)
    assert pago and etapa == "pgto_aprovado"


def test_usar_vale_quitando_avanca_etapa(client, app, seed):
    from app.models import Vale, db
    vid = _venda_erp(client, app, seed)
    with app.app_context():
        v = Vale(codigo="VL-TESTE1", tipo="presente", valor_inicial=500.0, saldo=500.0)
        db.session.add(v)
        db.session.commit()
    client.post(f"/console/erp/vendas/{vid}/usar-vale",
                data={"codigo": "VL-TESTE1"}, follow_redirects=True)
    etapa, pago, _ = _etapa(app, vid)
    assert pago and etapa == "pgto_aprovado"


def test_voltar_status_nao_despaga_venda_com_pagamentos(client, app, seed):
    vid = _venda_erp(client, app, seed)
    client.post(f"/console/erp/vendas/{vid}/pagamentos", data={
        "pag_forma": ["Pix"], "pag_valor": ["200"], "pag_parcelas": ["1"], "pag_taxa": [""],
    }, follow_redirects=True)
    # Volta o status para "realizado" (ex.: clique errado no fluxo).
    client.post(f"/console/erp/vendas/{vid}/status/realizado", follow_redirects=True)
    _, pago, status = _etapa(app, vid)
    assert status == "realizado"
    assert pago is True                    # dinheiro recebido continua recebido


def test_cupom_pessoal_de_outro_cliente_ignorado_no_erp(client, app, seed):
    from app.models import Cupom, Venda, db
    with app.app_context():
        db.session.add(Cupom(codigo="NIVERANA", tipo="percentual", valor=5.0,
                             ativo=True, max_usos=1, cliente_id=seed["cliente"]))
        db.session.commit()
    # Venda SEM cliente (ou de outro cliente) tentando usar o cupom da Ana.
    vid = _venda_erp(client, app, seed, cupom="NIVERANA")
    with app.app_context():
        v = Venda.query.get(vid)
        assert v.desconto_total == 0.0             # antes: aplicava 5%
        assert v.cupom_codigo in ("", None)
        assert Cupom.query.filter_by(codigo="NIVERANA").first().usos == 0


def test_cupom_pessoal_do_proprio_cliente_aplica(client, app, seed):
    from app.models import Cupom, Venda, db
    with app.app_context():
        db.session.add(Cupom(codigo="NIVERANA2", tipo="percentual", valor=5.0,
                             ativo=True, max_usos=1, cliente_id=seed["cliente"]))
        db.session.commit()
    vid = _venda_erp(client, app, seed, cupom="NIVERANA2", cliente_id=str(seed["cliente"]))
    with app.app_context():
        v = Venda.query.get(vid)
        assert v.desconto_total == 10.0            # 5% de 200
        assert v.cupom_codigo == "NIVERANA2"
