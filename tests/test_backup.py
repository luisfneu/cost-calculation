"""Backup: download e restauração pelo painel (admin)."""
import io


def _admin(app):
    c = app.test_client()
    c.post("/login", data={"senha": "test"})
    with c.session_transaction() as s:
        s["admin"] = True
    return c


def test_download_backup(app, seed):
    c = _admin(app)
    r = c.get("/backup")
    assert r.status_code == 200
    assert r.data[:16] == b"SQLite format 3\x00"


def test_restore_arquivo_invalido(app, seed):
    c = _admin(app)
    r = c.post("/backup/restaurar",
               data={"arquivo": (io.BytesIO(b"lixo"), "x.db")},
               content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    assert "não restaurado" in r.get_data(as_text=True)


def test_restore_valido(app, seed):
    c = _admin(app)
    dbbytes = c.get("/backup").data  # backup íntegro do próprio banco de teste
    r = c.post("/backup/restaurar",
               data={"arquivo": (io.BytesIO(dbbytes), "bkp.db")},
               content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    assert "restaurado com sucesso" in r.get_data(as_text=True)


def test_restore_exige_admin(app, seed):
    c = app.test_client()
    c.post("/login", data={"senha": "test"})  # logado, mas não admin
    with c.session_transaction() as s:
        s["admin"] = False
    dbbytes = None
    # gera um .db qualquer válido a partir do backup admin de outro client
    admin = _admin(app)
    dbbytes = admin.get("/backup").data
    r = c.post("/backup/restaurar",
               data={"arquivo": (io.BytesIO(dbbytes), "bkp.db")},
               content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    assert "administradores" in r.get_data(as_text=True)
