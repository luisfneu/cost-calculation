"""Regressão: notificação de pedido novo, aviso 'voltou ao estoque',
papéis (destrutivos só admin) e anonimização LGPD.
"""
import pytest


@pytest.fixture()
def emails_enviados(monkeypatch):
    """Captura envios (síncrono, sem thread nem rede)."""
    enviados = []
    monkeypatch.setattr("app.emails.email_configurado", lambda: True)
    monkeypatch.setattr("app.emails.enviar_email_async",
                        lambda destino, assunto, html: enviados.append((destino, assunto, html)))
    return enviados


def test_pedido_vitrine_notifica_atelier(client, app, seed, emails_enviados):
    from app.models import Parametro, db
    with app.app_context():
        Parametro.definir("aviso_email", "atelier@ex.com")
        db.session.commit()
    client.post("/publico/pedido", json={
        "cliente": {"nome": "Compradora", "telefone": "51999990000"},
        "itens": [{"id": seed["peca"], "tam": "M", "qtd": 1}],
    })
    assert len(emails_enviados) == 1
    destino, assunto, html = emails_enviados[0]
    assert destino == "atelier@ex.com"
    assert "Novo pedido" in assunto
    assert "Vestido Flor" in html


def test_sem_aviso_email_configurado_nao_envia(client, app, seed, emails_enviados):
    client.post("/publico/pedido", json={
        "cliente": {"nome": "Compradora", "telefone": "51999990000"},
        "itens": [{"id": seed["peca"], "tam": "M", "qtd": 1}],
    })
    assert emails_enviados == []


def _peca_esgotada_com_fa(app, seed):
    """Peça pública sem estoque + cliente com conta que a favoritou."""
    from app.models import Cliente, Peca, db
    with app.app_context():
        p = Peca(nome="Peça Aviso", preco_etiqueta=100.0, sku="SH-AVISO",
                 vitrine_publica=True)
        db.session.add(p)
        c = Cliente(nome="Fã", email="fa@ex.com", telefone="51900009999",
                    aceita_novidades=True)
        c.set_senha("Segredo1!")
        db.session.add(c)
        db.session.commit()
        c.definir_favoritos([p.id])
        db.session.commit()
        return p.id


def test_voltou_ao_estoque_avisa_favoritos(client, app, seed, emails_enviados):
    pid = _peca_esgotada_com_fa(app, seed)
    # Ajuste manual dá entrada: 0 → 2 disponíveis (transição dispara o aviso).
    client.post(f"/console/erp/pecas/{pid}/estoque/ajustar",
                data={"tamanho": "M", "quantidade": "2"}, follow_redirects=True)
    assert len(emails_enviados) == 1
    destino, assunto, html = emails_enviados[0]
    assert destino == "fa@ex.com" and "Voltou" in assunto and "Peça Aviso" in html
    # Nova entrada com estoque já positivo: NÃO repete o aviso.
    client.post(f"/console/erp/pecas/{pid}/estoque/ajustar",
                data={"tamanho": "M", "quantidade": "5"}, follow_redirects=True)
    assert len(emails_enviados) == 1


def test_voltou_ao_estoque_respeita_optout(client, app, seed, emails_enviados):
    from app.models import Cliente, db
    pid = _peca_esgotada_com_fa(app, seed)
    with app.app_context():
        Cliente.por_email("fa@ex.com").aceita_novidades = False
        db.session.commit()
    client.post(f"/console/erp/pecas/{pid}/estoque/ajustar",
                data={"tamanho": "M", "quantidade": "2"}, follow_redirects=True)
    assert emails_enviados == []


def _client_nao_admin(app):
    from app.models import Usuario, db
    with app.app_context():
        u = Usuario(nome="Vendedora", login="vend2", admin=False)
        u.set_senha("s3nh4")
        db.session.add(u)
        db.session.commit()
    cli = app.test_client()
    cli.post("/console/erp/login", data={"login": "vend2", "senha": "s3nh4"})
    return cli


def test_destrutivos_exigem_admin(app, client, seed):
    from app.models import Venda
    client.post("/console/erp/vendas/nova", data={
        "peca_id": [str(seed["peca"])], "tamanho": ["M"], "quantidade": ["1"],
        "preco_unitario": ["200"], "desconto": [""], "frete": "", "desconto_total": "",
    }, follow_redirects=True)
    with app.app_context():
        vid = Venda.query.order_by(Venda.id.desc()).first().id

    cli = _client_nao_admin(app)
    alvos = [
        f"/console/erp/vendas/{vid}/excluir",
        f"/console/erp/pecas/{seed['peca']}/excluir",
        f"/console/erp/insumos/{seed['tecido']}/excluir",
        f"/console/erp/clientes/{seed['cliente']}/excluir",
        "/console/erp/cupons/novo",
    ]
    for url in alvos:
        body = cli.post(url, data={}, follow_redirects=True).get_data(as_text=True)
        assert "restrito a administradores" in body, url
    body = cli.get("/console/erp/configuracoes", follow_redirects=True).get_data(as_text=True)
    assert "restrito a administradores" in body
    with app.app_context():
        assert Venda.query.get(vid) is not None      # nada foi excluído


def test_anonimizar_cliente_lgpd(client, app, seed):
    from app.models import Cliente, Endereco, Venda, db
    with app.app_context():
        c = Cliente.query.get(seed["cliente"])
        c.email = "ana@ex.com"
        c.set_senha("Segredo1!")
        c.cpf = "52998224725"
        db.session.add(Endereco(cliente_id=c.id, cep="90000-000", logradouro="Rua A"))
        db.session.add(Venda(status="realizado", tipo="venda", cliente_id=c.id,
                             comprador="Ana"))
        db.session.commit()

    client.post(f"/console/erp/clientes/{seed['cliente']}/anonimizar", follow_redirects=True)
    with app.app_context():
        c = Cliente.query.get(seed["cliente"])
        assert c.nome == f"Cliente anonimizado #{c.id}"
        assert c.email is None and c.cpf == "" and c.telefone == ""
        assert not c.tem_conta                                  # login desativado
        assert Endereco.query.filter_by(cliente_id=c.id).count() == 0
        venda = Venda.query.filter_by(cliente_id=c.id).first()
        assert venda is not None                                # histórico preservado
        assert venda.comprador == c.nome                        # nome antigo apagado
