"""Modelos de dados (SQLAlchemy).

Domínio:
- Insumo: matéria-prima/aviamento (tecido, etiqueta, linha, botão...) com custo e estoque.
- Peca: peça de vestuário composta por vários insumos + mão de obra + custos extras.
- PecaInsumo: quantidade de cada insumo usada em uma peça (ficha técnica / BOM).
- MovimentoEstoque: histórico de entradas/saídas de estoque dos insumos.
"""
import re
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# Tamanhos padrão para o estoque das peças.
TAMANHOS = ["PP", "P", "M", "G", "GG"]


def _agora():
    return datetime.now(timezone.utc)


class Insumo(db.Model):
    __tablename__ = "insumos"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    # Categoria do insumo: "materia_prima" ou "embalagem".
    tipo = db.Column(db.String(20), nullable=False, default="materia_prima")
    # Unidade de medida: un, m, cm, kg, g, rolo, etc.
    unidade = db.Column(db.String(20), nullable=False, default="un")
    # Custo por unidade de medida (R$).
    custo_unitario = db.Column(db.Float, nullable=False, default=0.0)
    # Onde o insumo foi comprado (fornecedor/loja).
    fornecedor = db.Column(db.String(160), default="")
    # Foto do insumo (nome do arquivo em static/uploads).
    foto = db.Column(db.String(255))
    # Quantidade atual em estoque.
    estoque = db.Column(db.Float, nullable=False, default=0.0)
    # Alerta quando o estoque fica abaixo deste valor.
    estoque_minimo = db.Column(db.Float, nullable=False, default=0.0)
    # Insumo inativo não gera alerta de estoque no painel.
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    criado_em = db.Column(db.DateTime, default=_agora)

    usos = db.relationship("PecaInsumo", back_populates="insumo", cascade="all, delete-orphan")
    movimentos = db.relationship(
        "MovimentoEstoque", back_populates="insumo", cascade="all, delete-orphan"
    )

    @property
    def estoque_baixo(self) -> bool:
        return self.estoque <= self.estoque_minimo

    @property
    def tipo_label(self) -> str:
        return {"embalagem": "Embalagem", "materia_prima": "Matéria-prima"}.get(
            self.tipo, "Matéria-prima"
        )


