"""Regressão: duplicidade de cadastro de cliente (ERP × vitrine) e mesclagem.

Bugs cobertos:
- cliente_rapido criava duplicado mesmo com WhatsApp já cadastrado;
- form_cliente aceitava WhatsApp/CPF de outro cliente;
- CPF duplicado deixava o login por CPF ambíguo (vitrine não checava);
- mesclagem apagava os endereços do duplicado (cascade) e perdia cpf/genero;
- mesclagem recusava cadastros com telefones diferentes mesmo com CPF igual;
- checkout logado atualizava Cliente mas não "Meus endereços" (Endereco).
"""
CPF_OK = "52998224725"     # CPF válido (dígitos verificadores corretos)
CPF_OK2 = "11144477735"    # outro CPF válido


def _novo_cliente(app, **kw):
    from app.models import Cliente, db
    with app.app_context():
        c = Cliente(**kw)
        db.session.add(c)
        db.session.commit()
        return c.id


def test_cliente_rapido_reusa_cadastro_com_mesmo_whatsapp(client, app):
    from app.models import Cliente
    cid = _novo_cliente(app, nome="Ana Balcão", telefone="51988887777", cep="90000-000")
    with app.app_context():
        antes = Cliente.query.count()
    r = client.post("/console/erp/clientes/rapido", data={
        "nome": "Ana B.", "telefone": "(51) 98888-7777",   # mesmo número, formatado
    })
    d = r.get_json()
    assert d["ok"] and d["id"] == cid and d.get("existente") is True
    with app.app_context():
        assert Cliente.query.count() == antes              # não criou duplicado


def test_form_cliente_bloqueia_whatsapp_duplicado(client, app):
    from app.models import Cliente
    _novo_cliente(app, nome="Bia", telefone="51977776666")
    body = client.post("/console/erp/clientes/novo", data={
        "nome": "Beatriz", "telefone": "51977776666",
    }, follow_redirects=True).get_data(as_text=True)
    assert "Já existe um cliente com esse WhatsApp" in body
    with app.app_context():
        assert Cliente.query.filter_by(nome="Beatriz").first() is None


def test_form_cliente_bloqueia_cpf_duplicado(client, app):
    from app.models import Cliente
    _novo_cliente(app, nome="Carla", cpf=CPF_OK)
    body = client.post("/console/erp/clientes/novo", data={
        "nome": "Carolina", "cpf": CPF_OK,
    }, follow_redirects=True).get_data(as_text=True)
    assert "CPF já cadastrado" in body
    with app.app_context():
        assert Cliente.query.filter_by(nome="Carolina").first() is None


def test_cadastro_vitrine_bloqueia_cpf_de_outro(client, app):
    from app.models import Cliente
    _novo_cliente(app, nome="Dona do CPF", telefone="51911112222", cpf=CPF_OK)
    cli = app.test_client()
    r = cli.post("/conta/cadastro", data={
        "nome": "Impostora", "email": "outra@ex.com", "senha": "Segredo1!",
        "telefone": "51933334444", "cpf": CPF_OK,
    }, follow_redirects=True)
    assert "CPF já está cadastrado" in r.get_data(as_text=True)
    with app.app_context():
        assert Cliente.por_email("outra@ex.com") is None


def test_mesclar_preserva_enderecos_e_cpf(client, app):
    from app.models import Cliente, Endereco, db
    pid = _novo_cliente(app, nome="Eva", telefone="51955556666")
    did = _novo_cliente(app, nome="Eva Conta", telefone="51955556666",
                        cpf=CPF_OK, genero="Feminino")
    with app.app_context():
        db.session.add(Endereco(cliente_id=did, apelido="Casa", cep="90000-000",
                                logradouro="Rua A", numero="10", cidade="POA",
                                uf="RS", principal=True, cobranca=True))
        db.session.commit()

    client.post(f"/console/erp/clientes/{pid}/mesclar/{did}", follow_redirects=True)
    with app.app_context():
        assert Cliente.query.get(did) is None
        principal = Cliente.query.get(pid)
        assert principal.cpf == CPF_OK                    # antes se perdia
        assert principal.genero == "Feminino"
        ends = Endereco.query.filter_by(cliente_id=pid).all()
        assert len(ends) == 1 and ends[0].apelido == "Casa"   # antes o cascade apagava
        assert ends[0].principal is True                  # principal não tinha endereços


def test_mesclar_permitido_por_cpf_com_telefones_diferentes(client, app):
    from app.models import Cliente
    pid = _novo_cliente(app, nome="Gi", telefone="51900001111", cpf=CPF_OK2)
    did = _novo_cliente(app, nome="Gi Antiga", telefone="51900002222", cpf=CPF_OK2)
    client.post(f"/console/erp/clientes/{pid}/mesclar/{did}", follow_redirects=True)
    with app.app_context():
        assert Cliente.query.get(did) is None             # antes: recusado


def test_mesclar_sem_identificador_comum_recusa(client, app):
    from app.models import Cliente
    pid = _novo_cliente(app, nome="Hugo", telefone="51900003333")
    did = _novo_cliente(app, nome="Huguinho", telefone="51900004444")
    client.post(f"/console/erp/clientes/{pid}/mesclar/{did}", follow_redirects=True)
    with app.app_context():
        assert Cliente.query.get(did) is not None         # nada mesclado


def test_checkout_logado_sincroniza_meus_enderecos(client, app, seed):
    from app.models import Cliente, Endereco, db
    with app.app_context():
        c = Cliente(nome="Iara", email="iara@ex.com", telefone="51966667777")
        c.set_senha("Segredo1!")
        db.session.add(c)
        db.session.commit()
        cid = c.id
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["cliente_id"] = cid
    r = cli.post("/publico/pedido", json={
        "cliente": {"nome": "Iara", "telefone": "51966667777", "cep": "91000-000",
                    "logradouro": "Rua Nova", "numero": "42", "bairro": "Centro",
                    "cidade": "Porto Alegre", "uf": "rs"},
        "itens": [{"id": seed["peca"], "tam": "M", "qtd": 1}],
    })
    assert r.get_json()["ok"]
    with app.app_context():
        end = Endereco.query.filter_by(cliente_id=cid, principal=True).first()
        assert end is not None                            # antes: só o Cliente mudava
        assert end.logradouro == "Rua Nova" and end.numero == "42"
        assert end.uf == "RS"
