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


def test_fluxo_caixa_atraso_e_despesa(client, app, seed):
    from app.models import db, Despesa
    ontem = date.today() - timedelta(days=1)
    _venda(app, seed, pago_valor=0.0, vencimento=ontem)  # a receber 200 em atraso
    with app.app_context():
        db.session.add(Despesa(descricao="Aluguel", valor=300.0,
                               vencimento=date.today() + timedelta(days=5), pago=False))
        db.session.commit()
    body = client.get("/fluxo-caixa").get_data(as_text=True)
    assert "Fluxo de caixa projetado" in body
    assert "Em atraso" in body
    assert "200,00" in body   # a receber em atraso
    assert "300,00" in body   # despesa a pagar no mês


def test_fluxo_caixa_ignora_despesa_paga(client, app, seed):
    from app.models import db, Despesa
    with app.app_context():
        db.session.add(Despesa(descricao="Paga", valor=999.0,
                               vencimento=date.today(), pago=True))
        db.session.commit()
    body = client.get("/fluxo-caixa").get_data(as_text=True)
    assert "999,00" not in body


def _venda_em(app, seed, quando, preco):
    from datetime import datetime
    from app.models import db, Venda, VendaItem, Pagamento
    with app.app_context():
        v = Venda(cliente_id=seed["cliente"], tipo="venda",
                  criado_em=datetime(quando.year, quando.month, quando.day))
        db.session.add(v)
        db.session.flush()
        v.itens.append(VendaItem(peca_id=seed["peca"], tamanho="M",
                                 quantidade=1, preco_unitario=preco, custo_unitario=40))
        v.pagamentos.append(Pagamento(forma="Pix", valor=preco))
        db.session.commit()


def test_relatorio_comparativo_mensal(client, app, seed):
    from app.models import Pagamento  # noqa: F401 (usado em _venda_em)
    _venda_em(app, seed, date(2026, 5, 10), 150)
    _venda_em(app, seed, date(2026, 6, 10), 250)  # +66% vs mês anterior
    body = client.get("/relatorio?ano=2026").get_data(as_text=True)
    assert "Comparativo mensal" in body
    assert "Salvar PDF" in body
    assert "mai/2026" in body and "jun/2026" in body
    assert "bi-arrow-up-short" in body  # variação positiva marcada