class Peca(db.Model):
    __tablename__ = "pecas"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    colecao = db.Column(db.String(120), default="")  # coleção a que a peça pertence
    tags = db.Column(db.String(255), default="")     # etiquetas livres, separadas por vírgula
    descricao = db.Column(db.Text, default="")
    foto = db.Column(db.String(255))  # nome do arquivo salvo em static/uploads

    # Custos além dos insumos.
    custo_mao_de_obra = db.Column(db.Float, nullable=False, default=0.0)
    custos_extras = db.Column(db.Float, nullable=False, default=0.0)  # energia, frete, embalagem...

    # Margem de lucro desejada sobre o preço de venda (em %). Ex: 40 => 40%.
    margem_percentual = db.Column(db.Float, nullable=False, default=0.0)

    # Preço "de etiqueta": preço comercial ajustado manualmente. Quando definido,
    # é usado como preço de venda padrão (em vez do preço calculado pela margem).
    preco_etiqueta = db.Column(db.Float, nullable=False, default=0.0)

    # Dados de envio (para cálculo de frete): peso em gramas e dimensões em cm.
    peso_g = db.Column(db.Float, nullable=False, default=0.0)
    altura_cm = db.Column(db.Float, nullable=False, default=0.0)
    largura_cm = db.Column(db.Float, nullable=False, default=0.0)
    comprimento_cm = db.Column(db.Float, nullable=False, default=0.0)

    criado_em = db.Column(db.DateTime, default=_agora)

    insumos = db.relationship(
        "PecaInsumo", back_populates="peca", cascade="all, delete-orphan"
    )
    fotos = db.relationship(
        "FotoPeca", back_populates="peca", cascade="all, delete-orphan",
        order_by="FotoPeca.id",
    )
    estoques = db.relationship(
        "EstoquePeca", back_populates="peca", cascade="all, delete-orphan"
    )
    movimentos = db.relationship(
        "MovimentoPeca", back_populates="peca", cascade="all, delete-orphan"
    )

    # ----- Estoque por tamanho -----
    @property
    def estoque_por_tamanho(self) -> dict:
        """Dicionário {tamanho: quantidade} cobrindo todos os TAMANHOS."""
        atual = {e.tamanho: e.quantidade for e in self.estoques}
        return {t: atual.get(t, 0.0) for t in TAMANHOS}

    @property
    def estoque_total(self) -> float:
        return sum(e.quantidade for e in self.estoques)

    # ----- Cálculos -----
    @property
    def custo_insumos(self) -> float:
        return sum(item.subtotal for item in self.insumos)

    @property
    def custo_total(self) -> float:
        """Custo de produção da peça."""
        return self.custo_insumos + self.custo_mao_de_obra + self.custos_extras

    @property
    def preco_venda(self) -> float:
        """Preço de venda aplicando a margem sobre o preço final.

        preço = custo / (1 - margem%).  Margem >= 100% é inválida (retorna 0).
        """
        m = self.margem_percentual / 100.0
        if m >= 1:
            return 0.0
        return self.custo_total / (1 - m)

    @property
    def lucro(self) -> float:
        return self.preco_venda - self.custo_total

    @property
    def preco_etiqueta_efetivo(self) -> float:
        """Preço comercial usado como padrão na venda (etiqueta, ou o calculado)."""
        return self.preco_etiqueta if self.preco_etiqueta and self.preco_etiqueta > 0 else self.preco_venda

    @property
    def tags_lista(self) -> list:
        return [t.strip() for t in (self.tags or "").split(",") if t.strip()]


class PecaInsumo(db.Model):
    """Linha da ficha técnica: qual insumo e quanto é usado em uma peça."""

    __tablename__ = "peca_insumos"

    id = db.Column(db.Integer, primary_key=True)
    peca_id = db.Column(db.Integer, db.ForeignKey("pecas.id"), nullable=False)
    insumo_id = db.Column(db.Integer, db.ForeignKey("insumos.id"), nullable=False)
    quantidade = db.Column(db.Float, nullable=False, default=0.0)

    peca = db.relationship("Peca", back_populates="insumos")
    insumo = db.relationship("Insumo", back_populates="usos")

    @property
    def subtotal(self) -> float:
        return self.quantidade * self.insumo.custo_unitario


class EstoquePeca(db.Model):
    """Quantidade em estoque de uma peça em um determinado tamanho."""

    __tablename__ = "estoque_pecas"

    id = db.Column(db.Integer, primary_key=True)
    peca_id = db.Column(db.Integer, db.ForeignKey("pecas.id"), nullable=False)
    tamanho = db.Column(db.String(5), nullable=False)  # PP, P, M, G, GG
    quantidade = db.Column(db.Float, nullable=False, default=0.0)

    peca = db.relationship("Peca", back_populates="estoques")


class MovimentoPeca(db.Model):
    """Histórico de movimentações do estoque de peças (produção, ajuste, saída)."""

    __tablename__ = "movimentos_peca"

    id = db.Column(db.Integer, primary_key=True)
    peca_id = db.Column(db.Integer, db.ForeignKey("pecas.id"), nullable=False)
    tamanho = db.Column(db.String(5), nullable=False)
    tipo = db.Column(db.String(12), nullable=False)  # "producao", "ajuste", "saida"
    quantidade = db.Column(db.Float, nullable=False, default=0.0)
    observacao = db.Column(db.String(255), default="")
    criado_em = db.Column(db.DateTime, default=_agora)

    peca = db.relationship("Peca", back_populates="movimentos")


