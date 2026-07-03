"""Contas a receber (pedidos a prazo / com saldo pendente)."""
from datetime import date, timedelta


def _venda(app, seed, pago_valor=0.0, vencimento=None):
    from app.models import db, Venda, VendaItem, Pagamento
    with app.app_context():
        v = Venda(cliente_id=seed["cliente"], tipo="venda", vencimento=vencimento)
        db.session.add(v)
        db.session.flush()
        v.itens.append(VendaItem(peca_id=seed["peca"], tamanho="P",
                                 quantidade=1, preco_unitario=200))
        if pago_valor:
            v.pagamentos.append(Pagamento(forma="Pix", valor=pago_valor))
        db.session.commit()
        return v.id


def test_pedido_com_saldo_aparece(client, app, seed):
    vid = _venda(app, seed, pago_valor=50.0)  # total 200, pago 50, saldo 150
    body = client.get("/contas-a-receber").get_data(as_text=True)
    assert f"#{vid}" in body
    assert "150,00" in body


def test_pedido_quitado_nao_aparece(client, app, seed):
    vid = _venda(app, seed, pago_valor=200.0)  # quitado
    body = client.get("/contas-a-receber").get_data(as_text=True)
    assert f"#{vid}" not in body
    assert "Nenhuma parcela de crediário em aberto" in body


def test_vencido_destacado(client, app, seed):
    ontem = date.today() - timedelta(days=1)
    _venda(app, seed, pago_valor=0.0, vencimento=ontem)
    body = client.get("/contas-a-receber").get_data(as_text=True)
    assert "vencido" in body
    assert "table-danger" in body
