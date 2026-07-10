"""Ajustes de workflow: guarda ao excluir peça, produzido baixa/estorna insumo,
reset de senha pelo ateliê, reivindicação segura, frete recalculado no servidor."""


def test_nao_exclui_peca_com_historico(client, app, seed):
    from app.models import Peca, Venda, VendaItem, db
    with app.app_context():
        v = Venda(status="realizado", tipo="venda", comprador="X")
        db.session.add(v); db.session.commit()
        db.session.add(VendaItem(venda_id=v.id, peca_id=seed["peca"], tamanho="M",
                                 quantidade=1, preco_unitario=10))
        db.session.commit()
    client.post(f"/console/erp/pecas/{seed['peca']}/excluir", follow_redirects=True)
    with app.app_context():
        assert Peca.query.get(seed["peca"]) is not None   # bloqueado: histórico existe


def test_produzido_baixa_e_estorna_insumo(client, app, seed):
    from app.models import Insumo, Venda, VendaItem, db
    with app.app_context():
        v = Venda(status="realizado", tipo="venda", comprador="X")
        db.session.add(v); db.session.commit()
        it = VendaItem(venda_id=v.id, peca_id=seed["peca"], tamanho="GG",
                       quantidade=2, preco_unitario=10, produzir=True)
        db.session.add(it); db.session.commit()
        iid = it.id
        tecido0 = Insumo.query.get(seed["tecido"]).estoque   # ficha: 2/peça
        linha0 = Insumo.query.get(seed["linha"]).estoque     # ficha: 1/peça

    client.post(f"/console/erp/encomendas/item/{iid}/produzido", follow_redirects=True)
    with app.app_context():
        assert Insumo.query.get(seed["tecido"]).estoque == tecido0 - 4  # 2/peça × 2
        assert Insumo.query.get(seed["linha"]).estoque == linha0 - 2    # 1/peça × 2
        assert VendaItem.query.get(iid).insumo_baixado is True

    # Reabrir estorna (e não baixa de novo em toggles repetidos).
    client.post(f"/console/erp/encomendas/item/{iid}/produzido", follow_redirects=True)
    with app.app_context():
        assert Insumo.query.get(seed["tecido"]).estoque == tecido0
        assert VendaItem.query.get(iid).insumo_baixado is False


def test_reset_senha_pelo_atelie(client, app):
    from app.models import Cliente, db
    with app.app_context():
        c = Cliente(nome="Bea", email="bea@ex.com", telefone="51900002222")
        c.set_senha("antiga1")
        db.session.add(c); db.session.commit()
        cid = c.id
    client.post(f"/console/erp/clientes/{cid}/resetar-senha", follow_redirects=True)
    with app.app_context():
        c = Cliente.query.get(cid)
        assert c.tem_conta is True
        assert not c.conferir_senha("antiga1")   # senha antiga invalidada


def test_reivindicar_bloqueia_quando_dados_nao_conferem(app):
    """E-mail bate, mas o WhatsApp do cadastro existente é outro → não reivindica."""
    from app.models import Cliente, db
    with app.app_context():
        c = Cliente(nome="Dona", email="dona@ex.com", telefone="51900001111")
        db.session.add(c); db.session.commit()
    cli = app.test_client()
    cli.post("/conta/cadastro", data={
        "nome": "Atacante", "email": "dona@ex.com", "senha": "segredo1",
        "telefone": "51999999999",  # telefone diferente do cadastro
    })
    with app.app_context():
        assert Cliente.por_email("dona@ex.com").tem_conta is False   # não virou conta


def test_frete_retirar_ignora_preco_do_cliente(app):
    from app.routes.catalogo import _frete_recalculado
    with app.app_context():
        val, ok = _frete_recalculado("", [{"id": 1, "qtd": 1}], "Retirar em mãos")
        assert val == 0.0 and ok is True


