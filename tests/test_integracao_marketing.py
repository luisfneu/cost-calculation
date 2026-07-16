"""Regressão: integração vitrine↔ERP e marketing — carrinho abandonado, views,
avaliações, notificação de etapa, aviso de promoção, cupom automático, SEO,
sugestões de busca.
"""
import pytest


@pytest.fixture()
def emails_enviados(monkeypatch):
    enviados = []
    monkeypatch.setattr("app.emails.email_configurado", lambda: True)
    monkeypatch.setattr("app.emails.enviar_email_async",
                        lambda destino, assunto, html: enviados.append((destino, assunto, html)))
    return enviados


def _cliente_com_conta(app, **kw):
    from app.models import Cliente, db
    with app.app_context():
        c = Cliente(nome=kw.pop("nome", "Cli Teste"), email=kw.pop("email", "cli@ex.com"),
                    telefone=kw.pop("telefone", "51900001111"), **kw)
        c.set_senha("Segredo1!")
        db.session.add(c)
        db.session.commit()
        return c.id


def _login_vitrine(app, cid):
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["cliente_id"] = cid
    return cli


# ---------------- carrinho abandonado ----------------
def test_carrinho_sync_e_crm_abandonados(client, app, seed):
    from app.models import Cliente
    cid = _cliente_com_conta(app)
    cli = _login_vitrine(app, cid)
    r = cli.post("/conta/carrinho/sync", json={"itens": [
        {"id": seed["peca"], "tam": "M", "qtd": 2, "nome": "Vestido Flor", "preco": 200},
    ]})
    assert r.get_json()["ok"]
    with app.app_context():
        assert Cliente.query.get(cid).carrinho_em is not None
    # GET devolve o carrinho salvo (outro aparelho restaura).
    itens = cli.get("/conta/carrinho/sync").get_json()["itens"]
    assert itens[0]["nome"] == "Vestido Flor" and itens[0]["qtd"] == 2
    # Aparece no CRM como carrinho abandonado.
    body = client.get("/console/erp/crm").get_data(as_text=True)
    assert "Carrinhos abandonados" in body and "Vestido Flor" in body


def test_pedido_limpa_carrinho_salvo(client, app, seed):
    from app.models import Cliente
    cid = _cliente_com_conta(app, email="cli2@ex.com", telefone="51900002222")
    cli = _login_vitrine(app, cid)
    cli.post("/conta/carrinho/sync", json={"itens": [
        {"id": seed["peca"], "tam": "M", "qtd": 1, "nome": "Vestido Flor", "preco": 200}]})
    cli.post("/publico/pedido", json={
        "cliente": {"nome": "Cli", "telefone": "51900002222"},
        "itens": [{"id": seed["peca"], "tam": "M", "qtd": 1}],
    })
    with app.app_context():
        assert Cliente.query.get(cid).carrinho_json == ""    # não é mais "abandonado"


# ---------------- views ----------------
def test_pdp_conta_views_sem_derrubar_cache(client, app, seed, monkeypatch):
    from app.models import Peca
    chamadas = []
    monkeypatch.setattr("app.routes.helpers._limpar_cache_vitrine",
                        lambda: chamadas.append(1))
    client.get(f"/peca/{seed['peca']}")
    client.get(f"/peca/{seed['peca']}")
    with app.app_context():
        assert Peca.query.get(seed["peca"]).views == 2
    assert chamadas == []           # UPDATE direto não invalida o cache


# ---------------- avaliações ----------------
def test_avaliacao_fluxo_completo(client, app, seed):
    from app.models import Avaliacao, Venda, db
    cid = _cliente_com_conta(app, email="ava@ex.com", telefone="51900003333")
    with app.app_context():
        v = Venda(status="entregue", tipo="venda", cliente_id=cid, pago=True,
                  etapa_pedido="entregue", estoque_baixado=False)
        db.session.add(v)
        db.session.commit()
        from app.models import VendaItem
        db.session.add(VendaItem(venda_id=v.id, peca_id=seed["peca"], tamanho="M",
                                 quantidade=1, preco_unitario=200))
        db.session.commit()
        vid = v.id
    cli = _login_vitrine(app, cid)
    cli.post(f"/conta/pedidos/{vid}/avaliar",
             data={"peca_id": seed["peca"], "nota": "5", "texto": "Amei o caimento!"},
             follow_redirects=True)
    with app.app_context():
        av = Avaliacao.query.filter_by(peca_id=seed["peca"], cliente_id=cid).first()
        assert av is not None and av.aprovado is False
        aid = av.id
    # Antes de aprovar: não aparece na PDP.
    assert "Amei o caimento" not in client.get(f"/peca/{seed['peca']}").get_data(as_text=True)
    client.post(f"/console/erp/avaliacoes/{aid}/aprovar", follow_redirects=True)
    body = client.get(f"/peca/{seed['peca']}").get_data(as_text=True)
    assert "Amei o caimento" in body and "aggregateRating" in body