class Cliente(db.Model):
    """Cliente com dados de contato e histórico de compras."""

    __tablename__ = "clientes"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(160), nullable=False)
    instagram = db.Column(db.String(80), default="")
    telefone = db.Column(db.String(40), default="")

    # Endereço (opcional) — para envio via Correios.
    cep = db.Column(db.String(12), default="")
    logradouro = db.Column(db.String(160), default="")
    numero = db.Column(db.String(20), default="")
    complemento = db.Column(db.String(80), default="")
    bairro = db.Column(db.String(80), default="")
    cidade = db.Column(db.String(80), default="")
    uf = db.Column(db.String(2), default="")

    criado_em = db.Column(db.DateTime, default=_agora)

    vendas = db.relationship("Venda", back_populates="cliente")

    @property
    def tem_endereco(self) -> bool:
        return bool(self.logradouro or self.cep or self.cidade)

    @property
    def endereco_completo(self) -> str:
        linha1 = self.logradouro
        if self.numero:
            linha1 += f", {self.numero}"
        if self.complemento:
            linha1 += f" - {self.complemento}"
        partes = [p for p in [linha1, self.bairro,
                              " ".join(x for x in [self.cidade, self.uf] if x),
                              f"CEP {self.cep}" if self.cep else ""] if p]
        return " · ".join(partes)

    @property
    def instagram_handle(self) -> str:
        """Handle sem @ e sem URL (para montar o link)."""
        h = (self.instagram or "").strip()
        h = h.rstrip("/").split("/")[-1]  # aceita URL colada
        return h.lstrip("@")

    @property
    def whatsapp_numero(self) -> str:
        """Só dígitos, com DDI 55 se parecer número nacional sem código."""
        d = re.sub(r"\D", "", self.telefone or "")
        if d and not d.startswith("55") and len(d) <= 11:
            d = "55" + d
        return d

    # ----- Histórico -----
    @property
    def total_compras(self) -> float:
        return sum(v.receita for v in self.vendas)

    @property
    def total_pago(self) -> float:
        return sum(v.receita for v in self.vendas if v.pago)

    @property
    def total_pendente(self) -> float:
        return sum(v.receita for v in self.vendas if not v.pago)


