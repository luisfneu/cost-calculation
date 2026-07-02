# 🧵 Calculadora de Custos de Confecção

Aplicação web em Python para calcular o **preço de custo** de peças de vestuário,
definir a **margem de lucro / preço de venda**, guardar **foto** de cada peça e
controlar o **estoque de insumos** (tecidos, etiquetas, linhas, botões...).
Sem necessidade de login — todos os dados ficam salvos localmente em SQLite.

## Funcionalidades

- **Insumos / Estoque**: cadastro de matérias-primas com custo por unidade,
  estoque atual, estoque mínimo e alerta de reposição. Entradas e saídas de
  estoque com histórico.
- **Peças**: cadastro com descrição e foto. Ficha técnica (quais insumos e
  quanto de cada) + mão de obra + custos extras.
- **Cálculo automático**:
  - Custo total = insumos + mão de obra + custos extras
  - Preço de venda = custo ÷ (1 − margem%)
  - Lucro por peça
- **Produção**: dá baixa automática no estoque dos insumos ao produzir N peças
  (bloqueia se faltar estoque).
- **Persistência**: banco SQLite em `instance/costcalc.db`; fotos em
  `app/static/uploads/`.

## Tecnologias

Python · Flask · Flask-SQLAlchemy (SQLite) · Jinja2 · Bootstrap 5

## Como rodar

```bash
cd cost-calculation

# 1. Ambiente virtual
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Dependências
pip install -r requirements.txt

# 3. Iniciar
python run.py
```

Acesse **http://127.0.0.1:5000**. O banco e as pastas necessárias são criados
automaticamente no primeiro start.

## Fluxo de uso

1. **Insumos / Estoque** → cadastre tecidos, etiquetas etc. com custo e estoque.
2. **Peças** → crie a peça (com foto opcional) informando mão de obra, custos
   extras e a margem de lucro desejada.
3. Na página da peça, monte a **ficha técnica** adicionando os insumos e as
   quantidades. O preço de venda é calculado na hora.
4. Use **Produzir** para dar baixa no estoque conforme a produção.

## Estrutura

```
cost-calculation/
├── run.py                 # ponto de entrada
├── config.py              # configurações (banco, uploads)
├── requirements.txt
└── app/
    ├── __init__.py        # application factory + filtros de template
    ├── models.py          # Insumo, Peca, PecaInsumo, MovimentoEstoque
    ├── routes.py          # rotas e lógica de cálculo/estoque
    ├── static/            # css e uploads de fotos
    └── templates/         # páginas HTML (Jinja2)
```

## Migrações de banco (Alembic / Flask-Migrate)

O schema é versionado com Alembic. No boot, o app aplica as migrações
automaticamente (`upgrade`); a migração manual antiga ficou só como fallback.

Para mudar o schema (novos campos/tabelas):

```bash
export FLASK_APP=run
# 1) altere os modelos em app/models.py
# 2) gere a migração:
.venv/bin/flask db migrate -m "descrição da mudança"
# 3) revise o arquivo em migrations/versions/ e aplique:
.venv/bin/flask db upgrade
```

Úteis: `flask db current`, `flask db history`, `flask db downgrade`.
O SQLite usa *batch mode* (ALTER TABLE) automaticamente.

## HTTPS na rede local (celular / câmera do scanner)

```bash
./gerar_cert.sh    # gera o certificado com o IP da rede (rode de novo se o IP mudar)
python run.py      # sobe em HTTPS ligado à rede local
```

No celular (mesma rede): `https://<ip-do-notebook>:8000`, aceite o aviso do
certificado uma vez — isso libera a câmera do leitor de QR (contexto seguro).

## Testes

```bash
.venv/bin/python -m pytest
```

## Notas

- Valores aceitam vírgula ou ponto como separador decimal (ex.: `0,50` ou `0.50`).
- Para produção real, troque `SECRET_KEY` por uma variável de ambiente e use um
  servidor WSGI (gunicorn/waitress) no lugar do servidor de desenvolvimento.
