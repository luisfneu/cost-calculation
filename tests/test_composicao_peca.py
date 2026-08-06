"""Composição da peça: herda do tecido / da peça pronta, mas o texto manual manda."""

import pytest


@pytest.fixture()
def ficha(app):
    """Peça com um tecido na ficha e uma peça pronta à parte, para reaproveitar."""
    from app.models import Insumo, Peca, PecaInsumo, db

    with app.app_context():
        tecido = Insumo(nome="Tricoline", tipo="tecido", unidade="m", custo_unitario=38.9,
                        estoque=50, composicao="100% algodão")
        linha = Insumo(nome="Linha", tipo="aviamento", unidade="rolo", custo_unitario=4.0,
                       estoque=20, composicao="")
        pronta = Insumo(nome="Camisa cetim (fornecedor)", tipo="peca", unidade="un",
                        custo_unitario=58.0, estoque=10, composicao="100% poliéster")
        db.session.add_all([tecido, linha, pronta])
        db.session.commit()

        peca = Peca(nome="Vestido", margem_percentual=50.0, sku="SH-TST-0001")
        db.session.add(peca)
        db.session.commit()
        db.session.add_all([
            PecaInsumo(peca_id=peca.id, insumo_id=tecido.id, quantidade=2),
            PecaInsumo(peca_id=peca.id, insumo_id=linha.id, quantidade=1),
        ])
        db.session.commit()
        return {"peca": peca.id, "tecido": tecido.id, "linha": linha.id, "pronta": pronta.id}


def test_herda_do_tecido_quando_peca_nao_tem(app, ficha):
    from app.models import Peca, db

    with app.app_context():
        peca = db.session.get(Peca, ficha["peca"])
        assert peca.composicao_herdada == "100% algodão"
        assert peca.composicao_efetiva == "100% algodão"


def test_texto_da_peca_vence_a_ficha(app, ficha):
    from app.models import Peca, db

    with app.app_context():
        peca = db.session.get(Peca, ficha["peca"])
        peca.composicao = "95% algodão, 5% elastano"
        db.session.commit()
        assert peca.composicao_efetiva == "95% algodão, 5% elastano"
        assert peca.composicao_herdada == "100% algodão"   # a da ficha continua visível


def test_herda_da_peca_pronta(app, ficha):
    """Revenda: a peça comprada carrega a composição."""
    from app.models import Peca, PecaInsumo, db

    with app.app_context():
        revenda = Peca(nome="Camisa cetim preta", margem_percentual=50.0, sku="SH-TST-0002")
        db.session.add(revenda)
        db.session.commit()
        db.session.add(PecaInsumo(peca_id=revenda.id, insumo_id=ficha["pronta"], quantidade=1))
        db.session.commit()
        assert revenda.composicao_efetiva == "100% poliéster"


def test_junta_composicoes_diferentes_sem_repetir(app, ficha):
    from app.models import Insumo, Peca, PecaInsumo, db

    with app.app_context():
        forro = Insumo(nome="Forro", tipo="tecido", unidade="m", custo_unitario=12.0,
                       estoque=30, composicao="100% viscose")
        igual = Insumo(nome="Tricoline lote 2", tipo="tecido", unidade="m", custo_unitario=39.0,
                       estoque=30, composicao="100% algodão")
        db.session.add_all([forro, igual])
        db.session.commit()
        db.session.add_all([
            PecaInsumo(peca_id=ficha["peca"], insumo_id=forro.id, quantidade=1),
            PecaInsumo(peca_id=ficha["peca"], insumo_id=igual.id, quantidade=1),
        ])
        db.session.commit()

        peca = db.session.get(Peca, ficha["peca"])
        assert peca.composicao_herdada == "100% algodão · 100% viscose"


def test_aviamento_com_composicao_nao_entra(app, ficha):
    """Só tecido e peça pronta descrevem o material da roupa."""
    from app.models import Insumo, Peca, PecaInsumo, db

    with app.app_context():
        db.session.get(Insumo, ficha["tecido"]).composicao = ""
        etiqueta = Insumo(nome="Etiqueta", tipo="aviamento", unidade="un", custo_unitario=2.0,
                          estoque=100, composicao="100% poliamida")
        db.session.add(etiqueta)
        db.session.commit()
        db.session.add(PecaInsumo(peca_id=ficha["peca"], insumo_id=etiqueta.id, quantidade=1))
        db.session.commit()

        assert db.session.get(Peca, ficha["peca"]).composicao_herdada == ""


def test_peca_sem_ficha_fica_vazia(app):
    from app.models import Peca

    assert Peca(nome="Solta").composicao_efetiva == ""


def test_vitrine_publica_mostra_a_herdada(client, app, ficha):
    from app.models import Peca, db

    with app.app_context():
        peca = db.session.get(Peca, ficha["peca"])
        peca.vitrine_publica = True
        peca.preco_etiqueta = 200.0
        db.session.commit()
        sku = peca.sku or Peca.gerar_sku(peca.id)
        peca.sku = sku
        db.session.commit()

    html = client.get(f"/peca/{ficha['peca']}").get_data(as_text=True)
    assert "100% algodão" in html


def test_form_mostra_a_composicao_da_ficha(client, ficha):
    html = client.get(f"/console/erp/pecas/{ficha['peca']}/editar").get_data(as_text=True)
    assert "Da ficha técnica:" in html
    assert "100% algodão" in html
