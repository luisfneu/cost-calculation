"""Escolher insumo para a ficha técnica mostrando o estoque disponível."""

import pytest


@pytest.fixture()
def dados(app):
    from app.models import Insumo, Peca, db

    with app.app_context():
        cheio = Insumo(nome="Linho Genova Marrom", tipo="tecido", unidade="m",
                       custo_unitario=19.9, estoque=12.0, estoque_minimo=2.0)
        zerado = Insumo(nome="Zíper invisível", tipo="aviamento", unidade="un",
                        custo_unitario=6.2, estoque=0.0)
        baixo = Insumo(nome="Etiqueta bordada", tipo="aviamento", unidade="un",
                       custo_unitario=2.4, estoque=3.0, estoque_minimo=5.0)
        peca = Peca(nome="Vestido", sku="SH-PCK-0001")
        db.session.add_all([cheio, zerado, baixo, peca])
        db.session.commit()
        return {"peca": peca.id}


def test_picker_mostra_estoque_disponivel(client, dados):
    html = client.get(f"/console/erp/pecas/{dados['peca']}").get_data(as_text=True)
    assert "12 m em estoque" in html


def test_picker_marca_insumo_sem_estoque(client, dados):
    html = client.get(f"/console/erp/pecas/{dados['peca']}").get_data(as_text=True)
    assert "sem estoque" in html


def test_picker_marca_estoque_baixo(client, dados):
    """Abaixo do mínimo aparece sinalizado, não só o número."""
    html = client.get(f"/console/erp/pecas/{dados['peca']}").get_data(as_text=True)
    assert "3 un · baixo" in html


def test_form_de_nova_peca_leva_o_estoque_para_o_js(client, dados):
    """O select da criação monta o rótulo com esse JSON."""
    html = client.get("/console/erp/pecas/nova").get_data(as_text=True)
    assert '"estoque": 12.0' in html
    assert "em estoque" in html          # trecho que monta o rótulo da option
