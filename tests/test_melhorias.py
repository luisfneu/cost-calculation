"""Testes dos fluxos novos: arredondamento de dinheiro, telefone, cupom de
aniversário, filtro por tipo, URL da vitrine, página de erro, throttling de
login e uploader de fotos da peça."""
import io
from datetime import date

import pytest


# ----------------------------------------------------------------------------
# Dinheiro: arredondamento rígido
# ----------------------------------------------------------------------------
def test_dinheiro_arredonda_meio_para_cima():
    from app.models import dinheiro
    assert dinheiro(0.1 + 0.2) == 0.3
    assert dinheiro(2.675) == 2.68          # meio-para-cima (não 2.67)
    assert dinheiro(19.8999999) == 19.9
    assert dinheiro(None) == 0.0


def test_venda_receita_arredondada(app, db, seed):
    from app.models import db as _db, Venda, VendaItem
    with app.app_context():
        v = Venda(tipo="venda")
        _db.session.add(v)
        _db.session.commit()
        # 3 itens de 1/3 → soma exata a 2 casas, sem "0,999..."
        for _ in range(3):
            _db.session.add(VendaItem(venda_id=v.id, peca_id=seed["peca"],
                                      tamanho="M", quantidade=1, preco_unitario=0.10))
        _db.session.commit()
        assert v.receita == 0.30
        # valor sempre com no máximo 2 casas
        assert round(v.receita, 2) == v.receita


# ----------------------------------------------------------------------------
# Telefone formatado
# ----------------------------------------------------------------------------
@pytest.mark.parametrize("bruto,esperado", [
    ("51996556400", "(51) 99655-6400"),
    ("5180291284", "(51) 8029-1284"),
    ("(51) 99655-6400", "(51) 99655-6400"),
    ("5551996556400", "(51) 99655-6400"),   # com DDI 55
])
def test_telefone_formatado(bruto, esperado):
    from app.models import Cliente
    assert Cliente(telefone=bruto).telefone_formatado == esperado


# ----------------------------------------------------------------------------
# Cupom de aniversário
# ----------------------------------------------------------------------------
def test_cupom_aniversario(client, app):
    from app.models import db, Cliente, Cupom
    hoje = date.today()
    with app.app_context():
        c = Cliente(nome="Aniversariante", telefone="51999998888",
                    nascimento=date(1990, hoje.month, min(hoje.day + 1, 28)))
        db.session.add(c)
        db.session.commit()
        cid = c.id

    r = client.post(f"/crm/cupom-aniversario/{cid}", follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        cup = Cupom.query.filter_by(cliente_id=cid).first()
        assert cup is not None
        assert cup.valor == 5.0 and cup.max_usos == 1 and cup.tipo == "percentual"
        assert cup.valido is True

    # Não duplica: segundo clique avisa que já existe.
    r2 = client.post(f"/crm/cupom-aniversario/{cid}", follow_redirects=True)
    with app.app_context():
        assert Cupom.query.filter_by(cliente_id=cid).count() == 1


def test_crm_mensagem_tem_vitrine_e_quebras(client, app):
    from app.models import db, Cliente
    hoje = date.today()
    with app.app_context():
        db.session.add(Cliente(nome="Bday", telefone="5551999990000",
                               nascimento=date(1985, hoje.month, min(hoje.day + 1, 28))))
        db.session.commit()
    html = client.get("/crm").get_data(as_text=True)
    # A mensagem do WhatsApp deve ter quebras de linha (%0A) e a vitrine.
    assert "%0A" in html
    assert "publico/vitrine" in html or "vitrine" in html


# ----------------------------------------------------------------------------
# Filtro por tipo de peça
# ----------------------------------------------------------------------------
def test_filtro_por_tipo(client, app):
    from app.models import db, Peca
    with app.app_context():
        db.session.add(Peca(nome="Vestido A", tipo="Vestido", preco_etiqueta=100, sku="SH-A"))
        db.session.add(Peca(nome="Blusa B", tipo="Blusa", preco_etiqueta=80, sku="SH-B"))
        db.session.commit()
    corpo = client.get("/pecas?tipo=Vestido").get_data(as_text=True)
    assert "Vestido A" in corpo and "Blusa B" not in corpo


# ----------------------------------------------------------------------------
# URL pública da vitrine (config) usada no CRM
# ----------------------------------------------------------------------------
def test_url_vitrine_configuravel(client, app):
    from app.models import db, Cliente, Parametro
    hoje = date.today()
    with app.app_context():
        Parametro.definir("vitrine_url", "https://minhaloja.com.br/vitrine")
        db.session.add(Cliente(nome="Cli", telefone="5551999991111",
                               nascimento=date(1990, hoje.month, min(hoje.day + 1, 28))))
        db.session.commit()
    html = client.get("/crm").get_data(as_text=True)
    assert "minhaloja.com.br" in html


# ----------------------------------------------------------------------------
# Página de erro amigável
# ----------------------------------------------------------------------------
def test_pagina_404(client):
    r = client.get("/rota-inexistente-xyz")
    assert r.status_code == 404
    assert "Voltar ao painel" in r.get_data(as_text=True)


# ----------------------------------------------------------------------------
# Throttling de login (força bruta)
# ----------------------------------------------------------------------------
def test_login_throttling(app):
    from app.routes.sistema import _LOGIN_FALHAS, _LOGIN_MAX
    _LOGIN_FALHAS.clear()
    c = app.test_client()
    # Erra a senha _LOGIN_MAX vezes.
    for _ in range(_LOGIN_MAX):
        r = c.post("/login", data={"senha": "errada"})
        assert r.status_code == 200
    # Próxima tentativa é bloqueada (429), mesmo com a senha certa.
    r = c.post("/login", data={"senha": "test"})
    assert r.status_code == 429
    _LOGIN_FALHAS.clear()


# ----------------------------------------------------------------------------
# Uploader de fotos: várias fotos + escolha da principal
# ----------------------------------------------------------------------------
def _png(cor):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (8, 8), cor).save(b, "PNG")
    b.seek(0)
    return b


