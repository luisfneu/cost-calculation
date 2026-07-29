#!/usr/bin/env python3
"""Gera os ícones de tela inicial (iOS/Android) da Loja e do ERP.

Fonte da arte: o monograma `sh` de `app/static/monograma.svg` (o mesmo do
favicon). Cada ícone é montado como SVG (mantido em `app/static/` para poder
ser reaproveitado) e rasterizado com `qlmanage` (QuickLook do macOS) em
1024x1024, depois reduzido com Pillow para os tamanhos finais.

    .venv/bin/python gerar_icones.py            # respeita ícones editados à mão
    .venv/bin/python gerar_icones.py --forcar   # regera tudo, apagando edições

**Ícone editado à mão nunca é sobrescrito.** O script guarda o sha256 do que
gerou em `icones-gerados.json`; se o arquivo em disco não bate com esse hash
(ou nem consta no registro), ele é tratado como arte manual e pulado. Vale
também para os SVGs: SVG editado vira a fonte, e os PNGs saem dele.

Por que o PNG é quadrado e opaco: o iOS aplica sozinho a máscara arredondada
no `apple-touch-icon`. Se o arquivo já vier com cantos transparentes, o iOS
preenche o canto com preto. O arredondamento visível vem da moldura interna.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parent
ESTATICO = RAIZ / "app" / "static"
# sha256 de cada arquivo que o script gerou: se o hash de um ícone não bater,
# ele foi editado à mão e o script não encosta nele.
REGISTRO = RAIZ / "icones-gerados.json"

# Paleta de identidade.css
MOCHA = "#b89a78"
CREAM = "#f7f1e6"
GOLD = "#b08a4f"
GOLD_SOFT = "#c9a96a"
INK = "#2c2620"

LADO = 1024  # viewBox de trabalho


def monograma() -> tuple[str, tuple[float, float, float, float]]:
    """Devolve (path `d`, viewBox) do monograma."""
    svg = (ESTATICO / "monograma.svg").read_text()
    d = re.search(r'<path d="(.*?)"', svg, re.S).group(1)
    vb = re.search(r'viewBox="([-\d.\s]+)"', svg).group(1).split()
    return d, tuple(float(v) for v in vb)


PATH, (MX, MY, MW, MH) = monograma()


def _mono(cor: str, largura: float, cy: float) -> str:
    """Monograma pintado de `cor`, com `largura` px, centrado em (LADO/2, cy)."""
    s = largura / MW
    tx = LADO / 2 - largura / 2 - MX * s
    ty = cy - (MH * s) / 2 - MY * s
    return (
        f'<g fill="{cor}" transform="translate({tx:.2f},{ty:.2f}) scale({s:.5f})">'
        f'<g transform="translate(0,1024) scale(0.1,-0.1)"><path d="{PATH}"/></g></g>'
    )


def svg_icone(
    fundo: str,
    tinta: str,
    moldura: str | None,
    texto: str | None = None,
    cor_texto: str = GOLD_SOFT,
    mono_largura: float = 0.66,
    cantos: int = 0,
) -> str:
    """Monta o SVG do ícone.

    `cantos` > 0 arredonda o próprio PNG (uso web/favicon). Para
    `apple-touch-icon` e ícones maskable deve ficar 0 (quadrado, full-bleed).
    """
    partes = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {LADO} {LADO}" '
        f'width="{LADO}" height="{LADO}">',
        f'<rect width="{LADO}" height="{LADO}" rx="{cantos}" fill="{fundo}"/>',
    ]
    if moldura:
        partes.append(
            f'<rect x="76" y="76" width="{LADO - 152}" height="{LADO - 152}" rx="168" '
            f'fill="none" stroke="{moldura}" stroke-width="10" opacity="0.85"/>'
        )
    cy = 452 if texto else 512
    partes.append(_mono(tinta, LADO * mono_largura, cy))
    if texto:
        partes.append(
            f'<text x="{LADO / 2 + 16}" y="740" text-anchor="middle" '
            f'font-family="Didot, Georgia, serif" font-size="132" letter-spacing="32" '
            f'fill="{cor_texto}">{texto}</text>'
        )
    partes.append("</svg>")
    return "".join(partes)


def sha(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def carregar_registro() -> dict[str, str]:
    """Hashes dos arquivos que ESTE script gerou na última execução."""
    if REGISTRO.exists():
        return json.loads(REGISTRO.read_text())
    return {}


def editado_a_mao(caminho: Path, registro: dict[str, str]) -> bool:
    """Arquivo existe mas não bate com o que o script gerou -> é edição manual."""
    if not caminho.exists():
        return False
    return registro.get(caminho.name) != sha(caminho)


def rasterizar(svg: Path) -> Image.Image:
    """SVG -> PNG 1024x1024 via QuickLook."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["qlmanage", "-t", "-s", str(LADO), "-o", tmp, str(svg)],
            check=True,
            capture_output=True,
        )
        saida = next(Path(tmp).glob("*.png"))
        return Image.open(saida).convert("RGBA").copy()


