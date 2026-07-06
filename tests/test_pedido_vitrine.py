"""Fluxo da vitrine: pedido → pré-pedido (Venda) + Lead; lead cria cliente;
confirmar pedido efetiva (baixa estoque / produção); bloqueios de status."""


def _fazer_pedido(client, seed, itens):
    return client.post("/publico/pedido", json={
        "cliente": {"nome": "Bianca Vitrine", "telefone": "51999990000",
                    "cidade": "Porto Alegre", "uf": "RS"},
        "itens": itens,
        "frete": {"nome": "Retirar em mãos", "preco": 0},
    })


def test_pedido_cria_pre_pedido_e_lead(client, app, seed):
    from app.models import Lead, Venda
    r = _fazer_pedido(client, seed, [{"id": seed["peca"], "tam": "M", "qtd": 1}])
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] and d["lead_id"] and d["pedido_id"]
    with app.app_context():
        venda = Venda.query.get(d["pedido_id"])
        assert venda.status == "pre-pedido"
        assert venda.estoque_baixado is False
        assert venda.lead_id == d["lead_id"]
        assert Lead.query.get(d["lead_id"]).status == "pendente"


def test_confirmar_lead_so_cria_cliente_e_vincula(client, app):
    from app.models import Cliente, Lead, Peca, Venda, db
    with app.app_context():
        p = Peca(nome="Peça X", preco_etiqueta=50.0, sku="SH-X")
        db.session.add(p); db.session.commit()
        pid = p.id
    r = _fazer_pedido(client, {"peca": pid}, [{"id": pid, "tam": "M", "qtd": 1}])
    d = r.get_json()
    client.post(f"/console/erp/leads/{d['lead_id']}/confirmar", follow_redirects=True)
    with app.app_context():
        lead = Lead.query.get(d["lead_id"])
        assert lead.status == "confirmado" and lead.cliente_id
        venda = Venda.query.get(d["pedido_id"])
        assert venda.status == "pre-pedido"          # ainda NÃO efetivado
        assert venda.cliente_id == lead.cliente_id   # cliente vinculado ao pré-pedido
        assert Cliente.query.get(lead.cliente_id).nome == "Bianca Vitrine"


def test_confirmar_pedido_efetiva_estoque_e_producao(client, app, seed):
    from app.models import EstoquePeca, Venda
    r = _fazer_pedido(client, seed, [
        {"id": seed["peca"], "tam": "M", "qtd": 2},    # tem estoque (3)
        {"id": seed["peca"], "tam": "GG", "qtd": 1},   # sem estoque → produzir
    ])
    vid = r.get_json()["pedido_id"]
    client.post(f"/console/erp/vendas/{vid}/confirmar-pedido", follow_redirects=True)
    with app.app_context():
        venda = Venda.query.get(vid)
        assert venda.status == "realizado"
        itens = {it.tamanho: it for it in venda.itens}
        assert itens["M"].produzir is False
        assert itens["GG"].produzir is True
        est_m = EstoquePeca.query.filter_by(peca_id=seed["peca"], tamanho="M").first()
        assert est_m.quantidade == 1.0              # baixou 3→1
        assert venda.producao_pendente is True       # GG ainda não produzido


def test_encomendas_so_apos_confirmar(client, app, seed):
    r = _fazer_pedido(client, seed, [{"id": seed["peca"], "tam": "GG", "qtd": 1}])
    vid = r.get_json()["pedido_id"]
    # antes de confirmar: não aparece em Encomendas
    assert "Vestido Flor" not in client.get("/console/erp/encomendas").get_data(as_text=True)
    client.post(f"/console/erp/vendas/{vid}/confirmar-pedido", follow_redirects=True)
    assert "Vestido Flor" in client.get("/console/erp/encomendas").get_data(as_text=True)


def test_bloqueia_envio_com_producao_pendente(client, app, seed):
    from app.models import Venda
    r = _fazer_pedido(client, seed, [{"id": seed["peca"], "tam": "GG", "qtd": 1}])
    vid = r.get_json()["pedido_id"]
    client.post(f"/console/erp/vendas/{vid}/confirmar-pedido", follow_redirects=True)
    # pré-pedido confirmado, mas GG a produzir → não pode enviar
    body = client.post(f"/console/erp/vendas/{vid}/status/enviado", follow_redirects=True).get_data(as_text=True)
    assert "não produzidos" in body or "produção" in body.lower()
    with app.app_context():
        assert Venda.query.get(vid).status != "enviado"


def test_pre_pedido_fora_dos_relatorios(client, app, seed):
    # pré-pedido não deve contar na receita do relatório
    _fazer_pedido(client, seed, [{"id": seed["peca"], "tam": "M", "qtd": 1}])
    body = client.get("/console/erp/relatorio").get_data(as_text=True)
    assert "Sem vendas no período" in body or "R$ 0,00" in body