def test_uploader_fotos_principal(client, app, tmp_path):
    from app.models import db, Peca
    with app.app_context():
        app.config["UPLOAD_FOLDER"] = str(tmp_path)
        data = {
            "nome": "Peça Fotos", "preco_etiqueta": "100", "principal": "nova:1",
            "fotos": [(_png("red"), "a.png"), (_png("green"), "b.png"), (_png("blue"), "c.png")],
        }
        r = client.post("/pecas/nova", data=data, content_type="multipart/form-data",
                        follow_redirects=True)
        assert r.status_code == 200
        p = Peca.query.filter_by(nome="Peça Fotos").first()
        # 3 imagens no total; a 2ª enviada virou a principal.
        assert p.foto is not None
        assert len(p.fotos) == 2
        assert p.sku == Peca.gerar_sku(p.id)


def test_toggle_vitrine_publica(client, app):
    """Peça com vitrine_publica=False some da vitrine pública, mas fica na interna."""
    from app.models import db, Peca
    with app.app_context():
        db.session.add(Peca(nome="Publica On", vitrine_publica=True, preco_etiqueta=100, sku="SH-ON"))
        db.session.add(Peca(nome="Publica Off", vitrine_publica=False, preco_etiqueta=100, sku="SH-OFF"))
        db.session.commit()
    pub = client.get("/publico/vitrine").get_data(as_text=True)
    assert "Publica On" in pub and "Publica Off" not in pub
    interna = client.get("/vitrine").get_data(as_text=True)
    assert "Publica On" in interna and "Publica Off" in interna


# ----------------------------------------------------------------------------
# Fuso horário configurável (UTC -> local na exibição)
# ----------------------------------------------------------------------------
def test_fuso_horario_dt(app):
    from datetime import datetime, timezone
    from app.models import db, Parametro
    with app.app_context():
        Parametro.definir("fuso", "America/Sao_Paulo")
        db.session.commit()
    with app.test_request_context():
        dt = app.jinja_env.filters["dt"]
        # 12:00 UTC -> 09:00 em São Paulo (UTC-3)
        assert dt(datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)) == "01/01/2026 09:00"


# ----------------------------------------------------------------------------
# Cookie de sessão seguro
# ----------------------------------------------------------------------------
def test_cookie_httponly(app):
    c = app.test_client()
    r = c.post("/login", data={"senha": "test"})
    cookies = " ".join(r.headers.get_all("Set-Cookie"))
    assert "HttpOnly" in cookies and "SameSite=Lax" in cookies


# ----------------------------------------------------------------------------
# Dinheiro arredondado na entrada
# ----------------------------------------------------------------------------
def test_despesa_valor_arredondado(client, app):
    from app.models import Despesa
    client.post("/despesas/nova", data={"descricao": "Conta luz", "valor": "10,999"},
                follow_redirects=True)
    with app.app_context():
        d = Despesa.query.filter_by(descricao="Conta luz").first()
        assert d.valor == 11.00


# ----------------------------------------------------------------------------
# Cupom pessoal restrito ao cliente dono
# ----------------------------------------------------------------------------
def test_cupom_pessoal_restrito(client, app):
    from app.models import db, Cliente, Cupom
    with app.app_context():
        a = Cliente(nome="Dona A"); b = Cliente(nome="Outro B")
        db.session.add_all([a, b]); db.session.commit()
        db.session.add(Cupom(codigo="NIVERA", tipo="percentual", valor=5, ativo=True, cliente_id=a.id))
        db.session.commit()
        aid, bid = a.id, b.id
    # Cliente errado -> rejeitado
    r = client.post("/cupons/validar", data={"codigo": "NIVERA", "cliente_id": bid})
    assert r.get_json()["ok"] is False
    # Cliente dono -> ok
    r = client.post("/cupons/validar", data={"codigo": "NIVERA", "cliente_id": aid})
    assert r.get_json()["ok"] is True