class Venda(db.Model):
    """Pedido de venda com um ou mais itens (peças/tamanhos).

    - Comissão de marketplace: custo da venda (% sobre os produtos do pedido).
    - Frete: se "cortesia" (marcado), é custo da venda; se não, é somado à
      receita (o cliente paga).
    Dados de comprador/pagamento e frete/marketplace são do pedido (não do item).
    """

    __tablename__ = "vendas"

    id = db.Column(db.Integer, primary_key=True)

    frete = db.Column(db.Float, nullable=False, default=0.0)            # opcional
    frete_cortesia = db.Column(db.Boolean, nullable=False, default=False)  # frete é cortesia (custo)?
    marketplace_pct = db.Column(db.Float, nullable=False, default=0.0)  # opcional (% sobre os produtos)
    desconto_total = db.Column(db.Float, nullable=False, default=0.0)   # desconto no pedido (R$)
    cupom_codigo = db.Column(db.String(40), default="")  # cupom aplicado (registro)

    # Dados do comprador / pagamento.
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"))  # opcional
    comprador = db.Column(db.String(160), default="")        # legado / texto livre
    forma_pagamento = db.Column(db.String(40), default="")   # Pix, Dinheiro, Cartão...
    pago = db.Column(db.Boolean, nullable=False, default=False)
    vencimento = db.Column(db.Date)  # data de vencimento (venda a prazo/pendente)
    # Tipo: "venda" baixa estoque na criação; "encomenda" não baixa (produz depois).
    tipo = db.Column(db.String(12), nullable=False, default="venda")
    # Fluxo do pedido: realizado | pago | enviado | entregue.
    status = db.Column(db.String(12), nullable=False, default="realizado")
    # Se o estoque das peças já foi baixado.
    estoque_baixado = db.Column(db.Boolean, nullable=False, default=True)

    criado_em = db.Column(db.DateTime, default=_agora)

    cliente = db.relationship("Cliente", back_populates="vendas")
    itens = db.relationship(
        "VendaItem", back_populates="venda", cascade="all, delete-orphan"
    )
    pagamentos = db.relationship(
        "Pagamento", back_populates="venda", cascade="all, delete-orphan"
    )

    @property
    def cliente_nome(self) -> str:
        return self.cliente.nome if self.cliente else (self.comprador or "")

    # Etapas do fluxo do pedido, em ordem.
    FLUXO = ["realizado", "pago", "enviado", "entregue"]

    # Rótulos das etapas do fluxo (usados no stepper).
    FLUXO_LABELS = {
        "realizado": "Pedido feito", "pago": "Pagamento",
        "enviado": "Enviado", "entregue": "Entregue",
    }

    @property
    def status_label(self) -> str:
        return {
            "realizado": "Pedido feito", "pago": "Pago",
            "enviado": "Enviado", "entregue": "Entregue",
        }.get(self.status, "Pedido feito")

    @property
    def estado_label(self) -> str:
        """Rótulo do estado atual do pedido (considera o pagamento)."""
        if self.status == "entregue":
            return "Entregue"
        if self.status == "enviado":
            return "Enviado"
        if self.status == "pago":
            return "Pago · aguardando envio"
        return "Aguardando pagamento" if self.saldo_receber > 0.01 else "Pago"

    @property
    def fluxo_etapas(self) -> list:
        """Etapas para o stepper visual do pedido."""
        try:
            atual = Venda.FLUXO.index(self.status)
        except ValueError:
            atual = 0
        return [
            {"key": k, "label": Venda.FLUXO_LABELS[k], "concluido": i < atual, "atual": i == atual}
            for i, k in enumerate(Venda.FLUXO)
        ]

    @property
    def tipo_label(self) -> str:
        return "Encomenda" if self.tipo == "encomenda" else "Venda"

    @property
    def proximo_status(self) -> str:
        """Próxima etapa do fluxo (ou None se já entregue)."""
        try:
            i = Venda.FLUXO.index(self.status)
            return Venda.FLUXO[i + 1] if i + 1 < len(Venda.FLUXO) else None
        except ValueError:
            return "pago"

    @property
    def vencida(self) -> bool:
        """Pendente e com vencimento no passado."""
        from datetime import date
        return (not self.pago) and self.vencimento is not None and self.vencimento < date.today()

    @property
    def quantidade_total(self) -> float:
        return sum(i.quantidade for i in self.itens)

    @property
    def receita_itens(self) -> float:
        """Total dos itens, já com o desconto de cada item (sem o desconto do pedido)."""
        return sum(i.subtotal_receita for i in self.itens)

    @property
    def receita_produtos(self) -> float:
        """Mantido = total dos itens. O desconto do pedido NÃO reduz os produtos,
        só o valor final da venda."""
        return self.receita_itens

    @property
    def subtotal_bruto(self) -> float:
        return sum(i.subtotal_bruto for i in self.itens)

    @property
    def desconto_itens(self) -> float:
        return sum(i.desconto for i in self.itens)

    @property
    def desconto_geral(self) -> float:
        """Descontos de item + desconto do pedido."""
        return self.desconto_itens + self.desconto_total

    @property
    def desconto_percentual(self) -> float:
        """Quanto o desconto total representa sobre o valor bruto dos itens."""
        return (self.desconto_geral / self.subtotal_bruto * 100.0) if self.subtotal_bruto else 0.0

    @property
    def custo_producao(self) -> float:
        return sum(i.subtotal_custo for i in self.itens)

    @property
    def comissao_marketplace(self) -> float:
        return self.receita_itens * (self.marketplace_pct / 100.0)

    @property
    def receita(self) -> float:
        """Valor final: itens + frete (se o cliente paga) − desconto do pedido."""
        return self.receita_itens + (0.0 if self.frete_cortesia else self.frete) - self.desconto_total

    # ----- Pagamentos -----
    @property
    def taxa_maquininha(self) -> float:
        """Soma das taxas de cartão/maquininha (custo da venda)."""
        return sum(p.valor_taxa for p in self.pagamentos)

    @property
    def total_pago(self) -> float:
        """Soma dos pagamentos recebidos. Sem pagamentos, usa o flag legado 'pago'."""
        if self.pagamentos:
            return sum(p.valor for p in self.pagamentos)
        return self.receita if self.pago else 0.0

    @property
    def saldo_receber(self) -> float:
        return max(0.0, round(self.receita - self.total_pago, 2))

    @property
    def quitado(self) -> bool:
        return self.total_pago >= self.receita - 0.01

    @property
    def custo_total(self) -> float:
        """Produção + comissão + frete (só quando cortesia) + taxa de maquininha."""
        frete_custo = self.frete if self.frete_cortesia else 0.0
        return self.custo_producao + self.comissao_marketplace + frete_custo + self.taxa_maquininha

    @property
    def lucro(self) -> float:
        return self.receita - self.custo_total