def salvar(img: Image.Image, nome: str, lado: int, alfa: bool = False) -> None:
    fora = img.resize((lado, lado), Image.LANCZOS)
    if not alfa:
        fora = fora.convert("RGB")
    fora.save(ESTATICO / nome, optimize=True)
    print(f"  {nome} ({lado}x{lado})")


ICONES = {
    # nome do SVG: (kwargs do svg_icone, [(arquivo png, lado, alfa)])
    "icone-loja.svg": (
        dict(fundo=MOCHA, tinta=CREAM, moldura=CREAM),
        [
            ("apple-touch-icon.png", 180, False),
            ("icon-192.png", 192, False),
            ("icon-512.png", 512, False),
        ],
    ),
    "icone-erp.svg": (
        dict(fundo=INK, tinta=CREAM, moldura=GOLD, texto="ERP"),
        [
            ("apple-touch-icon-erp.png", 180, False),
            ("icon-erp-192.png", 192, False),
            ("icon-erp-512.png", 512, False),
        ],
    ),
    # Maskable: sem moldura e com monograma menor, para caber na zona segura
    # (80% central) que o Android recorta.
    "icone-loja-maskable.svg": (
        dict(fundo=MOCHA, tinta=CREAM, moldura=None, mono_largura=0.50),
        [("icon-maskable-512.png", 512, False)],
    ),
    "icone-erp-maskable.svg": (
        dict(fundo=INK, tinta=CREAM, moldura=None, texto="ERP", mono_largura=0.50),
        [("icon-erp-maskable-512.png", 512, False)],
    ),
}


def main(forcar: bool = False) -> None:
    if not shutil.which("qlmanage"):
        raise SystemExit("qlmanage não encontrado (script depende do macOS).")
    registro = carregar_registro()
    pulados = []

    for nome_svg, (kw, saidas) in ICONES.items():
        svg = ESTATICO / nome_svg
        # SVG editado à mão vira a fonte da arte: mantém o arquivo e rasteriza a
        # partir dele, em vez de regravar o desenho padrão por cima.
        if editado_a_mao(svg, registro) and not forcar:
            print(f"{nome_svg} (edição manual — usando o arquivo do disco)")
        else:
            svg.write_text(svg_icone(**kw))
            registro[nome_svg] = sha(svg)
            print(nome_svg)

        pendentes = [s for s in saidas if forcar or not editado_a_mao(ESTATICO / s[0], registro)]
        pulados += [s[0] for s in saidas if s not in pendentes]
        if not pendentes:
            continue

        base = rasterizar(svg)
        for arquivo, lado, alfa in pendentes:
            salvar(base, arquivo, lado, alfa)
            registro[arquivo] = sha(ESTATICO / arquivo)

    REGISTRO.write_text(json.dumps(registro, indent=2, sort_keys=True) + "\n")
    for nome in pulados:
        print(f"  pulado (edição manual): {nome}")
    if pulados:
        print("Para sobrescrever mesmo assim: gerar_icones.py --forcar")


if __name__ == "__main__":
    main(forcar="--forcar" in sys.argv)
