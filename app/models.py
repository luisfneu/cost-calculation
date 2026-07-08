"""Modelos de dados (SQLAlchemy).

Domínio:
- Insumo: matéria-prima/aviamento (tecido, etiqueta, linha, botão...) com custo e estoque.
- Peca: peça de vestuário composta por vários insumos + mão de obra + custos extras.
- PecaInsumo: quantidade de cada insumo usada em uma peça (ficha técnica / BOM).
- MovimentoEstoque: histórico de entradas/saídas de estoque dos insumos.
"""
import math
import re
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_conn, _rec):
    """Robustez do SQLite sob o servidor web: espera locks em vez de falhar na
    hora e usa WAL (melhor concorrência de leitura/escrita)."""
    if dbapi_conn.__class__.__module__.startswith("sqlite3"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA busy_timeout=5000")   # espera até 5s por um lock
        cur.execute("PRAGMA journal_mode=WAL")     # concorrência melhor
        cur.close()

# Tamanhos padrão para o estoque das peças.
TAMANHOS = ["PP", "P", "M", "G", "GG"]


def _agora():
    return datetime.now(UTC)


def dinheiro(valor) -> float:
    """Arredonda um valor monetário para 2 casas (meio-para-cima, exato via Decimal).

    Usado em todos os cálculos de R$ para evitar acúmulo de erro de ponto flutuante
    (ex.: somas de subtotais, comissões, parcelas fechando com 1 centavo de diferença).
    """
    try:
        return float(Decimal(str(valor or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError):
        return 0.0


def arredondar_cima(valor, base=5) -> int:
    """Arredonda para cima até o próximo múltiplo de `base` (ex.: 32→35, 36→40).

    Usa Decimal na divisão para não errar por ponto flutuante (35.0 continua 35).
    """
    try:
        v = Decimal(str(valor or 0))
    except (InvalidOperation, ValueError, TypeError):
        return 0
    if v <= 0:
        return 0
    return int(math.ceil(v / Decimal(base))) * base


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
    tipo = db.Column(db.String(60), default="")      # tipo de peça (vestido, blusa, saia...)
    colecao = db.Column(db.String(120), default="")  # coleção a que a peça pertence
    tags = db.Column(db.String(255), default="")     # etiquetas livres, separadas por vírgula
    descricao = db.Column(db.Text, default="")
    foto = db.Column(db.String(255))  # nome do arquivo salvo em static/uploads
    # Se True, a peça aparece na vitrine PÚBLICA (link do cliente). A vitrine
    # interna mostra todas, independente deste campo.
    vitrine_publica = db.Column(db.Boolean, nullable=False, default=True)

    # Custos além dos insumos.
    custo_mao_de_obra = db.Column(db.Float, nullable=False, default=0.0)
    custos_extras = db.Column(db.Float, nullable=False, default=0.0)  # energia, frete, embalagem...

    # Margem de lucro desejada sobre o preço de venda (em %). Ex: 40 => 40%.
    margem_percentual = db.Column(db.Float, nullable=False, default=0.0)

    # Preço "de etiqueta": preço comercial ajustado manualmente. Quando definido,
    # é usado como preço de venda padrão (em vez do preço calculado pela margem).
    preco_etiqueta = db.Column(db.Float, nullable=False, default=0.0)
    # Preço promocional (de/por). Quando > 0, vira o preço efetivo de venda.
    preco_promocional = db.Column(db.Float, nullable=False, default=0.0)
    # Código/SKU único, gerado automaticamente no padrão SH-00000000 (id da peça).
    sku = db.Column(db.String(40), unique=True, default="")

    @staticmethod
    def gerar_sku(peca_id) -> str:
        return f"SH-{peca_id:08d}"

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

    @property
    def reservado_por_tamanho(self) -> dict:
        atual = {e.tamanho: e.reservado for e in self.estoques}
        return {t: atual.get(t, 0.0) for t in TAMANHOS}

    @property
    def disponivel_por_tamanho(self) -> dict:
        """Estoque livre para venda (quantidade − reservado)."""
        atual = {e.tamanho: max(0.0, e.quantidade - e.reservado) for e in self.estoques}
        return {t: atual.get(t, 0.0) for t in TAMANHOS}

    @property
    def disponivel_total(self) -> float:
        return sum(max(0.0, e.quantidade - e.reservado) for e in self.estoques)

    @property
    def reservado_total(self) -> float:
        return sum(e.reservado for e in self.estoques)

    @property
    def minimo_por_tamanho(self) -> dict:
        atual = {e.tamanho: e.estoque_minimo for e in self.estoques}
        return {t: atual.get(t, 0.0) for t in TAMANHOS}

    @property
    def abaixo_minimo(self) -> list:
        """Tamanhos com mínimo definido cujo estoque está abaixo dele."""
        faltas = []
        for e in self.estoques:
            if e.estoque_minimo and e.estoque_minimo > 0 and e.quantidade < e.estoque_minimo:
                faltas.append({
                    "tamanho": e.tamanho, "quantidade": e.quantidade,
                    "minimo": e.estoque_minimo, "faltam": e.estoque_minimo - e.quantidade,
                })
        return sorted(faltas, key=lambda x: TAMANHOS.index(x["tamanho"]) if x["tamanho"] in TAMANHOS else 99)

    @property
    def precisa_repor(self) -> bool:
        return bool(self.abaixo_minimo)

    # ----- Cálculos -----
    @property
    def custo_insumos(self) -> float:
        return dinheiro(sum(item.subtotal for item in self.insumos))

    @property
    def custo_total(self) -> float:
        """Custo de produção da peça."""
        return dinheiro(self.custo_insumos + self.custo_mao_de_obra + self.custos_extras)

    @property
    def preco_venda(self) -> float:
        """Preço de venda aplicando a margem sobre o preço final.

        preço = custo / (1 - margem%).  Margem >= 100% é inválida (retorna 0).
        """
        m = self.margem_percentual / 100.0
        if m >= 1:
            return 0.0
        return dinheiro(self.custo_total / (1 - m))

    @property
    def lucro(self) -> float:
        return dinheiro(self.preco_venda - self.custo_total)

    @property
    def preco_base(self) -> float:
        """Preço 'de' (sem promoção): etiqueta ou o calculado pela margem."""
        return self.preco_etiqueta if self.preco_etiqueta and self.preco_etiqueta > 0 else self.preco_venda

    @property
    def em_promocao(self) -> bool:
        return bool(self.preco_promocional and self.preco_promocional > 0)

    @property
    def preco_etiqueta_efetivo(self) -> float:
        """Preço efetivo de venda: promocional se houver, senão o preço base."""
        return self.preco_promocional if self.em_promocao else self.preco_base

    @property
    def sob_encomenda(self) -> bool:
        """Sem estoque disponível: a peça só sai sob encomenda (feita ao pedir)."""
        return self.disponivel_total <= 0

    @property
    def preco_vitrine(self) -> float:
        """Preço exibido/cobrado na vitrine pública.

        - Sob encomenda: custo de produção arredondado para cima ao próximo
          múltiplo de R$5 (ex.: custo 32 → R$35; custo 36 → R$40).
        - Em estoque: preço efetivo normal (promoção ou preço base).
        """
        if self.sob_encomenda:
            return float(arredondar_cima(self.custo_total, 5))
        return self.preco_etiqueta_efetivo

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
        return dinheiro(self.quantidade * self.insumo.custo_unitario)


class EstoquePeca(db.Model):
    """Quantidade em estoque de uma peça em um determinado tamanho."""

    __tablename__ = "estoque_pecas"

    id = db.Column(db.Integer, primary_key=True)
    peca_id = db.Column(db.Integer, db.ForeignKey("pecas.id"), nullable=False)
    tamanho = db.Column(db.String(5), nullable=False)  # PP, P, M, G, GG
    quantidade = db.Column(db.Float, nullable=False, default=0.0)
    # Estoque mínimo desejado para este tamanho (0 = sem alerta).
    estoque_minimo = db.Column(db.Float, nullable=False, default=0.0)
    # Unidades reservadas (não disponíveis para nova venda).
    reservado = db.Column(db.Float, nullable=False, default=0.0)

    peca = db.relationship("Peca", back_populates="estoques")

    @property
    def disponivel(self) -> float:
        return max(0.0, self.quantidade - self.reservado)


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


class Kit(db.Model):
    """Kit/combo: conjunto de peças vendido por um preço especial."""

    __tablename__ = "kits"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    preco = db.Column(db.Float, nullable=False, default=0.0)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    criado_em = db.Column(db.DateTime, default=_agora)

    itens = db.relationship("KitItem", back_populates="kit", cascade="all, delete-orphan")

    @property
    def preco_normal(self) -> float:
        """Soma dos preços efetivos das peças do kit (para mostrar a economia)."""
        return dinheiro(sum(i.peca.preco_etiqueta_efetivo * i.quantidade for i in self.itens))


class KitItem(db.Model):
    __tablename__ = "kit_itens"

    id = db.Column(db.Integer, primary_key=True)
    kit_id = db.Column(db.Integer, db.ForeignKey("kits.id"), nullable=False)
    peca_id = db.Column(db.Integer, db.ForeignKey("pecas.id"), nullable=False)
    quantidade = db.Column(db.Float, nullable=False, default=1.0)

    kit = db.relationship("Kit", back_populates="itens")
    peca = db.relationship("Peca")


class OrdemProducao(db.Model):
    """Ordem/plano de produção: peças e tamanhos a produzir, com lista de compras."""

    __tablename__ = "ordens_producao"

    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(160), default="")
    status = db.Column(db.String(12), nullable=False, default="aberta")  # aberta | concluida
    criado_em = db.Column(db.DateTime, default=_agora)
    concluido_em = db.Column(db.DateTime)

    itens = db.relationship(
        "OrdemProducaoItem", back_populates="ordem", cascade="all, delete-orphan"
    )

    @property
    def total_unidades(self) -> float:
        return sum(i.quantidade for i in self.itens)

    @property
    def status_label(self) -> str:
        return "Concluída" if self.status == "concluida" else "Aberta"

    @property
    def necessidade_insumos(self) -> dict:
        """Agrega o consumo de insumos: {insumo_id: {"insumo": Insumo, "qtd": float}}."""
        need = {}
        for it in self.itens:
            for pi in it.peca.insumos:
                consumo = pi.quantidade * it.quantidade
                reg = need.setdefault(pi.insumo_id, {"insumo": pi.insumo, "qtd": 0.0})
                reg["qtd"] += consumo
        return need

    @property
    def lista_compras(self) -> list:
        """Insumos cujo estoque não cobre a necessidade da ordem."""
        compras = []
        for reg in self.necessidade_insumos.values():
            ins, precisa = reg["insumo"], reg["qtd"]
            falta = precisa - ins.estoque
            if falta > 0.0001:
                compras.append({
                    "insumo": ins, "precisa": precisa, "estoque": ins.estoque,
                    "comprar": falta, "custo": falta * ins.custo_unitario,
                })
        return sorted(compras, key=lambda x: x["insumo"].nome)

    @property
    def custo_compras(self) -> float:
        return sum(c["custo"] for c in self.lista_compras)

    @property
    def insumos_suficientes(self) -> bool:
        return not self.lista_compras


class OrdemProducaoItem(db.Model):
    __tablename__ = "ordem_producao_itens"

    id = db.Column(db.Integer, primary_key=True)
    ordem_id = db.Column(db.Integer, db.ForeignKey("ordens_producao.id"), nullable=False)
    peca_id = db.Column(db.Integer, db.ForeignKey("pecas.id"), nullable=False)
    tamanho = db.Column(db.String(5), nullable=False)
    quantidade = db.Column(db.Float, nullable=False, default=1.0)

    ordem = db.relationship("OrdemProducao", back_populates="itens")
    peca = db.relationship("Peca")


class Cliente(db.Model):
    """Cliente com dados de contato e histórico de compras."""

    __tablename__ = "clientes"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(160), nullable=False)
    instagram = db.Column(db.String(80), default="")
    telefone = db.Column(db.String(40), default="")
    # E-mail: login da área do cliente na vitrine. Único (case-insensitive via
    # normalização em minúsculas na gravação). Opcional para clientes só de balcão.
    email = db.Column(db.String(160), unique=True)
    # Senha da conta na vitrine (só clientes que criaram login têm hash).
    senha_hash = db.Column(db.String(255), nullable=False, default="")
    # Opt-in de novidades/marketing (preferência da conta).
    aceita_novidades = db.Column(db.Boolean, nullable=False, default=False)
    # Data de nascimento (para lembrete de aniversário).
    nascimento = db.Column(db.Date)
    # Tamanho habitual informado manualmente (sobrepõe o calculado).
    tamanho_habitual = db.Column(db.String(5), default="")

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

    # ----- Conta na vitrine (login por e-mail + senha) -----
    def set_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def conferir_senha(self, senha) -> bool:
        return bool(self.senha_hash) and check_password_hash(self.senha_hash, senha)

    @property
    def tem_conta(self) -> bool:
        """Cliente com login ativo na vitrine (e-mail + senha definidos)."""
        return bool(self.email and self.senha_hash)

    @staticmethod
    def normalizar_email(email: str) -> str:
        return (email or "").strip().lower()

    @classmethod
    def por_email(cls, email: str):
        """Busca por e-mail (case-insensitive). None se vazio."""
        email = cls.normalizar_email(email)
        return cls.query.filter(db.func.lower(cls.email) == email).first() if email else None

    @staticmethod
    def normalizar_whatsapp(telefone: str) -> str:
        """Só dígitos, com DDI 55 se parecer número nacional sem código."""
        d = re.sub(r"\D", "", telefone or "")
        if d and not d.startswith("55") and len(d) <= 11:
            d = "55" + d
        return d

    @classmethod
    def por_whatsapp(cls, telefone: str):
        """Primeiro cliente com o mesmo WhatsApp (dígitos normalizados). None se vazio.
        Prefere um cadastro SEM conta (balcão), candidato natural a ser reivindicado."""
        alvo = cls.normalizar_whatsapp(telefone)
        if not alvo:
            return None
        iguais = [c for c in cls.query.all() if c.whatsapp_numero == alvo]
        iguais.sort(key=lambda c: c.tem_conta)  # sem conta primeiro
        return iguais[0] if iguais else None

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
        return self.normalizar_whatsapp(self.telefone)

    @property
    def telefone_formatado(self) -> str:
        """Telefone com máscara BR: (XX) XXXXX-XXXX ou (XX) XXXX-XXXX."""
        d = re.sub(r"\D", "", self.telefone or "")
        if d.startswith("55") and len(d) > 11:  # remove DDI para exibir
            d = d[2:]
        if len(d) == 11:
            return f"({d[:2]}) {d[2:7]}-{d[7:]}"
        if len(d) == 10:
            return f"({d[:2]}) {d[2:6]}-{d[6:]}"
        return self.telefone or ""

    # ----- Histórico -----
    @property
    def total_compras(self) -> float:
        return dinheiro(sum(v.receita for v in self.vendas))

    @property
    def total_pago(self) -> float:
        return dinheiro(sum(v.receita for v in self.vendas if v.pago))

    @property
    def total_pendente(self) -> float:
        return dinheiro(sum(v.receita for v in self.vendas if not v.pago))

    # ----- CRM: aniversário -----
    @property
    def aniversario_hoje(self) -> bool:
        from datetime import date
        if not self.nascimento:
            return False
        hoje = date.today()
        return (self.nascimento.month, self.nascimento.day) == (hoje.month, hoje.day)

    @property
    def aniversario_no_mes(self) -> bool:
        from datetime import date
        return bool(self.nascimento) and self.nascimento.month == date.today().month

    @property
    def dias_para_aniversario(self):
        """Dias até o próximo aniversário (0 = hoje). None se sem data."""
        from datetime import date
        if not self.nascimento:
            return None
        hoje = date.today()

        def _no_ano(ano):
            try:
                return self.nascimento.replace(year=ano)
            except ValueError:  # 29/02 em ano não bissexto
                return self.nascimento.replace(year=ano, day=28)

        prox = _no_ano(hoje.year)
        if prox < hoje:
            prox = _no_ano(hoje.year + 1)
        return (prox - hoje).days

    @property
    def idade(self):
        from datetime import date
        if not self.nascimento:
            return None
        hoje = date.today()
        return hoje.year - self.nascimento.year - (
            (hoje.month, hoje.day) < (self.nascimento.month, self.nascimento.day)
        )

    # ----- CRM: recência / reativação -----
    @property
    def ultima_compra(self):
        return max((v.criado_em for v in self.vendas), default=None)

    @property
    def dias_desde_ultima_compra(self):
        from datetime import datetime
        u = self.ultima_compra
        if not u:
            return None
        if u.tzinfo is None:
            u = u.replace(tzinfo=UTC)
        return (datetime.now(UTC) - u).days

    def inativo(self, dias=90) -> bool:
        """Comprou antes mas está há 'dias' ou mais sem comprar."""
        d = self.dias_desde_ultima_compra
        return d is not None and d >= dias

    # ----- CRM: tamanho habitual -----
    @property
    def tamanho_frequente(self) -> str:
        """Tamanho mais comprado no histórico (por quantidade)."""
        from collections import Counter
        c = Counter()
        for v in self.vendas:
            for it in v.itens:
                if it.tamanho:
                    c[it.tamanho] += it.quantidade
        mais = c.most_common(1)
        return mais[0][0] if mais else ""

    @property
    def tamanho_preferido(self) -> str:
        """Habitual informado, senão o mais frequente do histórico."""
        return self.tamanho_habitual or self.tamanho_frequente


class Lead(db.Model):
    """Pré-cadastro de cliente vindo da vitrine pública.

    Aguarda a confirmação de um administrador antes de virar Cliente de fato
    (evita cadastrar contatos falsos/spam automaticamente).
    """

    __tablename__ = "leads"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(160), nullable=False)
    instagram = db.Column(db.String(80), default="")
    telefone = db.Column(db.String(40), default="")   # WhatsApp

    cep = db.Column(db.String(12), default="")
    logradouro = db.Column(db.String(160), default="")
    numero = db.Column(db.String(20), default="")
    complemento = db.Column(db.String(80), default="")
    bairro = db.Column(db.String(80), default="")
    cidade = db.Column(db.String(80), default="")
    uf = db.Column(db.String(2), default="")

    observacao = db.Column(db.Text, default="")       # resumo do pedido (texto legível)
    pedido_json = db.Column(db.Text, default="")      # itens/frete/cupom do carrinho (JSON)
    # pendente | confirmado | descartado
    status = db.Column(db.String(20), nullable=False, default="pendente")
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"))
    criado_em = db.Column(db.DateTime, default=_agora)
    confirmado_em = db.Column(db.DateTime)

    cliente = db.relationship("Cliente")

    @property
    def tem_endereco(self) -> bool:
        return bool(self.logradouro or self.cep or self.cidade)

    @property
    def endereco_completo(self) -> str:
        linha1 = self.logradouro or ""
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
        h = (self.instagram or "").strip().rstrip("/").split("/")[-1]
        return h.lstrip("@")

    @property
    def whatsapp_numero(self) -> str:
        d = re.sub(r"\D", "", self.telefone or "")
        if d and not d.startswith("55") and len(d) <= 11:
            d = "55" + d
        return d


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
    # Nome do usuário que registrou a venda (vendedor).
    vendedor = db.Column(db.String(80), default="")
    # Fluxo do pedido: realizado | pago | enviado | entregue.
    status = db.Column(db.String(12), nullable=False, default="realizado")
    # Se o estoque das peças já foi baixado.
    estoque_baixado = db.Column(db.Boolean, nullable=False, default=True)
    # Origem do pedido pela vitrine pública (link ao lead que o gerou).
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id"))

    criado_em = db.Column(db.DateTime, default=_agora)

    lead = db.relationship("Lead", backref="vendas")
    cliente = db.relationship("Cliente", back_populates="vendas")
    itens = db.relationship(
        "VendaItem", back_populates="venda", cascade="all, delete-orphan"
    )
    pagamentos = db.relationship(
        "Pagamento", back_populates="venda", cascade="all, delete-orphan"
    )
    parcelas = db.relationship(
        "Parcela", back_populates="venda", cascade="all, delete-orphan",
        order_by="Parcela.numero",
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

    # Posição de cada status no fluxo. 'crediario' ocupa a etapa de pagamento
    # (o pedido é liberado, mas o valor é recebido em parcelas).
    _POS = {"pre-pedido": -1, "realizado": 0, "pago": 1, "crediario": 1, "enviado": 2, "entregue": 3}

    @property
    def _pos(self) -> int:
        return Venda._POS.get(self.status, 0)

    @property
    def eh_crediario(self) -> bool:
        return self.status == "crediario" or bool(self.parcelas)

    @property
    def eh_pre_pedido(self) -> bool:
        """Pedido feito pela vitrine, aguardando o admin confirmar (não efetivado:
        não baixa estoque nem entra nos relatórios)."""
        return self.status == "pre-pedido"

    @property
    def producao_pendente(self) -> bool:
        """Tem item de encomenda ainda não produzido (bloqueia envio/entrega)."""
        return any(it.produzir and not it.produzido for it in self.itens)

    @property
    def itens_a_produzir(self) -> list:
        return [it for it in self.itens if it.produzir]

    @property
    def status_label(self) -> str:
        return {
            "pre-pedido": "Pré-pedido", "realizado": "Pedido feito", "pago": "Pago",
            "crediario": "Crediário", "enviado": "Enviado", "entregue": "Entregue",
        }.get(self.status, "Pedido feito")

    @property
    def estado_label(self) -> str:
        """Rótulo do estado atual do pedido (considera o pagamento)."""
        if self.status == "pre-pedido":
            return "Pré-pedido · aguardando confirmação"
        if self.status == "entregue":
            return "Entregue"
        if self.status == "enviado":
            return "Enviado"
        if self.status == "crediario" or self.parcelas:
            pagas = sum(1 for p in self.parcelas if p.pago)
            return f"Crediário · {pagas}/{len(self.parcelas)} parcelas pagas"
        if self.status == "pago":
            return "Pago · aguardando envio"
        return "Aguardando pagamento" if self.saldo_receber > 0.01 else "Pago"

    @property
    def fluxo_etapas(self) -> list:
        """Etapas para o stepper visual do pedido."""
        atual = self._pos
        etapas = []
        for i, k in enumerate(Venda.FLUXO):
            label = Venda.FLUXO_LABELS[k]
            if k == "pago" and self.eh_crediario:
                label = "Crediário"
            etapas.append({"key": k, "label": label, "concluido": i < atual, "atual": i == atual})
        return etapas

    @property
    def tipo_label(self) -> str:
        return "Encomenda" if self.tipo == "encomenda" else "Venda"

    @property
    def proximo_status(self) -> str:
        """Próxima etapa do fluxo (ou None se pré-pedido/entregue)."""
        if self.status == "pre-pedido":
            return None   # precisa confirmar o pedido antes de entrar no fluxo
        i = self._pos
        return Venda.FLUXO[i + 1] if i + 1 < len(Venda.FLUXO) else None

    # ----- Crediário (parcelas) -----
    @property
    def crediario_total(self) -> float:
        return sum(p.valor for p in self.parcelas)

    @property
    def crediario_pago(self) -> float:
        return sum(p.valor for p in self.parcelas if p.pago)

    @property
    def crediario_pendente(self) -> float:
        return sum(p.valor for p in self.parcelas if not p.pago)

    @property
    def crediario_quitado(self) -> bool:
        return bool(self.parcelas) and all(p.pago for p in self.parcelas)

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
        return dinheiro(sum(i.subtotal_receita for i in self.itens))

    @property
    def receita_produtos(self) -> float:
        """Mantido = total dos itens. O desconto do pedido NÃO reduz os produtos,
        só o valor final da venda."""
        return self.receita_itens

    @property
    def subtotal_bruto(self) -> float:
        return dinheiro(sum(i.subtotal_bruto for i in self.itens))

    @property
    def desconto_itens(self) -> float:
        return dinheiro(sum(i.desconto for i in self.itens))

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
        return dinheiro(sum(i.subtotal_custo for i in self.itens))

    @property
    def comissao_marketplace(self) -> float:
        return dinheiro(self.receita_itens * (self.marketplace_pct / 100.0))

    @property
    def receita(self) -> float:
        """Valor final: itens + frete (se o cliente paga) − desconto do pedido."""
        return dinheiro(self.receita_itens + (0.0 if self.frete_cortesia else self.frete) - self.desconto_total)

    # ----- Pagamentos -----
    @property
    def taxa_maquininha(self) -> float:
        """Soma das taxas de cartão/maquininha (custo da venda)."""
        return dinheiro(sum(p.valor_taxa for p in self.pagamentos))

    @property
    def total_pago(self) -> float:
        """Soma dos pagamentos recebidos. Sem pagamentos, usa o flag legado 'pago'."""
        if self.pagamentos:
            return dinheiro(sum(p.valor for p in self.pagamentos))
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
        return dinheiro(self.custo_producao + self.comissao_marketplace + frete_custo + self.taxa_maquininha)

    @property
    def lucro(self) -> float:
        return dinheiro(self.receita - self.custo_total)


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
        return dinheiro(self.valor * (self.taxa_pct / 100.0))


class Parcela(db.Model):
    """Parcela de um crediário (venda parcelada, a receber)."""

    __tablename__ = "parcelas"

    id = db.Column(db.Integer, primary_key=True)
    venda_id = db.Column(db.Integer, db.ForeignKey("vendas.id"), nullable=False)
    numero = db.Column(db.Integer, nullable=False, default=1)   # 1..total
    total = db.Column(db.Integer, nullable=False, default=1)    # nº total de parcelas
    valor = db.Column(db.Float, nullable=False, default=0.0)
    vencimento = db.Column(db.Date)
    pago = db.Column(db.Boolean, nullable=False, default=False)
    pago_em = db.Column(db.DateTime)

    venda = db.relationship("Venda", back_populates="parcelas")

    @property
    def vencida(self) -> bool:
        from datetime import date
        return (not self.pago) and self.vencimento is not None and self.vencimento < date.today()

    @property
    def rotulo(self) -> str:
        return f"{self.numero}/{self.total}"


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
    # Item sem estoque no fechamento: precisa ser produzido (aparece em Encomendas).
    produzir = db.Column(db.Boolean, nullable=False, default=False)
    produzido = db.Column(db.Boolean, nullable=False, default=False)  # produção concluída

    venda = db.relationship("Venda", back_populates="itens")
    peca = db.relationship("Peca")

    @property
    def subtotal_bruto(self) -> float:
        return dinheiro(self.preco_unitario * self.quantidade)

    @property
    def subtotal_receita(self) -> float:
        """Subtotal do item já com o desconto do item."""
        return dinheiro(self.subtotal_bruto - self.desconto)

    @property
    def subtotal_custo(self) -> float:
        return dinheiro(self.custo_unitario * self.quantidade)


class Cupom(db.Model):
    """Cupom de desconto promocional aplicável na venda."""

    __tablename__ = "cupons"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(40), unique=True, nullable=False)
    tipo = db.Column(db.String(12), nullable=False, default="percentual")  # percentual | valor | frete
    # % (percentual), R$ (valor) ou R$ limite do desconto no frete (frete).
    # Para tipo='frete': valor em branco (0) = frete 100% grátis; valor
    # preenchido = desconto no frete limitado a esse valor.
    valor = db.Column(db.Float, nullable=False, default=0.0)
    validade = db.Column(db.Date)  # None = sem validade
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    usos = db.Column(db.Integer, nullable=False, default=0)
    max_usos = db.Column(db.Integer)  # None = ilimitado
    # Cupom pessoal (ex.: presente de aniversário). None = cupom geral.
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"))
    cliente = db.relationship("Cliente")
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
        """Desconto sobre o subtotal dos itens. Cupom de frete não entra aqui
        (usar desconto_frete_para) — evita aplicar o mesmo cupom duas vezes."""
        if self.tipo == "frete":
            return 0.0
        if self.tipo == "percentual":
            return round(subtotal * self.valor / 100.0, 2)
        return min(self.valor, subtotal)

    def desconto_frete_para(self, frete: float) -> float:
        """Desconto sobre o valor do frete (só para tipo='frete'). Limitado ao
        próprio frete — nunca gera valor negativo. valor em branco (0) no
        cadastro do cupom = frete 100% grátis; valor preenchido = desconto até
        esse teto."""
        frete = frete or 0.0
        if self.tipo != "frete" or frete <= 0:
            return 0.0
        limite = self.valor if self.valor and self.valor > 0 else frete
        return round(min(limite, frete), 2)


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