class Pagamento(db.Model):
    """Pagamento recebido de uma venda (permite várias formas por venda)."""

    __tablename__ = "pagamentos"

    id = db.Column(db.Integer, primary_key=True)
    venda_id = db.Column(db.Integer, db.ForeignKey("vendas.id"), nullable=False)
    forma = db.Column(db.String(40), default="")   # Pix, Dinheiro, Cartão crédito...
    valor = db.Column(db.Float, nullable=False, default=0.0)
    parcelas = db.Column(db.Integer, nullable=False, default=1)
    taxa_pct = db.Column(db.Float, nullable=False, default=0.0)  # taxa da maquininha (%)
    criado_em = db.Column(db.DateTime, default=_agora)

    venda = db.relationship("Venda", back_populates="pagamentos")

    @property
    def valor_taxa(self) -> float:
        return self.valor * (self.taxa_pct / 100.0)


class VendaItem(db.Model):
    """Item de um pedido de venda: uma peça em um tamanho, com quantidade."""

    __tablename__ = "venda_itens"

    id = db.Column(db.Integer, primary_key=True)
    venda_id = db.Column(db.Integer, db.ForeignKey("vendas.id"), nullable=False)
    peca_id = db.Column(db.Integer, db.ForeignKey("pecas.id"), nullable=False)
    tamanho = db.Column(db.String(5), nullable=False)
    quantidade = db.Column(db.Float, nullable=False, default=1.0)
    preco_unitario = db.Column(db.Float, nullable=False, default=0.0)
    desconto = db.Column(db.Float, nullable=False, default=0.0)  # desconto do item (R$)
    custo_unitario = db.Column(db.Float, nullable=False, default=0.0)  # snapshot

    venda = db.relationship("Venda", back_populates="itens")
    peca = db.relationship("Peca")

    @property
    def subtotal_bruto(self) -> float:
        return self.preco_unitario * self.quantidade

    @property
    def subtotal_receita(self) -> float:
        """Subtotal do item já com o desconto do item."""
        return self.subtotal_bruto - self.desconto

    @property
    def subtotal_custo(self) -> float:
        return self.custo_unitario * self.quantidade


class Cupom(db.Model):
    """Cupom de desconto promocional aplicável na venda."""

    __tablename__ = "cupons"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(40), unique=True, nullable=False)
    tipo = db.Column(db.String(12), nullable=False, default="percentual")  # percentual | valor
    valor = db.Column(db.Float, nullable=False, default=0.0)  # % ou R$
    validade = db.Column(db.Date)  # None = sem validade
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    usos = db.Column(db.Integer, nullable=False, default=0)
    max_usos = db.Column(db.Integer)  # None = ilimitado
    criado_em = db.Column(db.DateTime, default=_agora)

    @property
    def valido(self) -> bool:
        from datetime import date
        if not self.ativo:
            return False
        if self.validade and self.validade < date.today():
            return False
        if self.max_usos is not None and self.usos >= self.max_usos:
            return False
        return True

    def desconto_para(self, subtotal: float) -> float:
        if self.tipo == "percentual":
            return round(subtotal * self.valor / 100.0, 2)
        return min(self.valor, subtotal)


