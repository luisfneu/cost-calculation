"""Soft delete de peça: arquivar some das listas/seleções sem apagar nada,
só admin arquiva/restaura, e peças já usadas em pedidos/kits continuam
aparecendo onde precisam (edição) mesmo depois de arquivadas.
"""
import json


def _client_nao_admin(app):
    """Client logado como usuário comum (não-admin)."""
    from app.models import Usuario, db
    with app.app_context():
        u = Usuario(nome="Vendedora", login="vend-arq", admin=False)
        u.set_senha("s3nh4-vend")
        db.session.add(u)
        db.session.commit()
    cli = app.test_client()
    cli.post("/console/erp/login", data={"login": "vend-arq", "senha": "s3nh4-vend"})
    return cli


def test_arquivar_some_da_lista_e_desarquivar_devolve(client, seed):
    peca_id = seed["peca"]
    r = client.get("/console/erp/pecas")
    assert "Vestido Flor" in r.get_data(as_text=True)

    r = client.post(f"/console/erp/pecas/{peca_id}/arquivar", follow_redirects=True)
    assert "arquivada" in r.get_data(as_text=True).lower()
    # GET à parte: a resposta acima ainda carrega o toast de sucesso (que cita
    # o nome da peça) — o que importa é a peça sumir da LISTA em si.
    r = client.get("/console/erp/pecas")
    assert "Vestido Flor" not in r.get_data(as_text=True)

    # Continua acessível direto pelo id (histórico/estoque intactos).
    r = client.get(f"/console/erp/pecas/{peca_id}")
    assert r.status_code == 200
    assert "arquivada" in r.get_data(as_text=True).lower()

    # Aparece na tela de administração.
    r = client.get("/console/erp/pecas/arquivadas")
    assert "Vestido Flor" in r.get_data(as_text=True)

    r = client.post(f"/console/erp/pecas/{peca_id}/desarquivar", follow_redirects=True)
    assert "restaurada" in r.get_data(as_text=True).lower()
    r = client.get("/console/erp/pecas")
    assert "Vestido Flor" in r.get_data(as_text=True)


def test_arquivar_e_tela_de_arquivadas_exigem_admin(app, client, seed):
    peca_id = seed["peca"]
    cli = _client_nao_admin(app)

    r = cli.post(f"/console/erp/pecas/{peca_id}/arquivar", follow_redirects=True)
    assert "restrito a administradores" in r.get_data(as_text=True)

    r = cli.get("/console/erp/pecas/arquivadas", follow_redirects=True)
    assert "restrito a administradores" in r.get_data(as_text=True)

    # Admin consegue normalmente.
    r = client.post(f"/console/erp/pecas/{peca_id}/arquivar", follow_redirects=True)
    assert "arquivada" in r.get_data(as_text=True).lower()


def test_peca_arquivada_some_do_picker_de_nova_venda(client, seed, app):
    from app.models import EstoquePeca, Peca, db

    peca_id = seed["peca"]
    # Uma segunda peça ativa com estoque: senão a lista de peças fica vazia e o
    # bloco inteiro do picker (inclusive o <script id="dados-pecas">) nem renderiza.
    with app.app_context():
        outra = Peca(nome="Saia Lisa", preco_etiqueta=100.0, sku="SH-0002")
        db.session.add(outra)
        db.session.commit()
        db.session.add(EstoquePeca(peca_id=outra.id, tamanho="M", quantidade=2.0))
        db.session.commit()

    client.post(f"/console/erp/pecas/{peca_id}/arquivar")

    r = client.get("/console/erp/vendas/nova")
    html = r.get_data(as_text=True)
    inicio = html.index('id="dados-pecas"')
    bloco = html[inicio:html.index("</script>", inicio)]
    pecas = json.loads(bloco.split(">", 1)[1])
    assert all(p["id"] != peca_id for p in pecas)


def test_editar_venda_com_item_arquivado_mantem_peca_no_picker(client, seed, app):
    """Uma venda antiga com a peça já arquivada precisa continuar editável —
    senão o picker da linha existente perde nome/foto da peça."""
    from app.models import Venda, VendaItem, db

    with app.app_context():
        venda = Venda(status="realizado", tipo="venda", comprador="Ana")
        db.session.add(venda)
        db.session.flush()
        db.session.add(VendaItem(
            venda=venda, peca_id=seed["peca"], tamanho="P", quantidade=1,
            preco_unitario=200.0, custo_unitario=10.0,
        ))
        db.session.commit()
        venda_id = venda.id

    client.post(f"/console/erp/pecas/{seed['peca']}/arquivar")

    r = client.get(f"/console/erp/vendas/{venda_id}/editar")
    html = r.get_data(as_text=True)
    inicio = html.index('id="dados-pecas"')
    bloco = html[inicio:html.index("</script>", inicio)]
    pecas = json.loads(bloco.split(">", 1)[1])
    assert any(p["id"] == seed["peca"] for p in pecas)


def test_peca_publica_arquivada_da_404_mesmo_com_vitrine_publica(client, seed, app):
    from app.models import Peca, db

    with app.app_context():
        peca = Peca.query.get(seed["peca"])
        peca.vitrine_publica = True
        peca.arquivada = True
        db.session.commit()

    r = client.get(f"/peca/{seed['peca']}")
    assert r.status_code == 404
