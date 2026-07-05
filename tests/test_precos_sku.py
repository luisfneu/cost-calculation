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


def test_arredondar_cima_multiplo_5():
    from app.models import arredondar_cima
    assert arredondar_cima(32) == 35
    assert arredondar_cima(36) == 40
    assert arredondar_cima(35) == 35   # já múltiplo: mantém
    assert arredondar_cima(30) == 30
    assert arredondar_cima(0.1) == 5
    assert arredondar_cima(0) == 0


def test_preco_vitrine_sob_encomenda_usa_custo_arredondado(app):
    from app.models import Peca, db
    with app.app_context():
        # Sem estoque => sob encomenda. custo_total = mão de obra 32 => R$35.
        p = Peca(nome="Sob Enc", preco_etiqueta=200.0, custo_mao_de_obra=32.0)
        db.session.add(p)
        db.session.commit()
        assert p.sob_encomenda is True
        assert p.custo_total == 32.0
        assert p.preco_vitrine == 35.0     # 32 -> próximo múltiplo de 5


def test_preco_vitrine_com_estoque_usa_preco_normal(app):
    from app.models import EstoquePeca, Peca, db
    with app.app_context():
        p = Peca(nome="Com Estoque", preco_etiqueta=120.0, custo_mao_de_obra=32.0)
        db.session.add(p)
        db.session.flush()
        db.session.add(EstoquePeca(peca_id=p.id, tamanho="M", quantidade=2.0))
        db.session.commit()
        assert p.sob_encomenda is False
        assert p.preco_vitrine == 120.0    # ignora o custo, usa preço de etiqueta


def test_vitrine_tamanhos_indisponiveis(client, app):
    from app.models import EstoquePeca, Parametro, Peca, db
    with app.app_context():
        Parametro.definir("whatsapp", "5511999999999")  # chips só aparecem com WhatsApp
        p = Peca(nome="Blusa Tam", preco_etiqueta=100.0, vitrine_publica=True, sku="SH-TAM")
        db.session.add(p)
        db.session.flush()
        db.session.add(EstoquePeca(peca_id=p.id, tamanho="M", quantidade=3.0))  # só M em estoque
        db.session.commit()
    body = client.get("/publico/vitrine").get_data(as_text=True)
    assert 'data-tam="M"' in body
    # M com estoque (chip normal); PP sem estoque (amarelo/sob encomenda, ainda selecionável).
    assert 'class="tam-chip" data-tam="M" data-sem-estoque="0"' in body
    assert 'class="tam-chip sem-estoque" data-tam="PP" data-sem-estoque="1"' in body