class Vale(db.Model):
    """Crédito de loja: vale-presente (vendido) ou vale-troca (de devolução)."""

    __tablename__ = "vales"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(40), unique=True, nullable=False)
    tipo = db.Column(db.String(12), nullable=False, default="presente")  # presente | troca
    valor_inicial = db.Column(db.Float, nullable=False, default=0.0)
    saldo = db.Column(db.Float, nullable=False, default=0.0)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"))
    observacao = db.Column(db.String(200), default="")
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    criado_em = db.Column(db.DateTime, default=_agora)

    cliente = db.relationship("Cliente")

    @property
    def tipo_label(self) -> str:
        return "Vale-presente" if self.tipo == "presente" else "Vale-troca"

    @property
    def disponivel(self) -> bool:
        return self.ativo and self.saldo > 0.01


class MovimentoEstoque(db.Model):
    """Registro de entrada (compra) ou saída (produção/ajuste) de um insumo."""

    __tablename__ = "movimentos_estoque"

    id = db.Column(db.Integer, primary_key=True)
    insumo_id = db.Column(db.Integer, db.ForeignKey("insumos.id"), nullable=False)
    tipo = db.Column(db.String(10), nullable=False)  # "entrada" ou "saida"
    quantidade = db.Column(db.Float, nullable=False, default=0.0)
    # Custo unitário no momento do movimento (para custo médio e contabilidade).
    custo_unitario = db.Column(db.Float, nullable=False, default=0.0)
    observacao = db.Column(db.String(255), default="")
    criado_em = db.Column(db.DateTime, default=_agora)

    insumo = db.relationship("Insumo", back_populates="movimentos")

    @property
    def valor(self) -> float:
        return self.quantidade * self.custo_unitario


class Despesa(db.Model):
    """Conta a pagar / despesa da empresa (aluguel, energia, etc.)."""

    __tablename__ = "despesas"

    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(160), nullable=False)
    categoria = db.Column(db.String(60), default="")  # Aluguel, Energia, Pró-labore...
    valor = db.Column(db.Float, nullable=False, default=0.0)
    vencimento = db.Column(db.Date)
    pago = db.Column(db.Boolean, nullable=False, default=False)
    criado_em = db.Column(db.DateTime, default=_agora)

    @property
    def vencida(self) -> bool:
        from datetime import date
        return (not self.pago) and self.vencimento is not None and self.vencimento < date.today()


class Parametro(db.Model):
    """Configurações simples chave/valor (ex.: meta mensal de faturamento)."""

    __tablename__ = "parametros"

    chave = db.Column(db.String(60), primary_key=True)
    valor = db.Column(db.String(255), default="")

    @staticmethod
    def obter(chave, padrao=""):
        p = db.session.get(Parametro, chave)
        return p.valor if p else padrao

    @staticmethod
    def definir(chave, valor):
        p = db.session.get(Parametro, chave)
        if p is None:
            p = Parametro(chave=chave)
            db.session.add(p)
        p.valor = str(valor)


class FotoPeca(db.Model):
    """Foto adicional de uma peça (galeria)."""

    __tablename__ = "fotos_peca"

    id = db.Column(db.Integer, primary_key=True)
    peca_id = db.Column(db.Integer, db.ForeignKey("pecas.id"), nullable=False)
    arquivo = db.Column(db.String(255), nullable=False)

    peca = db.relationship("Peca", back_populates="fotos")
