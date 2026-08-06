"""Frete da compra rateado no custo do insumo.

Comprar 10 camisas com R$120 de frete deixa cada uma R$12 mais cara — e é esse
custo que precisa chegar na ficha técnica da peça.
"""


def _criar(client, **campos):
    dados = {
        "nome": "Camisa cetim (fornecedor)",
        "tipo": "peca",
        "unidade": "un",
        "custo_unitario": "58,00",
        "estoque": "10",
        "estoque_minimo": "2",
        "ativo": "on",
        "frete_compra": "120,00",
        "frete_qtd": "10",
    }
    dados.update(campos)
    return client.post("/console/erp/insumos/novo", data=dados, follow_redirects=True)


def test_frete_entra_no_custo_unitario(client, app):
    _criar(client)

    from app.models import Insumo
    with app.app_context():
        i = Insumo.query.one()
        assert i.custo_unitario == 58.0        # material, sem frete
        assert i.frete_unitario == 12.0        # 120 / 10
        assert i.custo_com_frete == 70.0


def test_sem_quantidade_rateia_pelo_estoque_inicial(client, app):
    """Quem não preencher a quantidade do rateio usa o que comprou."""
    _criar(client, frete_qtd="")

    from app.models import Insumo
    with app.app_context():
        i = Insumo.query.one()
        assert i.frete_qtd == 10.0
        assert i.custo_com_frete == 70.0


def test_sem_frete_o_custo_nao_muda(client, app):
    _criar(client, frete_compra="", frete_qtd="")

    from app.models import Insumo
    with app.app_context():
        i = Insumo.query.one()
        assert i.frete_unitario == 0.0
        assert i.custo_com_frete == i.custo_unitario == 58.0


def test_frete_sem_quantidade_valida_nao_estoura(app):
    """Quantidade zerada não pode virar divisão por zero."""
    from app.models import Insumo

    i = Insumo(nome="X", custo_unitario=10.0, frete_compra=50.0, frete_qtd=0.0)
    assert i.frete_unitario == 0.0
    assert i.custo_com_frete == 10.0


def test_ficha_da_peca_usa_o_custo_com_frete(client, app):
    """O que o cliente paga tem que cobrir o frete que você pagou na compra."""
    _criar(client)
    _criar(client, nome="Sacola", tipo="aviamento", custo_unitario="1,30",
           estoque="100", frete_compra="", frete_qtd="")

    from app.models import Insumo, Peca, PecaInsumo, db
    with app.app_context():
        camisa = Insumo.query.filter_by(tipo="peca").one()
        sacola = Insumo.query.filter_by(nome="Sacola").one()
        peca = Peca(nome="Camisa cetim preta", margem_percentual=50.0, sku="SH-FRT-0001")
        db.session.add(peca)
        db.session.commit()
        db.session.add_all([
            PecaInsumo(peca_id=peca.id, insumo_id=camisa.id, quantidade=1),
            PecaInsumo(peca_id=peca.id, insumo_id=sacola.id, quantidade=1),
        ])
        db.session.commit()

        assert peca.custo_insumos == 71.30      # 70,00 (58 + 12 frete) + 1,30
        assert peca.custo_total == 71.30
        assert peca.preco_venda == 142.60


def test_lista_de_compras_da_ordem_considera_o_frete(client, app):
    """Repor material para produzir custa o preço cheio, frete incluído."""
    _criar(client, estoque="1")

    from app.models import (
        Insumo,
        OrdemProducao,
        OrdemProducaoItem,
        Peca,
        PecaInsumo,
        db,
    )
    with app.app_context():
        camisa = Insumo.query.one()
        camisa.frete_qtd = 10.0            # frete daquele lote de 10
        peca = Peca(nome="Camisa", sku="SH-FRT-0002")
        db.session.add(peca)
        db.session.commit()
        db.session.add(PecaInsumo(peca_id=peca.id, insumo_id=camisa.id, quantidade=1))
        ordem = OrdemProducao(descricao="Lote teste")
        db.session.add(ordem)
        db.session.commit()
        db.session.add(OrdemProducaoItem(ordem_id=ordem.id, peca_id=peca.id,
                                         tamanho="M", quantidade=3))
        db.session.commit()

        # Precisa de 3, tem 1 em estoque: faltam 2 a R$70,00 (58 + 12 de frete).
        compras = ordem.lista_compras
        assert len(compras) == 1
        assert compras[0]["comprar"] == 2
        assert compras[0]["custo"] == 140.0
        assert ordem.custo_compras == 140.0


def test_edicao_preserva_o_frete(client, app):
    _criar(client)

    from app.models import Insumo
    with app.app_context():
        insumo_id = Insumo.query.one().id

    client.post(f"/console/erp/insumos/{insumo_id}/editar", data={
        "nome": "Camisa cetim (fornecedor)", "tipo": "peca", "unidade": "un",
        "custo_unitario": "60,00", "estoque_minimo": "2", "ativo": "on",
        "frete_compra": "120,00", "frete_qtd": "10",
    }, follow_redirects=True)

    with app.app_context():
        i = Insumo.query.one()
        assert i.custo_unitario == 60.0
        assert i.custo_com_frete == 72.0