def test_producao_possivel_pelo_insumo_limitante(app, seed):
    from app.models import Insumo, Peca
    with app.app_context():
        p = Peca.query.get(seed["peca"])   # ficha: tecido 2/peça, linha 1/peça
        # estoques da seed: tecido=100, linha=100 → min(100//2, 100//1) = 50 (tecido limita)
        assert p.producao_possivel == 50
        assert p.insumo_limitante.insumo_id == seed["tecido"]
        # reduz o tecido: 5 → rende 2 peças, vira o limitante
        Insumo.query.get(seed["tecido"]).estoque = 5
        assert p.producao_possivel == 2

    from app.models import Peca as P2
    with app.app_context():
        vazia = P2(nome="Sem ficha", preco_etiqueta=10)   # sem insumos
        assert vazia.producao_possivel is None


def test_busca_global_peca_e_cliente(client, app, seed):
    b = client.get("/console/erp/buscar?q=Vestido").get_data(as_text=True)
    assert "Vestido Flor" in b            # peça da seed
    b2 = client.get("/console/erp/buscar?q=Ana").get_data(as_text=True)
    assert "Ana" in b2                    # cliente da seed


def test_produzir_lote_marca_varios(client, app, seed):
    from app.models import Venda, VendaItem, db
    with app.app_context():
        v = Venda(status="realizado", tipo="venda", comprador="X")
        db.session.add(v); db.session.commit()
        i1 = VendaItem(venda_id=v.id, peca_id=seed["peca"], tamanho="GG",
                       quantidade=1, preco_unitario=10, produzir=True)
        i2 = VendaItem(venda_id=v.id, peca_id=seed["peca"], tamanho="PP",
                       quantidade=1, preco_unitario=10, produzir=True)
        db.session.add_all([i1, i2]); db.session.commit()
        ids = [i1.id, i2.id]
    client.post("/console/erp/encomendas/produzir-lote",
                data={"item_ids": ids}, follow_redirects=True)
    with app.app_context():
        assert all(VendaItem.query.get(i).produzido for i in ids)
        assert all(VendaItem.query.get(i).insumo_baixado for i in ids)


def test_vitrine_tem_meta_e_og(app, seed):
    b = app.test_client().get("/").get_data(as_text=True)
    assert 'name="description"' in b
    assert 'rel="canonical"' in b
    assert 'property="og:title"' in b


def test_peca_publica_e_og(app, seed):
    from app.models import Parametro, db
    with app.app_context():
        Parametro.definir("whatsapp", "5551999990000")   # habilita o add-to-cart
        db.session.commit()
    r = app.test_client().get(f"/peca/{seed['peca']}")
    assert r.status_code == 200
    b = r.get_data(as_text=True)
    assert 'property="og:title"' in b and "pdp-comprar" in b


def test_peca_oculta_da_vitrine_404(app):
    from app.models import Peca, db
    with app.app_context():
        p = Peca(nome="Oculta", preco_etiqueta=10, vitrine_publica=False)
        db.session.add(p); db.session.commit()
        pid = p.id
    assert app.test_client().get(f"/peca/{pid}").status_code == 404


def test_etapa_sincroniza_com_status_da_venda(client, app):
    from app.models import Venda, db
    with app.app_context():
        v = Venda(status="pre-pedido", tipo="venda", comprador="X", estoque_baixado=False)
        db.session.add(v); db.session.commit(); vid = v.id
    client.post(f"/console/erp/vendas/{vid}/confirmar-pedido", follow_redirects=True)
    with app.app_context():
        assert Venda.query.get(vid).etapa_pedido == "aguard_pgto"
    client.post(f"/console/erp/vendas/{vid}/status/pago", follow_redirects=True)
    with app.app_context():
        assert Venda.query.get(vid).etapa_pedido == "pgto_aprovado"
    client.post(f"/console/erp/vendas/{vid}/status/enviado", follow_redirects=True)
    with app.app_context():
        assert Venda.query.get(vid).etapa_pedido == "preparando"   # entra no grupo Envio
    client.post(f"/console/erp/vendas/{vid}/status/entregue", follow_redirects=True)
    with app.app_context():
        assert Venda.query.get(vid).etapa_pedido == "entregue"
