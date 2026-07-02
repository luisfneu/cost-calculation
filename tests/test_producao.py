"""Ordens de produção: lista de compras e conclusão."""


def test_ordem_suficiente_conclui(client, app, seed):
    from app.models import Peca, Insumo, OrdemProducao
    pid = seed["peca"]
    r = client.post("/producao/nova", data={
        "descricao": "Teste", "peca_id": [str(pid)], "tamanho": ["P"], "quantidade": ["3"],
    }, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        ordem = OrdemProducao.query.order_by(OrdemProducao.id.desc()).first()
        oid = ordem.id
        assert ordem.insumos_suficientes is True
        estoque_p_antes = Peca.query.get(pid).estoque_por_tamanho["P"]

    client.post(f"/producao/{oid}/concluir", follow_redirects=True)
    with app.app_context():
        ordem = OrdemProducao.query.get(oid)
        p = Peca.query.get(pid)
        tecido = Insumo.query.get(seed["tecido"])
        assert ordem.status == "concluida"
        assert p.estoque_por_tamanho["P"] == estoque_p_antes + 3
        assert tecido.estoque == 100.0 - 2 * 3  # 2m por peça


def test_lista_compras_quando_falta_insumo(client, app, seed):
    from app.models import OrdemProducao
    pid = seed["peca"]  # tecido 100m; 60 peças => 120m > estoque
    client.post("/producao/nova", data={
        "peca_id": [str(pid)], "tamanho": ["M"], "quantidade": ["60"],
    }, follow_redirects=True)
    with app.app_context():
        ordem = OrdemProducao.query.order_by(OrdemProducao.id.desc()).first()
        assert ordem.insumos_suficientes is False
        nomes = [c["insumo"].nome for c in ordem.lista_compras]
        assert "Tecido" in nomes


def test_ordem_de_minimos(client, app, seed):
    from app.models import OrdemProducao
    pid = seed["peca"]
    client.post("/estoque/inventario", data={f"cont_{pid}_P": "1", f"min_{pid}_P": "5"})
    r = client.get("/producao/de-minimos", follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        ordem = OrdemProducao.query.order_by(OrdemProducao.id.desc()).first()
        assert ordem is not None and len(ordem.itens) >= 1
