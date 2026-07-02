"""Application factory."""
import os

from flask import Flask

from config import Config
from .models import db


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Garante que as pastas necessárias existem.
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)

    from .routes import bp
    app.register_blueprint(bp)

    @app.template_filter("moeda")
    def moeda(valor):
        """Formata número no padrão brasileiro: R$ 1.234,56."""
        try:
            texto = f"{float(valor):,.2f}"
        except (TypeError, ValueError):
            texto = "0,00"
        texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {texto}"

    @app.template_filter("dt")
    def dt(valor):
        """Formata data/hora: dd/mm/aaaa HH:MM."""
        try:
            return valor.strftime("%d/%m/%Y %H:%M")
        except (TypeError, ValueError, AttributeError):
            return ""

    @app.template_filter("num")
    def num(valor):
        """Número enxuto: 2 casas, sem zeros à direita desnecessários."""
        try:
            return f"{float(valor):g}"
        except (TypeError, ValueError):
            return valor

    with app.app_context():
        legado = _preparar_migracao_vendas()  # renomeia vendas antigas (single-item)
        db.create_all()                        # cria vendas (pedido) e venda_itens
        if legado:
            _copiar_vendas_legadas()           # move dados p/ o novo formato
        _migrar_colunas()                      # ADD COLUMN idempotente

    return app


def _preparar_migracao_vendas():
    """Se a tabela 'vendas' ainda for do formato antigo (single-item, marcada
    pela coluna peca_id), renomeia para 'vendas_legacy' antes do create_all.

    A presença de peca_id é o marcador definitivo do schema antigo — não
    dependemos de 'venda_itens' (que pode ter sido criado antes)."""
    from sqlalchemy import inspect, text

    insp = inspect(db.engine)
    tabelas = insp.get_table_names()
    if "vendas" in tabelas and "peca_id" in {c["name"] for c in insp.get_columns("vendas")}:
        db.session.execute(text("ALTER TABLE vendas RENAME TO vendas_legacy"))
        db.session.commit()
        return True
    return False


def _copiar_vendas_legadas():
    """Copia cada venda antiga para o novo formato: um pedido + um item.
    Idempotente: não duplica itens já existentes."""
    from sqlalchemy import text

    db.session.execute(text(
        "INSERT INTO vendas (id, frete, frete_cortesia, marketplace_pct, "
        "comprador, forma_pagamento, pago, criado_em) "
        "SELECT id, frete, frete_cortesia, marketplace_pct, comprador, "
        "forma_pagamento, pago, criado_em FROM vendas_legacy"
    ))
    db.session.execute(text(
        "INSERT INTO venda_itens (venda_id, peca_id, tamanho, quantidade, "
        "preco_unitario, custo_unitario) "
        "SELECT id, peca_id, tamanho, quantidade, preco_unitario, custo_unitario "
        "FROM vendas_legacy "
        "WHERE id NOT IN (SELECT venda_id FROM venda_itens)"
    ))
    db.session.execute(text("DROP TABLE vendas_legacy"))
    db.session.commit()


def _migrar_colunas():
    """Adiciona colunas novas em tabelas existentes (idempotente)."""
    from sqlalchemy import inspect, text

    esperado = {
        "pecas": {
            "preco_etiqueta": "FLOAT DEFAULT 0", "colecao": "VARCHAR(120) DEFAULT ''",
            "tags": "VARCHAR(255) DEFAULT ''",
            "peso_g": "FLOAT DEFAULT 0", "altura_cm": "FLOAT DEFAULT 0",
            "largura_cm": "FLOAT DEFAULT 0", "comprimento_cm": "FLOAT DEFAULT 0",
            "preco_promocional": "FLOAT DEFAULT 0", "sku": "VARCHAR(40) DEFAULT ''",
        },
        "insumos": {"ativo": "BOOLEAN DEFAULT 1"},
        "vendas": {
            "desconto_total": "FLOAT DEFAULT 0", "cliente_id": "INTEGER", "vencimento": "DATE",
            "status": "VARCHAR(12) DEFAULT 'realizado'", "estoque_baixado": "BOOLEAN DEFAULT 1",
            "tipo": "VARCHAR(12) DEFAULT 'venda'", "cupom_codigo": "VARCHAR(40) DEFAULT ''",
        },
        "venda_itens": {"desconto": "FLOAT DEFAULT 0"},
        "movimentos_estoque": {"custo_unitario": "FLOAT DEFAULT 0"},
        "clientes": {
            "cep": "VARCHAR(12) DEFAULT ''",
            "logradouro": "VARCHAR(160) DEFAULT ''",
            "numero": "VARCHAR(20) DEFAULT ''",
            "complemento": "VARCHAR(80) DEFAULT ''",
            "bairro": "VARCHAR(80) DEFAULT ''",
            "cidade": "VARCHAR(80) DEFAULT ''",
            "uf": "VARCHAR(2) DEFAULT ''",
        },
    }
    insp = inspect(db.engine)
    for tabela, colunas in esperado.items():
        if not insp.has_table(tabela):
            continue
        existentes = {c["name"] for c in insp.get_columns(tabela)}
        for coluna, ddl in colunas.items():
            if coluna not in existentes:
                db.session.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {ddl}"))
    db.session.commit()

    # Normaliza status antigos (orcamento/confirmado) para o novo fluxo.
    if insp.has_table("vendas"):
        db.session.execute(text(
            "UPDATE vendas SET status = CASE "
            "WHEN status='entregue' THEN 'entregue' "
            "WHEN pago=1 THEN 'pago' ELSE 'realizado' END "
            "WHERE status IN ('orcamento','confirmado')"
        ))
        db.session.execute(text(
            "UPDATE vendas SET tipo = CASE WHEN estoque_baixado=1 THEN 'venda' ELSE 'encomenda' END "
            "WHERE tipo IS NULL OR tipo=''"
        ))
        db.session.commit()
