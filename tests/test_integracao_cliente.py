"""Integração cadastro ERP ↔ vitrine: nunca sobrescrever dados existentes com
valores em branco (reivindicar conta de balcão; confirmar lead de cliente já
cadastrado)."""


def test_reivindicar_conta_sem_endereco_preserva_erp(client, app):
    """Cliente de balcão (ERP) com endereço reivindica a conta na vitrine sem
    redigitar o endereço → o endereço do ERP é preservado."""
    from app.models import Cliente, db
    with app.app_context():
        c = Cliente(nome="Ana ERP", email="ana@ex.com", telefone="51988887777",
                    cep="90000-000", logradouro="Rua A", numero="10",
                    bairro="Centro", cidade="Porto Alegre", uf="RS")
        db.session.add(c); db.session.commit()
        cid = c.id
        assert c.tem_conta is False

    cli = app.test_client()  # visitante da vitrine (sem sessão de cliente)
    r = cli.post("/conta/cadastro", data={
        "nome": "Ana", "email": "ana@ex.com", "senha": "segredo1",
        "telefone": "51988887777",  # endereço em branco de propósito
    })
    assert r.status_code in (302, 200)
    with app.app_context():
        c = Cliente.query.get(cid)
        assert c.tem_conta is True                 # conta reivindicada
        assert c.logradouro == "Rua A"             # endereço do ERP intacto
        assert c.cidade == "Porto Alegre"
        assert c.cep == "90000-000"


def test_reivindicar_conta_com_endereco_atualiza(client, app):
    """Se o cliente preenche o endereço no cadastro, ele atualiza (não é ignorado)."""
    from app.models import Cliente, db
    with app.app_context():
        c = Cliente(nome="Bia", email="bia@ex.com", telefone="51977776666",
                    logradouro="Antiga", cidade="Canoas", uf="RS")
        db.session.add(c); db.session.commit()
        cid = c.id

    cli = app.test_client()
    cli.post("/conta/cadastro", data={
        "nome": "Bia", "email": "bia@ex.com", "senha": "segredo1",
        "telefone": "51977776666",
        "cep": "91000-000", "logradouro": "Rua Nova", "numero": "20",
        "bairro": "Sarandi", "cidade": "Porto Alegre", "uf": "RS",
    })
    with app.app_context():
        c = Cliente.query.get(cid)
        assert c.logradouro == "Rua Nova" and c.cidade == "Porto Alegre"


def test_confirmar_lead_completa_campos_vazios_sem_sobrescrever(client, app):
    """Lead de cliente já existente (mesmo WhatsApp): completa só os campos
    vazios do cliente; não sobrescreve os que o ateliê já tinha."""
    from app.models import Cliente, Lead, db
    with app.app_context():
        c = Cliente(nome="Cadu", telefone="51966665555", cidade="Gravataí")  # sem rua
        db.session.add(c); db.session.commit()
        cid = c.id
        lead = Lead(nome="Cadu", telefone="51966665555",
                    logradouro="Rua do Lead", cidade="Viamão", uf="RS",
                    status="pendente")
        db.session.add(lead); db.session.commit()
        lid = lead.id

    client.post(f"/console/erp/leads/{lid}/confirmar", follow_redirects=True)
    with app.app_context():
        c = Cliente.query.get(cid)
        assert c.logradouro == "Rua do Lead"   # campo vazio → preenchido pelo lead
        assert c.cidade == "Gravataí"          # já tinha → NÃO sobrescrito
        assert c.uf == "RS"                    # vazio → preenchido


def test_cadastro_vitrine_nao_duplica_cadastro_de_balcao(client, app):
    """Cliente de balcão SEM e-mail (só WhatsApp) cria conta na vitrine → reivindica
    o mesmo cadastro pelo WhatsApp em vez de criar um segundo."""
    from app.models import Cliente, db
    with app.app_context():
        c = Cliente(nome="Fernando Neu", telefone="51980291284", instagram="luisfneu")
        db.session.add(c); db.session.commit()
        cid = c.id
        total_antes = Cliente.query.count()

    cli = app.test_client()
    cli.post("/conta/cadastro", data={
        "nome": "Fernando Neu", "email": "luisneu@gmail.com", "senha": "segredo1",
        "telefone": "(51) 98029-1284",  # mesmo número, formatado diferente
    })
    with app.app_context():
        assert Cliente.query.count() == total_antes    # não duplicou
        c = Cliente.query.get(cid)
        assert c.tem_conta and c.email == "luisneu@gmail.com"
        assert c.instagram == "luisfneu"               # dado do balcão preservado


