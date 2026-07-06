"""Inventário, estoque mínimo, reserva e disponibilidade na venda."""


def test_inventario_ajusta_e_define_minimo(client, app, seed):
    from app.models import Peca
    pid = seed["peca"]
    client.post("/console/erp/estoque/inventario", data={
        f"cont_{pid}_P": "2", f"min_{pid}_P": "5", f"min_{pid}_M": "5",
    })  # P=2<5 e M=3<5 ficam abaixo do mínimo
    with app.app_context():
        p = Peca.query.get(pid)
        assert p.estoque_por_tamanho["P"] == 2.0
        assert p.minimo_por_tamanho["P"] == 5.0
        assert p.precisa_repor is True
        tamanhos = [f["tamanho"] for f in p.abaixo_minimo]
        assert "P" in tamanhos and "M" in tamanhos


def test_alerta_minimo_no_painel(client, app, seed):
    pid = seed["peca"]
    client.post("/console/erp/estoque/inventario", data={f"cont_{pid}_P": "1", f"min_{pid}_P": "5"})
    body = client.get("/console/erp/").get_data(as_text=True)
    assert "abaixo do estoque mínimo" in body


def test_reserva_reduz_disponivel(client, app, seed):
    from app.models import Peca
    pid = seed["peca"]  # P tem 5
    client.post(f"/console/erp/pecas/{pid}/estoque/reservar", data={"tamanho": "P", "quantidade": "2"})
    with app.app_context():
        p = Peca.query.get(pid)
        assert p.reservado_por_tamanho["P"] == 2.0
        assert p.disponivel_por_tamanho["P"] == 3.0


def test_reserva_nao_excede_estoque(client, app, seed):
    from app.models import Peca
    pid = seed["peca"]
    r = client.post(f"/console/erp/pecas/{pid}/estoque/reservar",
                    data={"tamanho": "P", "quantidade": "99"}, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        assert Peca.query.get(pid).reservado_por_tamanho["P"] == 0.0


def test_liberar_reserva(client, app, seed):
    from app.models import Peca
    pid = seed["peca"]
    client.post(f"/console/erp/pecas/{pid}/estoque/reservar", data={"tamanho": "P", "quantidade": "3"})
    client.post(f"/console/erp/pecas/{pid}/estoque/liberar-reserva", data={"tamanho": "P", "quantidade": "1"})
    with app.app_context():
        assert Peca.query.get(pid).reservado_por_tamanho["P"] == 2.0


def test_venda_usa_disponivel_no_json(client, app, seed):
    pid = seed["peca"]  # P=5
    client.post(f"/console/erp/pecas/{pid}/estoque/reservar", data={"tamanho": "P", "quantidade": "2"})
    body = client.get("/console/erp/vendas/nova").get_data(as_text=True)
    # a peça aparece no JSON de dados com "P": 3.0 (5 - 2 reservado)
    assert '"P": 3.0' in body
