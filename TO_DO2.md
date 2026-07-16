# Auditoria completa — pós-refatorações (11/07/2026)

Releitura de todo o código (vendas, catalogo, conta, clientes, helpers, models,
financeiro, sistema, estoque, JS) após a rodada grande de correções e features.
Listagem de bugs, inconsistências, segurança, controles, usabilidade, features,
marketing e financeiro.

**Prioridade sugerida:** itens 1, 2, 3, 6 (notificações/guardas/auditoria) e
26 (filtro de idade no carrinho abandonado) — baratos e são bugs de verdade.

---

## 🐞 A. Bugs e inconsistências encontrados na releitura

1. **Crediário não notifica o cliente** — `receber_pagamentos`, ramo crediário
   (`app/routes/vendas.py`): o ramo dá `commit` e `return` antes do
   `_notificar_etapa_cliente`; a etapa vira "Pagamento aprovado" mas o e-mail
   não sai. Os outros ramos notificam.
2. **"Marcar como enviado" não gera e-mail** — `_STATUS_MIN_ETAPA` mapeia
   status `enviado` → etapa `preparando`, que **não** está em
   `_ETAPAS_NOTIFICAVEIS`. O cliente só é avisado se alguém avançar o stepper
   manualmente até "Pedido enviado". Fix: incluir `preparando` nas notificáveis
   (texto "Preparando envio") ou mapear status enviado → etapa `enviado`.
3. **Avançar etapa de pré-pedido sem guarda** — `avancar_etapa_pedido`
   (`app/routes/vendas.py`) não bloqueia `pre-pedido`: dá para levar um pedido
   não confirmado até "Entregue" no stepper (e disparar e-mails).
   `alterar_status` tem a guarda; esta rota não.
4. **Excluir venda entregue devolve peça ao estoque** — a peça está
   fisicamente com o cliente, mas a exclusão credita estoque (caminho A) ou
   re-entra a produzida (caminho B). Deletar venda entregue deveria ser
   bloqueado (ou ao menos avisar) — hoje só admin consegue, mas o efeito é
   estoque fantasma legítimo.
5. **`crm` pode quebrar com carrinho_em nulo** — `app/routes/clientes.py`:
   `carrinhos.sort(key=lambda x: x["em"] or datetime.min)` mistura datetime
   naive/aware se algum registro vier com tz e outro `None` → `TypeError`.
   Hoje o sync sempre grava os dois juntos; risco baixo, mas o mesmo padrão
   frágil existe em `historico` (`app/routes/estoque.py`, pré-existente).
6. **`receber_pagamento` não audita** — todas as rotas de pagamento chamam
   `_log`, exceto essa (pagamento parcial). Trilha de auditoria com buraco.
7. **`cliente_rapido` devolve `existente:true` mas o JS não avisa** — a tela
   de venda seleciona o cliente reusado silenciosamente; a vendedora pode
   achar que criou cadastro novo com os dados digitados (endereço digitado é
   descartado). Mostrar aviso "cliente já existia".
8. **Duplicação de linha no JSON do pedido público** — duas linhas iguais
   (mesma peça/tam) via JSON forjado criam dois `VendaItem` e duas reservas;
   a UI nunca gera isso e a matemática fecha, mas o pedido fica com linhas
   duplicadas estranhas no ERP. Agregar por (peça, tam) na entrada.
9. **Desconto de cupom em pedido com encomenda incide só sobre o sinal** —
   receita da venda usa preço cheio, mas `desconto_para(subtotal)` usa o
   subtotal-sinal. Comportamento defensável (desconto sobre o que é cobrado
   agora), mas **não documentado** — a dona pode esperar % sobre o preço
   cheio. Documentar ou decidir.
10. **`etiquetas_lote`/`pecas_info` sem teto de ids** — `?ids=` aceita lista
    ilimitada → query `IN` gigante. Cap simples (ex.: 100) evita abuso.
11. **`sitemap.xml` sem cache** — regenera a cada hit, lista todas as peças e
    está `@limiter.exempt` (sem limite). Colocar `@cache.cached` de alguns
    minutos (lembrar: o listener de invalidação limpa o cache inteiro).
12. **`views` conta bots** — crawlers (agora convidados pelo sitemap!) inflam
    o contador. Filtrar user-agents óbvios ou aceitar o ruído — o painel
    "mais vistas" deve ser lido com esse grão de sal.