class Usuario(db.Model):
    """Usuário do sistema (login individual)."""

    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    login = db.Column(db.String(60), unique=True, nullable=False)
    senha_hash = db.Column(db.String(255), nullable=False, default="")
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    admin = db.Column(db.Boolean, nullable=False, default=False)
    criado_em = db.Column(db.DateTime, default=_agora)

    def set_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def conferir_senha(self, senha) -> bool:
        return bool(self.senha_hash) and check_password_hash(self.senha_hash, senha)


class Auditoria(db.Model):
    """Trilha de auditoria: quem fez o quê e quando (login, vendas, estoque)."""

    __tablename__ = "auditoria"

    id = db.Column(db.Integer, primary_key=True)
    usuario = db.Column(db.String(80), default="")
    acao = db.Column(db.String(40), nullable=False)   # login, logout, venda, estoque...
    detalhe = db.Column(db.String(255), default="")
    criado_em = db.Column(db.DateTime, default=_agora)


class FotoPeca(db.Model):
    """Foto adicional de uma peça (galeria)."""

    __tablename__ = "fotos_peca"

    id = db.Column(db.Integer, primary_key=True)
    peca_id = db.Column(db.Integer, db.ForeignKey("pecas.id"), nullable=False)
    arquivo = db.Column(db.String(255), nullable=False)

    peca = db.relationship("Peca", back_populates="fotos")


class Colecao(db.Model):
    """Coleção do atelier: agrupa peças e tem identidade própria (slogan, foto)."""

    __tablename__ = "colecoes"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), unique=True, nullable=False)
    slogan = db.Column(db.String(255), default="")
    foto = db.Column(db.String(255))  # arquivo em static/uploads
    ativa = db.Column(db.Boolean, nullable=False, default=True)
    criado_em = db.Column(db.DateTime, default=_agora)

    @staticmethod
    def por_nome(nome):
        """Busca uma coleção pelo nome (case-insensitive). None se não houver."""
        if not nome:
            return None
        return Colecao.query.filter(
            db.func.lower(Colecao.nome) == nome.strip().lower()
        ).first()
