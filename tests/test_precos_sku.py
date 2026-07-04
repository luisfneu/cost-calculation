"""Preço de/por (promoção), SKU e disponibilidade na vitrine."""


def test_preco_efetivo_promocao(app):
    from app.models import Peca, db
    with app.app_context():
        p = Peca(nome="Blusa", preco_etiqueta=120.0, preco_promocional=89.9)
        db.session.add(p)
        db.session.commit()
        assert p.em_promocao is True
        assert p.preco_base == 120.0
        assert p.preco_etiqueta_efetivo == 89.9


def test_preco_sem_promocao(app):
    from app.models import Peca, db
    with app.app_context():
        p = Peca(nome="Saia", preco_etiqueta=70.0)
        db.session.add(p)
        db.session.commit()
        assert p.em_promocao is False
        assert p.preco_etiqueta_efetivo == 70.0


def test_vitrine_mostra_de_por(client, app):
    from app.models import Peca, db
    with app.app_context():
        db.session.add(Peca(nome="Vestido", preco_etiqueta=120.0, preco_promocional=89.9))
        db.session.commit()
    body = client.get("/vitrine").get_data(as_text=True)
    assert "89,90" in body and "120,00" in body


def test_form_peca_sku_autogerado_e_promo(client, app, seed):
    from app.models import Peca
    # O SKU enviado é ignorado: é sempre gerado a partir do id (SH-00000000).
    r = client.post(f"/pecas/{seed['peca']}/editar", data={
        "nome": "Vestido Flor", "preco_promocional": "149,90", "sku": "SH-9999",
    }, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        p = Peca.query.get(seed["peca"])
        assert p.sku == Peca.gerar_sku(seed["peca"])  # ex.: SH-00000001
        assert p.preco_promocional == 149.9
        assert p.preco_etiqueta == 200.0  # não zerou os demais campos


def test_nova_peca_recebe_sku_automatico(client, app):
    from app.models import Peca
    r = client.post("/pecas/nova", data={"nome": "Nova Peça", "preco_etiqueta": "50"},
                    follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        p = Peca.query.filter_by(nome="Nova Peça").first()
        assert p.sku == Peca.gerar_sku(p.id)
