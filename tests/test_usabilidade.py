"""Regressão: e-mail do convidado no checkout (lead → cliente) e código de
rastreio (ERP grava, cliente vê no pedido).
"""


def _pedido_vitrine(client, seed, email=""):
    return client.post("/publico/pedido", json={
        "cliente": {"nome": "Convidada", "telefone": "51999990000", "email": email},
        "itens": [{"id": seed["peca"], "tam": "M", "qtd": 1}],
    })


def test_checkout_guarda_email_do_convidado(client, app, seed):
    from app.models import Lead
    d = _pedido_vitrine(client, seed, email="Convidada@Ex.com").get_json()
    with app.app_context():
        assert Lead.query.get(d["lead_id"]).email == "convidada@ex.com"   # normalizado


def test_checkout_recusa_email_invalido(client, app, seed):
    r = _pedido_vitrine(client, seed, email="nao-e-email")
    assert r.status_code == 400
    assert "E-mail inválido" in r.get_json()["erro"]


def test_confirmar_lead_leva_email_para_o_cliente(client, app, seed):
    from app.models import Cliente, Lead
    d = _pedido_vitrine(client, seed, email="convidada@ex.com").get_json()
    client.post(f"/console/erp/leads/{d['lead_id']}/confirmar", follow_redirects=True)
    with app.app_context():
        lead = Lead.query.get(d["lead_id"])
        assert Cliente.query.get(lead.cliente_id).email == "convidada@ex.com"


def test_confirmar_lead_casa_por_email_sem_whatsapp_igual(client, app, seed):
    """Cliente já existe com o e-mail mas outro telefone: lead vincula a ele
    (antes só casava por WhatsApp → duplicava)."""
    from app.models import Cliente, Lead, db
    with app.app_context():
        c = Cliente(nome="Antiga", email="convidada@ex.com", telefone="51900000001")
        db.session.add(c)
        db.session.commit()
        cid = c.id
        antes = Cliente.query.count()
    d = _pedido_vitrine(client, seed, email="convidada@ex.com").get_json()
    client.post(f"/console/erp/leads/{d['lead_id']}/confirmar", follow_redirects=True)
    with app.app_context():
        assert Lead.query.get(d["lead_id"]).cliente_id == cid
        assert Cliente.query.count() == antes                 # não duplicou


def test_rastreio_erp_grava_e_cliente_ve(client, app, seed):
    from app.models import Cliente, Venda, db
    # Venda de balcão vinculada a um cliente com conta.
    with app.app_context():
        c = Cliente(nome="Rastreia", email="rast@ex.com", telefone="51922220000")
        c.set_senha("Segredo1!")
        db.session.add(c)
        db.session.commit()
        cid = c.id
    client.post("/console/erp/vendas/nova", data={
        "peca_id": [str(seed["peca"])], "tamanho": ["M"], "quantidade": ["1"],
        "preco_unitario": ["200"], "desconto": [""], "frete": "", "desconto_total": "",
        "cliente_id": str(cid),
    }, follow_redirects=True)
    with app.app_context():
        vid = Venda.query.order_by(Venda.id.desc()).first().id

    client.post(f"/console/erp/vendas/{vid}/rastreio",
                data={"rastreio": "AA123456789BR"}, follow_redirects=True)
    with app.app_context():
        assert Venda.query.get(vid).rastreio == "AA123456789BR"

    # Cliente logado vê o código no detalhe do pedido.
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["cliente_id"] = cid
    body = cli.get(f"/conta/pedidos/{vid}").get_data(as_text=True)
    assert "AA123456789BR" in body and "acompanhar entrega" in body
