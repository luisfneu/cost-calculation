"""Insumo do tipo "peça pronta": roupa comprada acabada para revenda.

O ateliê compra a peça já feita, troca a etiqueta pela da marca e vende. No
sistema ela é um insumo (com o custo de compra) que entra na ficha técnica da
peça vendida, junto com embalagem e etiqueta.
"""


def _criar(client, **campos):
    dados = {
        "nome": "Camisa cetim preta (fornecedor)",
        "tipo": "peca",
        "unidade": "un",
        "custo_unitario": "58,00",
        "estoque": "10",
        "estoque_minimo": "2",
        "ativo": "on",
        "composicao": "100% poliéster",
    }
    dados.update(campos)
    return client.post("/console/erp/insumos/novo", data=dados, follow_redirects=True)


def test_cadastra_peca_pronta(client, app):
    r = _criar(client)
    assert r.status_code == 200

    from app.models import Insumo
    with app.app_context():
        i = Insumo.query.filter_by(nome="Camisa cetim preta (fornecedor)").one()
        assert i.tipo == "peca"
        assert i.is_peca_pronta
        assert i.tipo_label == "Peça pronta"
        assert i.custo_unitario == 58.0
        assert i.estoque == 10.0


def test_peca_pronta_guarda_composicao_mas_nao_largura(client, app):
    """Composição serve à etiqueta/vitrine; largura é só do rolo de tecido."""
    _criar(client, composicao="97% viscose, 3% elastano", largura="150")

    from app.models import Insumo
    with app.app_context():
        i = Insumo.query.filter_by(tipo="peca").one()
        assert i.composicao == "97% viscose, 3% elastano"
        assert i.largura_cm == 0.0


def test_tecido_continua_com_largura(client, app):
    """Regressão: o tipo tecido não pode perder a largura no mesmo caminho."""
    _criar(client, nome="Tricoline", tipo="tecido", unidade="m", largura="150",
           composicao="100% algodão")

    from app.models import Insumo
    with app.app_context():
        i = Insumo.query.filter_by(nome="Tricoline").one()
        assert i.largura_cm == 150.0
        assert i.composicao == "100% algodão"


def test_tipo_invalido_vira_aviamento(client, app):
    _criar(client, nome="Coisa estranha", tipo="qualquer-coisa")

    from app.models import Insumo
    with app.app_context():
        assert Insumo.query.filter_by(nome="Coisa estranha").one().tipo == "aviamento"


def test_filtro_por_tipo_peca(client):
    _criar(client)
    _criar(client, nome="Linha preta", tipo="aviamento", composicao="")

    html = client.get("/console/erp/insumos?tipo=peca&filtrado=1").get_data(as_text=True)
    assert "Camisa cetim preta (fornecedor)" in html
    assert "Linha preta" not in html


def test_revenda_soma_no_custo_da_peca(client, app):
    """Fluxo real: peça pronta + embalagem viram o custo da peça revendida."""
    _criar(client)
    _criar(client, nome="Sacola", tipo="aviamento", custo_unitario="1,30", composicao="")

    from app.models import Insumo, Peca, PecaInsumo, db
    with app.app_context():
        comprada = Insumo.query.filter_by(tipo="peca").one()
        sacola = Insumo.query.filter_by(nome="Sacola").one()
        revenda = Peca(nome="Camisa cetim preta", margem_percentual=50.0, custos_extras=0.0,
                       custo_mao_de_obra=0.0)
        db.session.add(revenda)
        db.session.commit()
        db.session.add_all([
            PecaInsumo(peca_id=revenda.id, insumo_id=comprada.id, quantidade=1),
            PecaInsumo(peca_id=revenda.id, insumo_id=sacola.id, quantidade=1),
        ])
        db.session.commit()

        assert revenda.custo_total == 59.30          # 58,00 + 1,30
        assert revenda.preco_venda == 118.60         # margem de 50%
        # O estoque da peça pronta limita quantas dá para montar.
        assert revenda.producao_possivel == 10
