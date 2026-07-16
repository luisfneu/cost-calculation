"""Regressão: baixa/estorno de estoque por item (flags produzir/insumo_baixado)
e exclusividade dos caminhos de produção (marcar produzido × baixar estoque).

Bugs cobertos:
- excluir/editar venda mista criava estoque fantasma para itens 'produzir';
- editar venda perdia as flags de produção (item sumia de Encomendas);
- marcar 'produzido' um item que já saiu do estoque pronto consumia insumos 2×;
- rota de baixa de estoque baixava itens de produção direta.
"""


def _pedido_vitrine(client, seed, itens):
    return client.post("/publico/pedido", json={
        "cliente": {"nome": "Cliente Teste", "telefone": "51999990000"},
        "itens": itens,
    })


def _estoques(app, peca_id):
    from app.models import EstoquePeca
    with app.app_context():
        return {e.tamanho: e.quantidade
                for e in EstoquePeca.query.filter_by(peca_id=peca_id).all()}


def test_excluir_venda_mista_nao_gera_estoque_fantasma(client, app, seed):
    # M tem estoque (3); GG não tem → produzir.
    r = _pedido_vitrine(client, seed, [
        {"id": seed["peca"], "tam": "M", "qtd": 2},
        {"id": seed["peca"], "tam": "GG", "qtd": 1},
    ])
    vid = r.get_json()["pedido_id"]
    client.post(f"/console/erp/vendas/{vid}/confirmar-pedido", follow_redirects=True)
    assert _estoques(app, seed["peca"])["M"] == 1.0   # baixou 3→1

    client.post(f"/console/erp/vendas/{vid}/excluir", follow_redirects=True)
    est = _estoques(app, seed["peca"])
    assert est["M"] == 3.0                 # estornou só o que baixou
    assert est.get("GG", 0.0) == 0.0       # 'produzir' nunca saiu: sem fantasma


def test_editar_venda_preserva_flags_de_producao(client, app, seed):
    from app.models import Venda
    r = _pedido_vitrine(client, seed, [
        {"id": seed["peca"], "tam": "M", "qtd": 2},
        {"id": seed["peca"], "tam": "GG", "qtd": 1},
    ])
    vid = r.get_json()["pedido_id"]
    client.post(f"/console/erp/vendas/{vid}/confirmar-pedido", follow_redirects=True)

    # Edita mantendo os mesmos itens (ex.: só ajustou um preço).
    client.post(f"/console/erp/vendas/{vid}/editar", data={
        "peca_id": [str(seed["peca"]), str(seed["peca"])],
        "tamanho": ["M", "GG"],
        "quantidade": ["2", "1"],
        "preco_unitario": ["190", "200"],
        "desconto": ["", ""],
        "frete": "", "desconto_total": "",
    }, follow_redirects=True)

    with app.app_context():
        venda = Venda.query.get(vid)
        itens = {it.tamanho: it for it in venda.itens}
        assert itens["GG"].produzir is True          # antes sumia na edição
        assert itens["M"].produzir is False
        assert venda.producao_pendente is True       # continua em Encomendas
    est = _estoques(app, seed["peca"])
    assert est["M"] == 1.0                           # sem dupla baixa
    assert est.get("GG", 0.0) == 0.0                 # sem crédito fantasma


def test_editar_venda_remover_item_produzir_nao_credita_estoque(client, app, seed):
    r = _pedido_vitrine(client, seed, [
        {"id": seed["peca"], "tam": "M", "qtd": 2},
        {"id": seed["peca"], "tam": "GG", "qtd": 1},
    ])
    vid = r.get_json()["pedido_id"]
    client.post(f"/console/erp/vendas/{vid}/confirmar-pedido", follow_redirects=True)

    # Remove o item GG (a produzir) da venda.
    client.post(f"/console/erp/vendas/{vid}/editar", data={
        "peca_id": [str(seed["peca"])],
        "tamanho": ["M"],
        "quantidade": ["2"],
        "preco_unitario": ["200"],
        "desconto": [""],
        "frete": "", "desconto_total": "",
    }, follow_redirects=True)

    est = _estoques(app, seed["peca"])
    assert est.get("GG", 0.0) == 0.0    # antes: estorno fantasma de +1 no GG
    assert est["M"] == 1.0


def test_marcar_produzido_bloqueado_apos_baixa_de_estoque(client, app, seed):
    """Encomenda atendida do estoque pronto: marcar 'produzido' depois da baixa
    consumiria os insumos em dobro — deve ser bloqueado."""
    from app.models import Insumo, Venda, VendaItem
    client.post("/console/erp/encomendas/nova", data={
        "peca_id": [str(seed["peca"])], "tamanho": ["M"], "quantidade": ["1"],
        "preco_unitario": ["200"], "desconto": [""],
        "frete": "", "desconto_total": "",
    }, follow_redirects=True)
    with app.app_context():
        venda = Venda.query.order_by(Venda.id.desc()).first()
        vid, item_id = venda.id, venda.itens[0].id
        assert venda.estoque_baixado is False

    # Ateliê decide atender do estoque pronto: baixa o estoque do pedido.
    client.post(f"/console/erp/vendas/{vid}/baixar-estoque", follow_redirects=True)
    assert _estoques(app, seed["peca"])["M"] == 2.0   # 3→2

    with app.app_context():
        tecido_antes = Insumo.query.get(seed["tecido"]).estoque
    body = client.post(f"/console/erp/encomendas/item/{item_id}/produzido",
                       follow_redirects=True).get_data(as_text=True)
    assert "dobro" in body
    with app.app_context():
        assert VendaItem.query.get(item_id).produzido is False
        assert Insumo.query.get(seed["tecido"]).estoque == tecido_antes


