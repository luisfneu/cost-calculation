"""Leads da vitrine: confirmação (vira cliente), dedup por WhatsApp, admin-only."""


def _novo_lead(app, **kw):
    from app.models import Lead, db
    dados = {"nome": "Maria Teste", "telefone": "51999998888", "instagram": "@maria"}
    dados.update(kw)
    with app.app_context():
        lead = Lead(**dados)
        db.session.add(lead)
        db.session.commit()
        return lead.id


def test_listar_leads_exige_admin(app):
    c = app.test_client()
    c.post("/login", data={"senha": "test"})
    with c.session_transaction() as s:
        s["admin"] = False
    r = c.get("/leads", follow_redirects=False)
    assert r.status_code == 302  # redirecionado (acesso restrito)


def test_confirmar_lead_cria_cliente(client, app):
    from app.models import Cliente, Lead
    lid = _novo_lead(app, nome="Ana Vitrine", cidade="Porto Alegre", uf="RS")
    r = client.post(f"/leads/{lid}/confirmar", follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        lead = Lead.query.get(lid)
        assert lead.status == "confirmado"
        assert lead.cliente_id is not None
        cli = Cliente.query.get(lead.cliente_id)
        assert cli.nome == "Ana Vitrine"
        assert cli.cidade == "Porto Alegre"


def test_confirmar_lead_dedup_por_whatsapp(client, app):
    from app.models import Cliente, Lead, db
    with app.app_context():
        existente = Cliente(nome="João Antigo", telefone="51988887777")
        db.session.add(existente)
        db.session.commit()
        antes = Cliente.query.count()
    lid = _novo_lead(app, nome="João Novo", telefone="51988887777")
    client.post(f"/leads/{lid}/confirmar", follow_redirects=True)
    with app.app_context():
        assert Cliente.query.count() == antes            # não duplicou
        lead = Lead.query.get(lid)
        assert Cliente.query.get(lead.cliente_id).nome == "João Antigo"  # vinculou ao existente


def test_descartar_lead(client, app):
    from app.models import Lead
    lid = _novo_lead(app)
    client.post(f"/leads/{lid}/descartar", follow_redirects=True)
    with app.app_context():
        assert Lead.query.get(lid).status == "descartado"
