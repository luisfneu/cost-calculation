"""Duplicar peça: leva os dados e a ficha técnica, não leva as fotos."""

import pytest


@pytest.fixture()
def original(app):
    from app.models import EstoquePeca, FotoPeca, Insumo, Peca, PecaInsumo, db

    with app.app_context():
        tecido = Insumo(nome="Linho", tipo="tecido", unidade="m", custo_unitario=19.9,
                        estoque=30, composicao="100% linho")
        linha = Insumo(nome="Linha", tipo="aviamento", unidade="rolo", custo_unitario=4.0,
                       estoque=20)
        db.session.add_all([tecido, linha])
        db.session.commit()

        peca = Peca(
            nome="Vestido Genova", tipo="Vestido", colecao="Verão", tags="linho,verão",
            descricao="Vestido midi", composicao="100% linho", zona_corpo="inteiro",
            foto="vestido.jpg", vitrine_publica=True, custo_mao_de_obra=90.0,
            custos_extras=12.5, margem_percentual=55.0, preco_etiqueta=390.0,
            preco_promocional=299.0, peso_g=400, altura_cm=5, largura_cm=30,
            comprimento_cm=40, sku="SH-00000001", views=42,
        )
        db.session.add(peca)
        db.session.commit()
        db.session.add_all([
            PecaInsumo(peca_id=peca.id, insumo_id=tecido.id, quantidade=2.4),
            PecaInsumo(peca_id=peca.id, insumo_id=linha.id, quantidade=1),
            FotoPeca(peca_id=peca.id, arquivo="extra1.jpg"),
            FotoPeca(peca_id=peca.id, arquivo="extra2.jpg"),
            EstoquePeca(peca_id=peca.id, tamanho="M", quantidade=5),
        ])
        db.session.commit()
        return peca.id


def _duplicar(client, peca_id):
    return client.post(f"/console/erp/pecas/{peca_id}/duplicar", follow_redirects=True)


def _copia_id(app, peca_id):
    """Id da cópia — o objeto precisa ser recarregado dentro do app_context."""
    from app.models import Peca
    with app.app_context():
        return Peca.query.filter(Peca.id != peca_id).one().id


def test_copia_os_dados(client, app, original):
    _duplicar(client, original)
    from app.models import Peca, db

    with app.app_context():
        nova = Peca.query.filter(Peca.id != original).one()
        orig = db.session.get(Peca, original)
        assert nova.nome == "Vestido Genova (cópia)"
        for campo in ("tipo", "colecao", "tags", "descricao", "composicao", "zona_corpo",
                      "custo_mao_de_obra", "custos_extras", "margem_percentual",
                      "preco_etiqueta", "peso_g", "altura_cm", "largura_cm", "comprimento_cm"):
            assert getattr(nova, campo) == getattr(orig, campo), campo


def test_nao_copia_fotos(client, app, original):
    """O pedido central: cópia nasce sem foto nenhuma."""
    _duplicar(client, original)
    from app.models import FotoPeca, Peca, db

    nova_id = _copia_id(app, original)
    with app.app_context():
        nova = db.session.get(Peca, nova_id)
        assert nova.foto in (None, "")
        assert FotoPeca.query.filter_by(peca_id=nova_id).count() == 0
        # As fotos da original continuam lá.
        assert FotoPeca.query.filter_by(peca_id=original).count() == 2


def test_copia_a_ficha_tecnica(client, app, original):
    _duplicar(client, original)
    from app.models import Peca, PecaInsumo, db

    nova_id = _copia_id(app, original)
    with app.app_context():
        itens = PecaInsumo.query.filter_by(peca_id=nova_id).all()
        assert sorted(i.quantidade for i in itens) == [1.0, 2.4]
        assert db.session.get(Peca, nova_id).custo_insumos == 51.76   # 2,4 × 19,90 + 1 × 4,00


def test_nao_copia_estoque_nem_views(client, app, original):
    _duplicar(client, original)

    from app.models import Peca, db

    nova_id = _copia_id(app, original)
    with app.app_context():
        nova = db.session.get(Peca, nova_id)
        assert nova.estoque_total == 0
        assert nova.views == 0


def test_copia_nasce_fora_da_vitrine_e_sem_promocao(client, app, original):
    """Rascunho não pode aparecer na loja nem herdar a promoção da original."""
    _duplicar(client, original)

    from app.models import Peca, db

    nova_id = _copia_id(app, original)
    with app.app_context():
        nova = db.session.get(Peca, nova_id)
        assert nova.vitrine_publica is False
        assert nova.preco_promocional == 0


def test_sku_novo_e_unico(client, app, original):
    _duplicar(client, original)
    from app.models import Peca, db

    nova_id = _copia_id(app, original)
    with app.app_context():
        nova = db.session.get(Peca, nova_id)
        assert nova.sku == Peca.gerar_sku(nova.id)
        assert nova.sku != "SH-00000001"


def test_redireciona_para_edicao(client, original):
    r = client.post(f"/console/erp/pecas/{original}/duplicar")
    assert r.status_code == 302
    assert "/editar" in r.headers["Location"]


def test_botao_aparece_no_detalhe(client, original):
    html = client.get(f"/console/erp/pecas/{original}").get_data(as_text=True)
    assert f"/pecas/{original}/duplicar" in html