def test_produzir_encomenda_consome_insumos_uma_vez(client, app, seed):
    """Caminho normal da encomenda: marcar produzido baixa insumos 1× e não
    mexe no estoque de peças; a rota de baixa depois não acha nada para baixar."""
    from app.models import Insumo, Venda
    client.post("/console/erp/encomendas/nova", data={
        "peca_id": [str(seed["peca"])], "tamanho": ["M"], "quantidade": ["2"],
        "preco_unitario": ["200"], "desconto": [""],
        "frete": "", "desconto_total": "",
    }, follow_redirects=True)
    with app.app_context():
        venda = Venda.query.order_by(Venda.id.desc()).first()
        vid, item_id = venda.id, venda.itens[0].id

    client.post(f"/console/erp/encomendas/item/{item_id}/produzido", follow_redirects=True)
    with app.app_context():
        assert Insumo.query.get(seed["tecido"]).estoque == 96.0   # 100 − 2un×2m
        assert Insumo.query.get(seed["linha"]).estoque == 98.0    # 100 − 2un×1

    # Tentar "Baixar estoque" depois: item já produzido direto → nada a baixar.
    body = client.post(f"/console/erp/vendas/{vid}/baixar-estoque",
                       follow_redirects=True).get_data(as_text=True)
    assert "Nada a baixar" in body
    assert _estoques(app, seed["peca"])["M"] == 3.0   # estoque intocado


def _criar_encomenda_produzida(client, app, seed, qtd="1"):
    """Encomenda ERP de `qtd`× tam M já marcada como produzida. Retorna (vid, item_id)."""
    from app.models import Venda
    client.post("/console/erp/encomendas/nova", data={
        "peca_id": [str(seed["peca"])], "tamanho": ["M"], "quantidade": [qtd],
        "preco_unitario": ["200"], "desconto": [""],
        "frete": "", "desconto_total": "",
    }, follow_redirects=True)
    with app.app_context():
        venda = Venda.query.order_by(Venda.id.desc()).first()
        vid, item_id = venda.id, venda.itens[0].id
    client.post(f"/console/erp/encomendas/item/{item_id}/produzido", follow_redirects=True)
    return vid, item_id


def test_excluir_venda_com_item_produzido_devolve_peca_ao_estoque(client, app, seed):
    """Peça produzida sob encomenda existe fisicamente: excluir a venda deve
    colocá-la no estoque; os insumos ficam consumidos (foram usados)."""
    from app.models import Insumo
    vid, _ = _criar_encomenda_produzida(client, app, seed)
    with app.app_context():
        tecido = Insumo.query.get(seed["tecido"]).estoque   # já consumido na produção

    client.post(f"/console/erp/vendas/{vid}/excluir", follow_redirects=True)
    assert _estoques(app, seed["peca"])["M"] == 4.0         # 3 + 1 produzida
    with app.app_context():
        assert Insumo.query.get(seed["tecido"]).estoque == tecido   # insumo não volta


def test_editar_venda_remover_item_produzido_devolve_peca_ao_estoque(client, app, seed):
    from app.models import Peca, db
    vid, _ = _criar_encomenda_produzida(client, app, seed, qtd="2")
    with app.app_context():   # segunda peça para a venda continuar com 1 item
        outra = Peca(nome="Saia Lua", preco_etiqueta=100.0, sku="SH-LUA")
        db.session.add(outra); db.session.commit()
        outra_id = outra.id

    # Edita: reduz o item produzido de 2 para 1 e adiciona outra peça.
    client.post(f"/console/erp/vendas/{vid}/editar", data={
        "peca_id": [str(seed["peca"]), str(outra_id)],
        "tamanho": ["M", "M"],
        "quantidade": ["1", "1"],
        "preco_unitario": ["200", "100"],
        "desconto": ["", ""],
        "frete": "", "desconto_total": "",
    }, follow_redirects=True)
    assert _estoques(app, seed["peca"])["M"] == 4.0   # 3 + 1 produzida que sobrou


def test_devolucao_de_item_produzido_credita_estoque(client, app, seed):
    vid, item_id = _criar_encomenda_produzida(client, app, seed)
    client.post(f"/console/erp/vendas/{vid}/devolucao",
                data={f"qtd_{item_id}": "1"}, follow_redirects=True)
    assert _estoques(app, seed["peca"])["M"] == 4.0   # peça devolvida entra


def test_pedido_vitrine_so_producao_nao_baixa_estoque_de_outros(client, app, seed):
    """Pedido 100% a produzir: confirmação fecha a contabilidade de estoque
    (estoque_baixado=True) e a rota de baixa não desconta nada."""
    from app.models import Venda
    r = _pedido_vitrine(client, seed, [{"id": seed["peca"], "tam": "GG", "qtd": 1}])
    vid = r.get_json()["pedido_id"]
    client.post(f"/console/erp/vendas/{vid}/confirmar-pedido", follow_redirects=True)
    with app.app_context():
        assert Venda.query.get(vid).estoque_baixado is True
    client.post(f"/console/erp/vendas/{vid}/baixar-estoque", follow_redirects=True)
    est = _estoques(app, seed["peca"])
    assert est["M"] == 3.0 and est["P"] == 5.0        # nada foi descontado
