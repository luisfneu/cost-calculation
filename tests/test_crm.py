"""CRM: aniversário, reativação e tamanho habitual."""
from datetime import UTC, date, datetime, timedelta, timezone


def test_aniversario_hoje_e_idade(app):
    from app.models import Cliente, db
    hoje = date.today()
    with app.app_context():
        c = Cliente(nome="Ana", nascimento=date(1990, hoje.month, hoje.day))
        db.session.add(c)
        db.session.commit()
        assert c.aniversario_hoje is True
        assert c.aniversario_no_mes is True
        assert c.dias_para_aniversario == 0
        assert c.idade == hoje.year - 1990


def test_inativo_e_reativacao(app):
    from app.models import Cliente, Peca, Venda, VendaItem, db
    with app.app_context():
        c = Cliente(nome="Caio")
        p = Peca(nome="Vestido", preco_etiqueta=100)
        db.session.add_all([c, p])
        db.session.commit()
        v = Venda(cliente_id=c.id, criado_em=datetime.now(UTC) - timedelta(days=120))
        db.session.add(v)
        db.session.flush()
        v.itens.append(VendaItem(peca_id=p.id, tamanho="M", quantidade=1, preco_unitario=100))
        db.session.commit()
        assert c.inativo(90) is True
        assert c.inativo(200) is False
        assert c.dias_desde_ultima_compra >= 119


def test_tamanho_frequente_e_preferido(app):
    from app.models import Cliente, Peca, Venda, VendaItem, db
    with app.app_context():
        c = Cliente(nome="Bia")
        p = Peca(nome="Vestido", preco_etiqueta=100)
        db.session.add_all([c, p])
        db.session.commit()
        v = Venda(cliente_id=c.id)
        db.session.add(v)
        db.session.flush()
        v.itens.append(VendaItem(peca_id=p.id, tamanho="G", quantidade=3, preco_unitario=100))
        db.session.commit()
        assert c.tamanho_frequente == "G"
        assert c.tamanho_preferido == "G"
        c.tamanho_habitual = "M"
        assert c.tamanho_preferido == "M"  # manual sobrepõe


def test_pagina_crm(client, app):
    from app.models import Cliente, db
    hoje = date.today()
    with app.app_context():
        db.session.add(Cliente(nome="Aniversariante", telefone="11999998888",
                               nascimento=date(1990, hoje.month, hoje.day)))
        db.session.commit()
    body = client.get("/crm").get_data(as_text=True)
    assert "Aniversariantes do mês" in body
    assert "Aniversariante" in body
    assert "wa.me/5511999998888" in body
