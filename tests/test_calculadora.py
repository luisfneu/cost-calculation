"""Calculadora de preço (simulador).

A tela é só leitura e o cálculo roda no navegador — então o que importa testar é
que a matemática do JS bate com a do sistema (`models.py`). Se alguém mexer só
num lado, o preço da calculadora deixa de ser o preço da peça e o teste quebra.
Requer Node; sem ele, os testes de paridade são pulados.
"""

import json
import os
import re
import shutil
import subprocess

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALC_JS = os.path.join(BASE, "app", "static", "js", "calculadora.js")

precisa_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node não instalado")


def js(expressao):
    """Roda uma expressão contra o módulo da calculadora e devolve o resultado."""
    codigo = (
        f"const c=require({CALC_JS!r});"
        f"process.stdout.write(JSON.stringify({expressao}));"
    )
    saida = subprocess.run(["node", "-e", codigo], capture_output=True, text=True, check=True)
    return json.loads(saida.stdout)


# ---- tela ----

def test_calculadora_abre(client):
    r = client.get("/console/erp/calculadora")
    assert r.status_code == 200
    assert "Calculadora de preço" in r.get_data(as_text=True)


def test_calculadora_exige_login(app):
    r = app.test_client().get("/console/erp/calculadora")
    assert r.status_code in (302, 401)


def test_calculadora_lista_insumos_cadastrados(client, seed, app):
    """Insumo do estoque aparece no datalist (conveniência), sem ser obrigatório."""
    from app.models import Insumo
    with app.app_context():
        nome = Insumo.query.first().nome
    assert nome in client.get("/console/erp/calculadora").get_data(as_text=True)


def test_calculadora_lista_pecas_para_copiar(client, seed):
    html = client.get("/console/erp/calculadora").get_data(as_text=True)
    assert "Vestido Flor" in html
    assert 'id="peca_origem"' in html


def test_ficha_da_peca_traz_insumos_e_custos(client, seed, app):
    """A ficha alimenta a calculadora com os valores atuais da peça."""
    from app.models import Peca, db
    with app.app_context():
        peca = db.session.get(Peca, seed["peca"])
        peca.custo_mao_de_obra = 40.0
        peca.custos_extras = 6.5
        peca.margem_percentual = 55.0
        db.session.commit()

    ficha = client.get(f"/console/erp/calculadora/peca/{seed['peca']}.json").get_json()
    assert ficha["nome"] == "Vestido Flor"
    assert ficha["mao_de_obra"] == 40.0
    assert ficha["extras"] == 6.5
    assert ficha["margem"] == 55.0
    assert ficha["preco"] == 200.0          # preço de etiqueta do seed
    # Ficha do seed: 2 m de tecido a R$5 + 1 rolo de linha a R$3.
    por_nome = {i["nome"]: i for i in ficha["insumos"]}
    assert por_nome["Tecido"] == {"nome": "Tecido", "quantidade": 2.0, "unidade": "m", "custo": 5.0}
    assert por_nome["Linha"]["custo"] == 3.0


def test_ficha_bate_com_o_custo_da_peca(client, seed, app):
    """Somar a ficha na calculadora dá o mesmo custo que a peça calcula."""
    from app.models import Peca, db
    with app.app_context():
        peca = db.session.get(Peca, seed["peca"])
        peca.custo_mao_de_obra = 40.0
        peca.custos_extras = 6.5
        db.session.commit()
        custo_peca = peca.custo_total

    ficha = client.get(f"/console/erp/calculadora/peca/{seed['peca']}.json").get_json()
    somado = sum(i["quantidade"] * i["custo"] for i in ficha["insumos"])
    assert somado + ficha["mao_de_obra"] + ficha["extras"] == custo_peca


def test_botao_copiar_aponta_para_a_rota_da_ficha(client, seed):
    """A URL montada no JS (base + id + .json) precisa bater com a rota real."""
    html = client.get("/console/erp/calculadora").get_data(as_text=True)
    base = re.search(r'data-url-base="([^"]+)"', html).group(1)
    assert client.get(f"{base}{seed['peca']}.json").status_code == 200


def test_ficha_de_peca_inexistente_404(client):
    assert client.get("/console/erp/calculadora/peca/99999.json").status_code == 404


def test_ficha_exige_login(app, seed):
    r = app.test_client().get(f"/console/erp/calculadora/peca/{seed['peca']}.json")
    assert r.status_code in (302, 401)