def test_mesclar_clientes_move_pedidos_e_apaga_duplicado(client, app):
    from app.models import Cliente, Venda, db
    with app.app_context():
        principal = Cliente(nome="Fernando Neu", telefone="51980291284",
                            email="luisneu@gmail.com")
        principal.set_senha("x123456")
        dup = Cliente(nome="Fernando Neu", telefone="51980291284", instagram="luisfneu")
        db.session.add_all([principal, dup]); db.session.commit()
        pid, did = principal.id, dup.id
        db.session.add(Venda(status="realizado", tipo="venda", cliente_id=did,
                             comprador="Fernando Neu")); db.session.commit()

    client.post(f"/console/erp/clientes/{pid}/mesclar/{did}", follow_redirects=True)
    with app.app_context():
        assert Cliente.query.get(did) is None                 # duplicado apagado
        principal = Cliente.query.get(pid)
        assert principal.instagram == "luisfneu"              # herdou dado do dup
        assert Venda.query.filter_by(cliente_id=pid).count() == 1  # pedido migrou


def _login_cliente(app):
    from app.models import Cliente, db
    with app.app_context():
        c = Cliente(nome="End Teste", email="end@ex.com", telefone="51900000000")
        c.set_senha("segredo1"); db.session.add(c); db.session.commit()
        cid = c.id
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["cliente_id"] = cid
    return cli, cid


def test_enderecos_crud_e_principal(app):
    from app.models import Cliente, Endereco
    cli, cid = _login_cliente(app)
    # 1º endereço → vira principal automaticamente
    cli.post("/conta/enderecos/salvar", data={
        "apelido": "Casa", "cep": "90000-000", "logradouro": "Rua A", "numero": "10",
        "bairro": "Centro", "cidade": "Porto Alegre", "uf": "RS"})
    # 2º endereço marcado principal
    cli.post("/conta/enderecos/salvar", data={
        "apelido": "Trabalho", "logradouro": "Rua B", "numero": "20",
        "cidade": "Canoas", "uf": "RS", "principal": "on"})
    with app.app_context():
        ends = Endereco.query.filter_by(cliente_id=cid).all()
        assert len(ends) == 2
        princ = [e for e in ends if e.principal]
        assert len(princ) == 1 and princ[0].apelido == "Trabalho"
        # principal sincronizado no Cliente (checkout usa isso)
        c = Cliente.query.get(cid)
        assert c.logradouro == "Rua B" and c.cidade == "Canoas"
        casa_id = next(e.id for e in ends if e.apelido == "Casa")

    # tornar "Casa" principal
    cli.post(f"/conta/enderecos/{casa_id}/principal")
    with app.app_context():
        c = Cliente.query.get(cid)
        assert c.logradouro == "Rua A"
        assert Endereco.query.filter_by(cliente_id=cid, principal=True).count() == 1

    # excluir o principal → promove o outro
    cli.post(f"/conta/enderecos/{casa_id}/excluir")
    with app.app_context():
        ends = Endereco.query.filter_by(cliente_id=cid).all()
        assert len(ends) == 1 and ends[0].principal


def test_endereco_nao_vaza_entre_clientes(app):
    from app.models import Cliente, Endereco, db
    cli, cid = _login_cliente(app)
    cli.post("/conta/enderecos/salvar", data={"logradouro": "Minha Rua", "cidade": "POA", "uf": "RS"})
    with app.app_context():
        outro = Cliente(nome="Outro", email="o@ex.com", telefone="51911112222")
        outro.set_senha("segredo1"); db.session.add(outro); db.session.commit()
        eid = Endereco.query.filter_by(cliente_id=cid).first().id
        oid = outro.id
    # outro cliente tenta excluir/editar endereço alheio → 404
    c2 = app.test_client()
    with c2.session_transaction() as s:
        s["cliente_id"] = oid
    assert c2.post(f"/conta/enderecos/{eid}/excluir").status_code == 404
    assert c2.get(f"/conta/enderecos?editar={eid}").status_code == 200  # não mostra o alheio


def test_cpf_invalido_rejeitado_erp(client, app):
    from app.models import Cliente
    r = client.post("/console/erp/clientes/novo",
                    data={"nome": "CPF Ruim", "cpf": "123.456.789-00"})
    assert "inválido" in r.get_data(as_text=True).lower()
    with app.app_context():
        assert Cliente.query.filter_by(nome="CPF Ruim").first() is None  # não salvou


def test_cpf_valido_salvo_normalizado(client, app):
    from app.models import Cliente
    client.post("/console/erp/clientes/novo",
                data={"nome": "CPF Bom", "cpf": "529.982.247-25"}, follow_redirects=True)
    with app.app_context():
        c = Cliente.query.filter_by(nome="CPF Bom").first()
        assert c is not None and c.cpf == "52998224725"   # guardado só dígitos


def test_cpf_invalido_rejeitado_vitrine(app):
    from app.models import Cliente, db
    with app.app_context():
        c = Cliente(nome="Vit", email="vit@ex.com", telefone="51900001111")
        c.set_senha("segredo1"); db.session.add(c); db.session.commit()
        cid = c.id
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["cliente_id"] = cid
    r = cli.post("/conta/preferencias", data={"nome": "Vit", "email": "vit@ex.com", "cpf": "11111111111"})
    assert "inválido" in r.get_data(as_text=True).lower()
    with app.app_context():
        assert (Cliente.query.get(cid).cpf or "") == ""   # não salvou