## 🔒 B. Segurança

13. **Endpoints JSON autenticados `csrf.exempt`** (`favoritos/sync`,
    `carrinho/sync`) — protegidos na prática por SameSite=Lax + JSON
    content-type (form cross-site não envia JSON), mas o padrão mais forte é
    exigir header `X-CSRFToken` (o meta tag existe só no base do ERP).
14. **`conta_sair` via GET** — mesmo CSRF-logout corrigido no ERP existe na
    vitrine (o link "não é você?" do carrinho depende dele). Baixo impacto;
    converter exige mexer no link do JS.
15. **Sem verificação de e-mail na vitrine** — cadastro aceita qualquer
    e-mail sem confirmar posse; o lead→cliente agora **herda e-mail não
    verificado** — um convidado malicioso pode "plantar" o e-mail de terceiro
    num cadastro. Mitigação: só herdar e-mail do lead após confirmação por
    link (Resend já existe) ou marcar como não-verificado.
16. **`sugestoes` (60/min)** revela catálogo por enumeração — público por
    natureza, sem problema real.
17. **Avaliações: aprovação por qualquer usuário logado** — decisão
    consciente (excluir é admin), mas texto malicioso pode ir ao ar por
    vendedor. Considerar aprovar=admin também.
18. **Pendências de rodadas anteriores:** OTP/verificação para reivindicação
    de conta por WhatsApp; CSP com nonces (scripts inline em todo template);
    throttle de login em storage compartilhado se um dia houver >1 worker.

## 🎛️ C. Controles e permissões

19. **Editar venda é aberto a qualquer usuário** — pode trocar
    preços/descontos de venda antiga (lucro histórico protegido, mas receita
    não). Considerar: editar venda `entregue`/antiga = admin.
20. **Devolução sem trilha de motivo** — vale-troca é gerado sem campo
    "motivo" (defeito? tamanho?). Campo + relatório de motivos orienta a
    produção.
21. **`atualizar_preco_etiqueta` não audita** — ajuste de estoque loga;
    mudança de preço não (`_log` ausente). Preço é sensível: auditar.
22. **Sem limite de desconto por vendedor** — desconto manual ilimitado na
    venda. Parametrizar teto (%) para não-admin.
23. **Chave Pix nas Configurações** — já é admin-only; mereceria confirmação
    extra (redigitar) ao alterar (trocar = redirecionar pagamentos).

## 🖱️ D. Usabilidade

### ERP
24. Badge "Avaliações pendentes" no menu Catálogo (igual leads/pré-pedidos) —
    hoje só descobre entrando na tela.
25. `venda_detalhe`: campo rastreio aparece mesmo antes do envio — mostrar só
    a partir de "pago" reduz ruído.
26. CRM: carrinhos abandonados sem filtro de idade ("há mais de X horas") —
    carrinho de 5 minutos atrás não é abandonado; hoje lista tudo.
