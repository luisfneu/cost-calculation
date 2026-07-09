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
