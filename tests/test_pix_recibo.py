"""Pix (BR Code / CRC16), recibo e envio por WhatsApp."""


def test_pix_payload_estrutura_e_crc():
    from app.routes import _pix_crc16, _pix_payload
    pl = _pix_payload("email@exemplo.com", "Sabrina Hansen Ção", "São Paulo",
                      valor=400.0, txid="PEDIDO1")
    assert pl.startswith("000201")
    assert "br.gov.bcb.pix" in pl
    assert "5406400.00" in pl               # valor
    assert "SABRINA HANSEN CAO" in pl       # sem acento, maiúsculo
    assert "SAO PAULO" in pl
    assert _pix_crc16(pl[:-4]) == pl[-4:]   # CRC confere


def test_pix_sem_chave_vazio():
    from app.routes import _pix_payload
    assert _pix_payload("", "Nome", "Cidade", valor=10) == ""


def _cria_venda(app, seed, paga=False):
    from app.models import Pagamento, Venda, VendaItem, db
    with app.app_context():
        v = Venda(cliente_id=seed["cliente"], tipo="venda")
        db.session.add(v)
        db.session.flush()
        v.itens.append(VendaItem(peca_id=seed["peca"], tamanho="P",
                                 quantidade=2, preco_unitario=200))
        if paga:
            v.pagamentos.append(Pagamento(forma="Pix", valor=400))
            v.pago = True
        db.session.commit()
        return v.id


def test_recibo_pagina(client, app, seed):
    vid = _cria_venda(app, seed, paga=True)
    r = client.get(f"/console/erp/vendas/{vid}/recibo")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Total" in body and "quitado" in body


def test_botao_whatsapp_no_detalhe(client, app, seed):
    vid = _cria_venda(app, seed, paga=True)
    body = client.get(f"/console/erp/vendas/{vid}").get_data(as_text=True)
    assert "Enviar recibo" in body
    assert "wa.me/5511999998888" in body


def test_pix_config_no_detalhe(client, app, seed):
    vid = _cria_venda(app, seed, paga=False)  # tem saldo
    # sem config: PIX é null (chave não aparece no JS)
    assert "email@exemplo.com" not in client.get(f"/console/erp/vendas/{vid}").get_data(as_text=True)
    client.post("/console/erp/configuracoes", data={
        "pix_chave": "email@exemplo.com", "pix_nome": "Sabrina",
        "pix_cidade": "Sao Paulo", "meta_mensal": "0",
    })
    body = client.get(f"/console/erp/vendas/{vid}").get_data(as_text=True)
    # com config: a chave entra no PIX do JS e o modal do QR está na página
    assert "email@exemplo.com" in body
    assert 'id="modal-pix"' in body


def test_validar_cupom_endpoint(client, app):
    from datetime import date, timedelta

    from app.models import Cupom, db
    with app.app_context():
        db.session.add(Cupom(codigo="VERAO10", tipo="percentual", valor=10,
                             validade=date.today() + timedelta(days=30)))
        db.session.add(Cupom(codigo="EXPIRADO", tipo="valor", valor=5,
                             validade=date.today() - timedelta(days=1)))
        db.session.commit()

    ok = client.post("/console/erp/cupons/validar", data={"codigo": "verao10"}).get_json()
    assert ok["ok"] is True and ok["tipo"] == "percentual" and ok["valor"] == 10

    exp = client.post("/console/erp/cupons/validar", data={"codigo": "EXPIRADO"}).get_json()
    assert exp["ok"] is False

    nao = client.post("/console/erp/cupons/validar", data={"codigo": "NAOEXISTE"}).get_json()
    assert nao["ok"] is False