27. Tela Encomendas: falta previsão de insumos agregada ("para produzir tudo:
    12m tecido X") — a OrdemProducao tem `lista_compras`, Encomendas não.
28. Dashboard: falta atalho "pré-pedidos aguardando" clicável no painel (o
    badge existe no menu, o painel não mostra).
29. Busca global do ERP não acha por SKU parcial nem por código de rastreio.

### Loja
30. Cart: e-mail do convidado não é validado no front (só no servidor, 400
    depois do clique) — validar no blur.
31. PDP: avaliações sem paginação (ok por ora) nem resposta do ateliê
    (feature 50).
32. Guia de medidas é global — peças diferentes (vestido × colete) têm
    medidas diferentes; campo opcional por peça sobrepondo o global.
33. Stepper da conta não mostra data/hora de cada etapa (só a atual) —
    timeline com timestamps exige histórico de etapas (tabela nova, ver 36).
34. Número de favoritos por peça na PDP ("12 pessoas favoritaram") — prova
    social barata.
35. Autocomplete só completa nome; ao escolher sugestão poderia navegar
    direto à peça (datalist não suporta; exigiria dropdown custom).

## 💡 E. Features novas

### ERP
36. **Histórico de etapas do pedido** (tabela `venda_eventos`): timeline
    auditável do que aconteceu e quando; alimenta o stepper com datas (33).
37. **Expiração automática de reserva** — launchd diário (padrão do backup)
    liberando reservas de pré-pedidos com >N dias e avisando no painel.
38. **Etiqueta 50×30 paisagem p/ Niimbot M2** — já mapeado no TODO.md.
39. **Compra de insumos com pedido/fornecedor** — hoje entrada de estoque é
    avulsa; um "pedido de compra" agruparia entradas e daria custo por
    fornecedor.
40. **Metas por coleção** — meta mensal existe; por coleção orienta o que
    produzir.

### Loja
41. **Pix dinâmico + webhook** (Mercado Pago/Efí/Asaas) — maior impacto;
    bloqueado por conta em provedor externo.
42. **Lista de espera por tamanho** — "avise-me" hoje é por peça (favorito);
    por tamanho específico converte melhor ("quero o M").
43. **Página de coleção pública** (`/colecao/<nome>` com slogan+foto que já
    existem no modelo) — hoje coleção é só filtro.
44. **Presente**: opção "é presente" no checkout (embrulho + mensagem).
45. **Cross-sell na PDP**: "combina com" (peças da mesma coleção) — dados já
    existem.

## 📣 F. Marketing

46. **Segmentação + export da lista opt-in** — tela filtrando
    `aceita_novidades` por gênero/tamanho/última compra/aniversário com
    export CSV e links wa.me em massa. (Único item da lista anterior de
    marketing ainda não feito.)
47. **E-mail de carrinho abandonado automático** — o CRM manual existe; job
    diário (launchd) mandando e-mail após 24h fecha o ciclo sozinho.
48. **Cupom de reativação** — CRM já lista inativas 90d; botão "gerar cupom
    VOLTA10" ao lado, igual ao de aniversário.
49. **UTM/origem no pedido** — gravar `?utm_source` do primeiro acesso no
    lead/venda: saber se Instagram ou WhatsApp vende mais.
50. **Pós-entrega + review** — e-mail de "entregue" já sai; incluir CTA
    "avalie sua peça" com link direto (o form existe; falta o link no e-mail).
51. **Instagram feed na vitrine** — seção com últimos posts (embed) dá vida à
    home.

## 💰 G. Financeiro

52. **Contabilidade ignora taxa de maquininha nas saídas** —
    `taxa_maquininha` entra no custo da venda (lucro correto), mas o
    ledger/fluxo de caixa não mostra a taxa como saída — o "recebido" é o
    bruto. Mostrar líquido de cartão no mês.
53. **Sem regime de competência × caixa** — relatório mistura: receita por
    data da venda, recebido por pagamento. Consistente internamente, mas um
    seletor "competência/caixa" evita confusão em fechamento de mês.
54. **Crediário sem juros/multa** — parcela vencida não calcula encargo; se a
    política é sem juros, ok — documentar.
55. **Custo de mão de obra é estático por peça** — não há taxa/hora central;
    mudar o valor da hora exige editar peça por peça. Parametrizar
    `valor_hora` + horas por peça.
56. **DRE simplificado** — com os dados atuais (receita, CMV=custo_producao,
    comissões, taxas, despesas por categoria) dá para montar um DRE mensal de
    uma tela.
57. **Exportação contábil** — CSVs existem (vendas, a receber); falta um
    export único do mês (ledger completo) para o contador.
58. **Inventário sem valorização** — o ajuste de inventário corrige
    quantidade mas não reporta a perda/sobra em R$ (a exclusão do ledger
    esconde o custo da perda — correto para caixa, mas a **perda** merece
    relatório próprio).

## 🔧 H. Dívida técnica

59. Agregação SQL nos relatórios/dashboard (ainda "quando doer" — com
    views+favoritos agora há mais varreduras full-table por request).
60. `ruff format` drift em 40+ arquivos — decidir: formatar tudo num commit
    isolado ou remover a menção do CLAUDE.md.
61. Testes: 196 passam, mas não há teste de carga/concorrência para as
    reservas (gthread + SQLite busy_timeout cobre, não comprovado).
62. `.env` acumulando chaves — um validador no boot checando
    presença/formato (hoje só SECRET_KEY/APP_SENHA são checados).
63. Sem monitoramento: `/health` existe, ninguém olha — launchd de 5min com
    `curl` + notificação macOS (`osascript`) avisaria queda.
