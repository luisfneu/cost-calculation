"""Regressão de segurança: gate de admin no backup, troca de senha fraca
removida, security headers, token de reset não-reutilizável, logout POST,
upload valida conteúdo.
"""
import io


def _client_nao_admin(app):
    """Client logado como usuário comum (não-admin)."""
    from app.models import Usuario, db
    with app.app_context():
        u = Usuario(nome="Vendedora", login="vend", admin=False)
        u.set_senha("s3nh4-vend")
        db.session.add(u)
        db.session.commit()
    cli = app.test_client()
    cli.post("/console/erp/login", data={"login": "vend", "senha": "s3nh4-vend"})
    return cli


def test_backup_exige_admin(app, client):
    cli = _client_nao_admin(app)
    r = cli.get("/console/erp/backup", follow_redirects=True)
    assert "restrito a administradores" in r.get_data(as_text=True)
    # Admin continua conseguindo baixar.
    r = client.get("/console/erp/backup")
    assert r.status_code == 200
    assert r.data[:16] == b"SQLite format 3\x00"


def test_preferencias_nao_troca_senha(app):
    from app.models import Cliente, db
    with app.app_context():
        c = Cliente(nome="Ana", email="ana@ex.com", telefone="51999998888",
                    cpf="52998224725")
        c.set_senha("Original1!")
        db.session.add(c)
        db.session.commit()
        cid = c.id
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["cliente_id"] = cid
    # Ramo antigo aceitava nova_senha fraca aqui — não pode mais ter efeito.
    cli.post("/conta/preferencias", data={
        "nome": "Ana", "email": "ana@ex.com", "telefone": "51999998888",
        "cpf": "529.982.247-25", "nova_senha": "abc123",
    }, follow_redirects=True)
    with app.app_context():
        c = Cliente.query.get(cid)
        assert c.conferir_senha("Original1!")      # senha intacta
        assert not c.conferir_senha("abc123")


def test_security_headers_presentes(client):
    r = client.get("/console/erp/login")
    assert r.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "Referrer-Policy" in r.headers
    assert "Strict-Transport-Security" not in r.headers   # só em HTTPS


def test_token_reset_nao_reutilizavel(app):
    from app.emails import gerar_token_reset
    from app.models import Cliente, db
    with app.app_context():
        c = Cliente(nome="Bea", email="bea@ex.com", telefone="51988887777")
        c.set_senha("Antiga1!")
        db.session.add(c)
        db.session.commit()
        cid = c.id
        token = gerar_token_reset(c)

    cli = app.test_client()
    cli.post(f"/conta/redefinir/{token}", data={"senha": "Novasenha9!"})
    with app.app_context():
        assert Cliente.query.get(cid).conferir_senha("Novasenha9!")

    # Reusar o mesmo token (dentro da 1h): precisa ser recusado.
    cli2 = app.test_client()
    r = cli2.post(f"/conta/redefinir/{token}", data={"senha": "Hacker123!"},
                  follow_redirects=False)
    assert r.status_code == 302 and "login=1" in r.headers["Location"]
    with app.app_context():
        c = Cliente.query.get(cid)
        assert c.conferir_senha("Novasenha9!")     # senha não mudou de novo
        assert not c.conferir_senha("Hacker123!")


def test_logout_so_por_post(client):
    assert client.get("/console/erp/logout").status_code == 405
    r = client.post("/console/erp/logout", follow_redirects=True)
    assert "saiu do sistema" in r.get_data(as_text=True)


def test_upload_recusa_arquivo_que_nao_e_imagem(client, app):
    from app.models import Peca
    client.post("/console/erp/pecas/nova", data={
        "nome": "Peça Upload Falso",
        "fotos": (io.BytesIO(b"<script>alert(1)</script>isto nao e imagem"), "falso.jpg"),
    }, content_type="multipart/form-data", follow_redirects=True)
    with app.app_context():
        p = Peca.query.filter_by(nome="Peça Upload Falso").first()
        assert p is not None
        assert p.foto is None                      # arquivo rejeitado, peça sem foto
