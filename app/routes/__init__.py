"""Pacote de rotas. Mantém o blueprint único 'main'."""
import calendar
import csv
import io
import math
import os
import re
import unicodedata
import uuid
from datetime import date, datetime

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

from ..models import (
    TAMANHOS,
    Auditoria,
    Cliente,
    Cupom,
    Despesa,
    EstoquePeca,
    FotoPeca,
    Insumo,
    Kit,
    KitItem,
    MovimentoEstoque,
    MovimentoPeca,
    OrdemProducao,
    OrdemProducaoItem,
    Pagamento,
    Parametro,
    Parcela,
    Peca,
    PecaInsumo,
    Usuario,
    Vale,
    Venda,
    VendaItem,
    db,
)

# ERP: registrado sob /console/erp (ver create_app). Rotas internas do sistema.
bp = Blueprint("main", __name__)
# Público: registrado na raiz. Vitrine + APIs públicas (frete/cupom/pedido) + health.
publico_bp = Blueprint("publico", __name__)


@bp.before_app_request
def _exigir_login():
    # Só protege o ERP (blueprint 'main'). Público, estáticos e health ficam livres.
    if request.blueprint != "main":
        return None
    if request.endpoint == "main.login":
        return None
    if not session.get("logado"):
        return redirect(url_for("main.login", next=request.path))
    return None


@bp.app_context_processor
def _injetar_leads_pendentes():
    """Contador de leads pendentes para o badge no menu (só admin)."""
    if not session.get("admin"):
        return {}
    from ..models import Lead
    try:
        return {"leads_pendentes": Lead.query.filter_by(status="pendente").count()}
    except Exception:  # noqa: BLE001 - tela de erro não deve quebrar por causa do badge
        return {}


# Reexporta helpers para compatibilidade (ex.: testes usam app.routes._pix_payload).
# Importa os módulos de rota para registrá-los no blueprint.
from . import catalogo, clientes, estoque, financeiro, sistema, vendas  # noqa: E402,F401
from .helpers import *  # noqa: E402,F401,F403