def test_ficha_nao_altera_a_peca(client, seed, app):
    """Leitura pura: carregar a ficha não pode mexer no cadastro."""
    from app.models import Peca, db
    with app.app_context():
        antes = db.session.get(Peca, seed["peca"]).custo_total
    client.get(f"/console/erp/calculadora/peca/{seed['peca']}.json")
    with app.app_context():
        assert db.session.get(Peca, seed["peca"]).custo_total == antes


# ---- paridade JS x Python ----

@precisa_node
@pytest.mark.parametrize("valor", [0, 1.005, 2.675, 10.101, 33.335, 1999.999, 0.001])
def test_dinheiro_igual_python(valor):
    from app.models import dinheiro

    assert js(f"c.dinheiro({valor})") == dinheiro(valor)


@precisa_node
@pytest.mark.parametrize("valor", [0, -3, 1, 5, 5.01, 32, 35.0, 36, 132.4, 1999.99])
def test_arredondar_cima_igual_python(valor):
    from app.models import arredondar_cima

    assert js(f"c.arredondarCima({valor}, 5)") == arredondar_cima(valor, 5)


@precisa_node
@pytest.mark.parametrize(
    "insumos,mao_de_obra,extras",
    [
        ([(2.5, 38.9), (1, 4.75)], 60.0, 12.3),
        ([(0.35, 129.9)], 0.0, 0.0),
        ([], 45.0, 7.77),
        ([(3, 19.99), (0.5, 88.5), (12, 0.85)], 120.5, 33.33),
    ],
)
def test_custo_total_igual_python(insumos, mao_de_obra, extras):
    from app.models import Peca, dinheiro

    esperado = dinheiro(
        sum(dinheiro(q * c) for q, c in insumos) + mao_de_obra + extras
    )
    linhas = json.dumps([{"quantidade": q, "custo": c} for q, c in insumos])
    assert js(f"c.custoTotal({linhas},{mao_de_obra},{extras})") == esperado

    # E o mesmo custo, montado pela peça de verdade (sem insumos na ficha).
    peca = Peca(custo_mao_de_obra=mao_de_obra, custos_extras=extras)
    assert js(f"c.custoTotal([],{mao_de_obra},{extras})") == peca.custo_total


@precisa_node
@pytest.mark.parametrize(
    "custo,margem",
    [(100.0, 40), (87.35, 55), (12.5, 0), (250.0, 99), (250.0, 100), (250.0, 120), (33.33, 62.5)],
)
def test_preco_por_margem_igual_python(custo, margem):
    from app.models import Peca

    peca = Peca(custo_mao_de_obra=custo, custos_extras=0.0, margem_percentual=margem)
    assert js(f"c.precoPorMargem({custo},{margem})") == peca.preco_venda


@precisa_node
@pytest.mark.parametrize(
    "preco,custo", [(200.0, 100.0), (149.9, 87.35), (0.0, 50.0), (80.0, 95.0), (350.0, 132.47)]
)
def test_margem_efetiva_igual_python(preco, custo):
    from app.models import Peca

    peca = Peca(
        custo_mao_de_obra=custo, custos_extras=0.0, preco_etiqueta=preco, margem_percentual=0.0
    )
    assert js(f"c.margemEfetiva({preco},{custo})") == peca.margem_efetiva


@precisa_node
@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("2,4", 2.4),
        ("2.4", 2.4),          # quantidade vinda da ficha de uma peça
        ("1.234,50", 1234.5),  # milhar digitado com ponto
        ("38,9", 38.9),
        ("0,5", 0.5),
        ("", 0),
        ("abc", 0),
    ],
)
def test_numero_le_virgula_e_ponto(texto, esperado):
    """Ponto sem vírgula é decimal — tratá-lo como milhar inflava o custo 10×."""
    assert js(f"c.numero({texto!r})") == esperado


@precisa_node
def test_liquido_desconta_taxa_e_frete():
    """Preço 200, 10% de desconto, 4% de taxa e R$25 de frete bancado."""
    r = js("c.liquido(200, 100, 10, 4, 25)")
    assert r["recebido"] == 147.8   # 180 − 7,20 − 25
    assert r["lucro"] == 47.8
    assert r["margem"] == 32.3


@precisa_node
def test_markup_e_margem_sao_coisas_diferentes():
    """Margem 50% = markup 2× — a confusão clássica que a tela mostra lado a lado."""
    assert js("c.precoPorMargem(100, 50)") == 200.0
    assert js("c.markup(200, 100)") == 2.0
    assert js("c.margemEfetiva(200, 100)") == 50.0
