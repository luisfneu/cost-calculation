"""Garante que o gerador Pix em JS (static/js/pix.js) bate com o do Python.

Se as duas implementações divergirem (ex.: alguém mexe só num lado), o teste
quebra. Requer Node; se não houver, o teste é pulado.
"""
import os
import shutil
import subprocess

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIX_JS = os.path.join(BASE, "app", "static", "js", "pix.js")

CASOS = [
    ("email@exemplo.com", "Sabrina Hansen Ção", "São Paulo", 123.45, "PEDIDO7"),
    ("11999998888", "Atelier", "Rio de Janeiro", 0.0, "PEDIDO1"),
    ("chave-aleatoria-123", "AÇÃITÉ", "Belo Horizonte", 1999.90, "PEDIDO42"),
]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node não instalado")
@pytest.mark.parametrize("chave,nome,cidade,valor,txid", CASOS)
def test_pix_js_igual_python(chave, nome, cidade, valor, txid):
    from app.routes import _pix_payload

    esperado = _pix_payload(chave, nome, cidade, valor=valor, txid=txid)
    js = (
        f"const p=require({PIX_JS!r});"
        f"process.stdout.write(p.payload({chave!r},{nome!r},{cidade!r},{valor},{txid!r}));"
    )
    saida = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True)
    assert saida.stdout == esperado