def test_avaliacao_bloqueada_antes_de_entregue(client, app, seed):
    from app.models import Avaliacao, Venda, VendaItem, db
    cid = _cliente_com_conta(app, email="ava2@ex.com", telefone="51900004444")
    with app.app_context():
        v = Venda(status="pago", tipo="venda", cliente_id=cid, etapa_pedido="pgto_aprovado",
                  estoque_baixado=False)
        db.session.add(v)
        db.session.commit()
        db.session.add(VendaItem(venda_id=v.id, peca_id=seed["peca"], tamanho="M",
                                 quantidade=1, preco_unitario=200))
        db.session.commit()
        vid = v.id
    cli = _login_vitrine(app, cid)
    body = cli.post(f"/conta/pedidos/{vid}/avaliar",
                    data={"peca_id": seed["peca"], "nota": "5"},
                    follow_redirects=True).get_data(as_text=True)
    assert "depois que o pedido for entregue" in body
    with app.app_context():
        assert Avaliacao.query.count() == 0


# ---------------- notificação de etapa ----------------
def test_cliente_recebe_email_ao_mudar_etapa(client, app, seed, emails_enviados):
    from app.models import Venda
    cid = _cliente_com_conta(app, email="etapa@ex.com", telefone="51900005555")
    client.post("/console/erp/vendas/nova", data={
        "peca_id": [str(seed["peca"])], "tamanho": ["M"], "quantidade": ["1"],
        "preco_unitario": ["200"], "desconto": [""], "frete": "", "desconto_total": "",
        "cliente_id": str(cid),
    }, follow_redirects=True)
    with app.app_context():
        vid = Venda.query.order_by(Venda.id.desc()).first().id
    client.post(f"/console/erp/vendas/{vid}/pagar", follow_redirects=True)
    assert len(emails_enviados) == 1
    assert emails_enviados[0][0] == "etapa@ex.com"
    assert "Pagamento aprovado" in emails_enviados[0][1]
    # Enviar com rastreio: e-mail inclui o código.
    client.post(f"/console/erp/vendas/{vid}/rastreio", data={"rastreio": "AA1BR"}, follow_redirects=True)
    client.post(f"/console/erp/vendas/{vid}/status/enviado", follow_redirects=True)
    client.post(f"/console/erp/vendas/{vid}/etapa/avancar", follow_redirects=True)  # preparando→enviado
    assert any("AA1BR" in html for _, _, html in emails_enviados[1:])


# ---------------- promoção para favoritos ----------------
def test_promocao_avisa_favoritos(client, app, seed, emails_enviados):
    from app.models import Cliente, db
    cid = _cliente_com_conta(app, email="promo@ex.com", telefone="51900006666",
                             aceita_novidades=True)
    with app.app_context():
        Cliente.query.get(cid).definir_favoritos([seed["peca"]])
        db.session.commit()
    client.post(f"/console/erp/pecas/{seed['peca']}/editar", data={
        "nome": "Vestido Flor", "preco_promocional": "150", "vitrine_publica": "on",
    }, follow_redirects=True)
    assert len(emails_enviados) == 1
    assert "Promoção" in emails_enviados[0][1]
    # Salvar de novo (já em promoção): não repete.
    client.post(f"/console/erp/pecas/{seed['peca']}/editar", data={
        "nome": "Vestido Flor", "preco_promocional": "150", "vitrine_publica": "on",
    }, follow_redirects=True)
    assert len(emails_enviados) == 1


# ---------------- cupom aniversário automático ----------------
def test_cupom_aniversario_automatico_no_crm(client, app):
    from datetime import date

    from app.models import Cliente, Cupom, db
    hoje = date.today()
    with app.app_context():
        c = Cliente(nome="Niver Hoje", telefone="51900007777",
                    nascimento=hoje.replace(year=1990))
        db.session.add(c)
        db.session.commit()
        cid = c.id
    body = client.get("/console/erp/crm").get_data(as_text=True)
    assert "criados automaticamente" in body
    with app.app_context():
        assert Cupom.query.filter_by(cliente_id=cid).count() == 1
    # Segunda visita: idempotente.
    client.get("/console/erp/crm")
    with app.app_context():
        assert Cupom.query.filter_by(cliente_id=cid).count() == 1


# ---------------- SEO + busca ----------------
def test_robots_sitemap_jsonld(client, app, seed):
    r = client.get("/robots.txt")
    assert r.status_code == 200 and b"Sitemap:" in r.data and b"/console/" in r.data
    r = client.get("/sitemap.xml")
    assert r.status_code == 200 and f"/peca/{seed['peca']}".encode() in r.data
    body = client.get(f"/peca/{seed['peca']}").get_data(as_text=True)
    assert 'application/ld+json' in body and '"@type": "Product"' in body


def test_sugestoes_busca(client, seed):
    d = client.get("/publico/sugestoes?q=vest").get_json()
    assert any("Vestido" in s["nome"] for s in d["sugestoes"])
    assert client.get("/publico/sugestoes?q=v").get_json()["sugestoes"] == []
