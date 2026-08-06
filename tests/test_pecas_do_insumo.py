"""Modal 'peças que usam este insumo', no mesmo formato do de movimentação."""

import pytest


@pytest.fixture()
def dados(app):
    from app.models import Insumo, Peca, PecaInsumo, db

    with app.app_context():
        tecido = Insumo(nome="Linho Genova", tipo="tecido", unidade="m",
                        custo_unitario=19.9, estoque=30)
        sozinho = Insumo(nome="Insumo sem uso", tipo="aviamento", unidade="un",
                         custo_unitario=1.0, estoque=5)
        db.session.add_all([tecido, sozinho])
        db.session.commit()

        for n in range(1, 4):
            peca = Peca(nome=f"Vestido {n}", colecao="Verão", sku=f"SH-USO-000{n}")
            db.session.add(peca)
            db.session.commit()
            db.session.add(PecaInsumo(peca_id=peca.id, insumo_id=tecido.id, quantidade=2.0))
        db.session.commit()
        return {"tecido": tecido.id, "sozinho": sozinho.id}


def test_lista_as_pecas_que_usam(client, dados):
    html = client.get(f"/console/erp/insumos/{dados['tecido']}/pecas").get_data(as_text=True)
    for n in (1, 2, 3):
        assert f"Vestido {n}" in html


def test_mostra_quanto_consome_e_quanto_custa(client, dados):
    html = client.get(f"/console/erp/insumos/{dados['tecido']}/pecas").get_data(as_text=True)
    assert "2 m" in html            # quantidade por peça
    assert "39,80" in html          # 2 × R$ 19,90 naquela peça


def test_insumo_sem_uso_mostra_estado_vazio(client, dados):
    html = client.get(f"/console/erp/insumos/{dados['sozinho']}/pecas").get_data(as_text=True)
    assert "não está na ficha técnica de nenhuma peça" in html


def test_pagina_quando_passa_de_15(client, app, dados):
    from app.models import Peca, PecaInsumo, db

    with app.app_context():
        for n in range(4, 22):      # 18 a mais -> 21 no total
            peca = Peca(nome=f"Vestido {n}", sku=f"SH-USO-{n:04d}")
            db.session.add(peca)
            db.session.commit()
            db.session.add(PecaInsumo(peca_id=peca.id, insumo_id=dados["tecido"], quantidade=1))
        db.session.commit()

    p1 = client.get(f"/console/erp/insumos/{dados['tecido']}/pecas").get_data(as_text=True)
    assert p1.count("<tr>") == 16                      # 15 linhas + cabeçalho
    assert "pagina=2" in p1

    p2 = client.get(f"/console/erp/insumos/{dados['tecido']}/pecas?pagina=2").get_data(as_text=True)
    assert p2.count("<tr>") == 7                       # 6 restantes + cabeçalho
    assert "hist-page" in p2                           # links paginam dentro do modal


def test_botao_e_modal_estao_na_lista(client, dados):
    html = client.get("/console/erp/insumos").get_data(as_text=True)
    assert 'id="modal-pecas"' in html
    assert "btn-pecas" in html


def test_exige_login(app, dados):
    r = app.test_client().get(f"/console/erp/insumos/{dados['tecido']}/pecas")
    assert r.status_code in (302, 401)
