/* Calculadora de preço (simulador) — matemática + tela.
 *
 * As funções de cálculo espelham `app/models.py` (dinheiro, arredondar_cima,
 * Peca.custo_total / preco_venda / margem_efetiva). `tests/test_calculadora.py`
 * roda os dois lados e compara: se alguém mexer só aqui, o teste quebra.
 *
 * Nada é salvo no banco — o rascunho fica no localStorage do navegador.
 */
(function (raiz) {
  'use strict';

  // ---- núcleo do cálculo (espelha models.py) ----

  /** Arredonda meio-para-cima em `casas` decimais, partindo da representação
   *  decimal curta do número — o mesmo ponto de partida do Decimal(str(v)) do
   *  Python, para os dois lados fecharem no mesmo centavo. */
  function arredondar(valor, casas) {
    const n = Number(valor);
    if (!isFinite(n)) return 0;
    const s = String(n);
    if (s.indexOf('e') >= 0 || s.indexOf('E') >= 0) return Number(n.toFixed(casas));
    const neg = s[0] === '-';
    const partes = (neg ? s.slice(1) : s).split('.');
    const frac = partes[1] || '';
    if (frac.length <= casas) return n;
    let inteiro = Number(partes[0] + frac.slice(0, casas));
    if (frac.charCodeAt(casas) - 48 >= 5) inteiro += 1;
    const val = inteiro / Math.pow(10, casas);
    return neg ? -val : val;
  }

  /** models.py: dinheiro() — 2 casas, meio-para-cima. */
  function dinheiro(valor) {
    return arredondar(valor, 2);
  }

  /** models.py: arredondar_cima() — próximo múltiplo de `base` (32 → 35). */
  function arredondarCima(valor, base) {
    base = base || 5;
    const v = Number(valor);
    if (!isFinite(v) || v <= 0) return 0;
    return Math.ceil(arredondar(v / base, 9)) * base;
  }

  /** Lê número digitado ou vindo do cadastro.
   *
   *  Com vírgula, os pontos são separador de milhar ("1.234,50" → 1234.5).
   *  Sem vírgula, o ponto é decimal ("2.4" → 2.4) — é assim que a quantidade
   *  chega da ficha de uma peça, e tratá-lo como milhar multiplicava o custo.
   */
  function numero(valor) {
    const s = String(valor == null ? '' : valor).trim();
    if (!s) return 0;
    const normal = s.indexOf(',') >= 0 ? s.replace(/\./g, '').replace(',', '.') : s;
    return Number(normal) || 0;
  }

  /** Soma dos insumos avulsos: [{quantidade, custo}] → R$. */
  function custoInsumos(linhas) {
    let total = 0;
    (linhas || []).forEach(function (l) {
      total += dinheiro((Number(l.quantidade) || 0) * (Number(l.custo) || 0));
    });
    return dinheiro(total);
  }

  /** models.py: Peca.custo_total — insumos + mão de obra + extras. */
  function custoTotal(insumos, maoDeObra, extras) {
    return dinheiro(custoInsumos(insumos) + (Number(maoDeObra) || 0) + (Number(extras) || 0));
  }

  /** models.py: Peca.preco_venda — custo / (1 − margem%). Margem ≥ 100% → 0. */
  function precoPorMargem(custo, margemPercentual) {
    const m = (Number(margemPercentual) || 0) / 100;
    if (m >= 1) return 0;
    return dinheiro((Number(custo) || 0) / (1 - m));
  }

  /** models.py: Peca.margem_efetiva — margem (%) embutida num preço. */
  function margemEfetiva(preco, custo) {
    const p = Number(preco) || 0;
    if (p <= 0) return 0;
    return arredondar((p - (Number(custo) || 0)) / p * 100, 1);
  }

  /** Markup: quantas vezes o custo cabe no preço (2,0 = dobro do custo). */
  function markup(preco, custo) {
    const c = Number(custo) || 0;
    if (c <= 0) return 0;
    return arredondar((Number(preco) || 0) / c, 2);
  }

  /** Quanto sobra de fato: desconto e taxa saem do preço, o frete bancado sai
   *  do bolso. Devolve {recebido, lucro, margem}. */
  function liquido(preco, custo, descontoPct, taxaPct, freteBancado) {
    const p = Number(preco) || 0;
    const comDesconto = dinheiro(p * (1 - (Number(descontoPct) || 0) / 100));
    const taxa = dinheiro(comDesconto * (Number(taxaPct) || 0) / 100);
    const recebido = dinheiro(comDesconto - taxa - (Number(freteBancado) || 0));
    const lucro = dinheiro(recebido - (Number(custo) || 0));
    return { recebido: recebido, lucro: lucro, margem: margemEfetiva(recebido, custo) };
  }

  const calc = {
    arredondar: arredondar,
    numero: numero,
    dinheiro: dinheiro,
    arredondarCima: arredondarCima,
    custoInsumos: custoInsumos,
    custoTotal: custoTotal,
    precoPorMargem: precoPorMargem,
    margemEfetiva: margemEfetiva,
    markup: markup,
    liquido: liquido,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = calc;
  raiz.CalcPeca = calc;

  // ---- tela ----

  if (typeof document === 'undefined') return;
  document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('calc-form');
    if (!form) return;

    const CHAVE = 'sh-calculadora';
    const corpo = document.getElementById('linhas-insumos');
    const catalogo = JSON.parse(document.getElementById('dados-insumos').textContent);
    const MARGENS_CENARIO = [30, 40, 50, 60];

    const brl = (v) => (Number(v) || 0).toLocaleString('pt-BR', {
      style: 'currency', currency: 'BRL',
    });
    const num = calc.numero;
    // Número → texto do campo, sempre com vírgula decimal.
    const txt = (v) => String(v == null ? '' : v).replace('.', ',');
    // Confirmação e aviso do site (modal e toast do base.html). O fallback
    // nativo só entra se a tela for aberta fora do layout do ERP.
    const confirmar = (mensagem, acao) => {
      if (window.confirmarAcao) window.confirmarAcao(mensagem, acao);
      else if (confirm(mensagem)) acao();
    };
    const avisarErro = (mensagem) => {
      if (window.avisar) window.avisar(mensagem, 'erro');
      else alert(mensagem);
    };
    const campo = (id) => document.getElementById(id);
    const valor = (id) => num(campo(id).value);
    const escrever = (id, texto) => { document.getElementById(id).textContent = texto; };

    function novaLinha(dados) {
      const d = dados || {};
      const tr = document.createElement('tr');
      // Os data-rotulo viram o rótulo de cada campo no celular, onde a tabela
      // é estreita demais e a linha vira uma ficha empilhada.
      tr.innerHTML =
        '<td class="td-nome" data-rotulo="Insumo"><div class="d-flex align-items-center gap-1">' +
        '<i class="bi bi-box-seam text-muted marca-estoque d-none" title="Insumo do estoque"></i>' +
        '<input type="text" class="form-control form-control-sm ins-nome" list="lista-insumos"' +
        ' placeholder="Ex.: Tecido tricoline" aria-label="Nome do insumo"></div></td>' +
        '<td data-rotulo="Qtd"><input type="text" inputmode="decimal"' +
        ' class="form-control form-control-sm text-end ins-qtd" value="1" aria-label="Quantidade"></td>' +
        '<td data-rotulo="Unidade"><input type="text" class="form-control form-control-sm ins-un"' +
        ' placeholder="m, un, kg" aria-label="Unidade"></td>' +
        '<td data-rotulo="Custo unit."><input type="text" inputmode="decimal"' +
        ' class="form-control form-control-sm text-end ins-custo" placeholder="0,00"' +
        ' aria-label="Custo unitário"></td>' +
        '<td class="td-sub ins-sub" data-rotulo="Subtotal">R$ 0,00</td>' +
        '<td class="td-acao"><button type="button" class="btn btn-sm btn-outline-danger rem-linha"' +
        ' title="Remover insumo" aria-label="Remover insumo"><i class="bi bi-x-lg"></i></button></td>';
      corpo.appendChild(tr);
      if (d.nome) tr.querySelector('.ins-nome').value = d.nome;
      if (d.quantidade != null) tr.querySelector('.ins-qtd').value = txt(d.quantidade);
      if (d.unidade) tr.querySelector('.ins-un').value = d.unidade;
      if (d.custo != null) tr.querySelector('.ins-custo').value = txt(d.custo);
      if (d.estoque) marcarEstoque(tr, true);
      return tr;
    }

    /** Liga/desliga o selo de "veio do cadastro de insumos" na linha. */
    function marcarEstoque(tr, ligado) {
      tr.dataset.estoque = ligado ? '1' : '';
      tr.querySelector('.marca-estoque').classList.toggle('d-none', !ligado);
    }

    function linhas() {
      return Array.from(corpo.querySelectorAll('tr')).map(function (tr) {
        return {
          nome: tr.querySelector('.ins-nome').value.trim(),
          quantidade: num(tr.querySelector('.ins-qtd').value),
          unidade: tr.querySelector('.ins-un').value.trim(),
          custo: num(tr.querySelector('.ins-custo').value),
          estoque: tr.dataset.estoque === '1',
        };
      });
    }

    function preencherLinha(tr, insumo) {
      tr.querySelector('.ins-custo').value = txt(insumo.custo);
      tr.querySelector('.ins-un').value = insumo.unidade;
      marcarEstoque(tr, true);
    }

    function recalcular() {
      const itens = linhas();
      itens.forEach(function (item, i) {
        corpo.children[i].querySelector('.ins-sub').textContent =
          brl(calc.dinheiro(item.quantidade * item.custo));
      });

      const maoDeObra = calc.dinheiro(valor('mo_hora') * valor('mo_horas') + valor('mo_fixo'));
      const custo = calc.custoTotal(itens, maoDeObra, valor('extras'));
      const margemAlvo = valor('margem');
      const sugerido = calc.precoPorMargem(custo, margemAlvo);
      const redondo = calc.arredondarCima(sugerido, 5);

      const totalInsumos = brl(calc.custoInsumos(itens));
      escrever('r-insumos', totalInsumos);
      escrever('r-insumos-tabela', totalInsumos);
      escrever('r-mo', brl(maoDeObra));
      escrever('r-extras', brl(valor('extras')));
      escrever('r-custo', brl(custo));
      escrever('r-sugerido', brl(sugerido));
      escrever('r-redondo', redondo ? brl(redondo) : '—');
      escrever('r-markup', margemAlvo > 0 && margemAlvo < 100
        ? calc.markup(sugerido, custo).toLocaleString('pt-BR') + '×' : '—');
      escrever('r-lucro-sug', brl(calc.dinheiro(sugerido - custo)));

      // Teste: preço praticado, com desconto/taxa/frete saindo dele.
      const praticado = valor('praticado');
      const liq = calc.liquido(praticado, custo, valor('desconto'), valor('taxa'), valor('frete'));
      const bruto = calc.dinheiro(praticado - custo);
      escrever('t-bruto', brl(bruto));
      escrever('t-margem-bruta', calc.margemEfetiva(praticado, custo).toLocaleString('pt-BR') + '%');
      escrever('t-recebido', brl(liq.recebido));
      escrever('t-lucro', brl(liq.lucro));
      escrever('t-margem', liq.margem.toLocaleString('pt-BR') + '%');
      escrever('t-markup', calc.markup(praticado, custo).toLocaleString('pt-BR') + '×');

      const aviso = document.getElementById('t-aviso');
      aviso.classList.toggle('d-none', !(praticado > 0 && liq.lucro <= 0));

      // Cenários por margem.
      const linhasCenario = MARGENS_CENARIO.map(function (m) {
        const p = calc.precoPorMargem(custo, m);
        return '<tr><td>' + m + '%</td><td class="text-end">' + brl(p) + '</td>' +
          '<td class="text-end">' + brl(calc.arredondarCima(p, 5)) + '</td>' +
          '<td class="text-end">' + brl(calc.dinheiro(p - custo)) + '</td></tr>';
      });
      document.getElementById('cenarios').innerHTML = linhasCenario.join('');

      salvar();
    }

    function estado() {
      const campos = {};
      form.querySelectorAll('input[id]').forEach(function (el) { campos[el.id] = el.value; });
      return { campos: campos, insumos: linhas() };
    }

    function salvar() {
      try { localStorage.setItem(CHAVE, JSON.stringify(estado())); } catch (e) { /* modo privado */ }
    }

    function restaurar() {
      let dados = null;
      try { dados = JSON.parse(localStorage.getItem(CHAVE) || 'null'); } catch (e) { dados = null; }
      if (!dados) { novaLinha(); return false; }
      Object.keys(dados.campos || {}).forEach(function (id) {
        const el = document.getElementById(id);
        if (el) el.value = dados.campos[id];
      });
      (dados.insumos || []).forEach(function (l) {
        novaLinha({
          nome: l.nome, quantidade: l.quantidade, unidade: l.unidade,
          custo: l.custo, estoque: l.estoque,
        });
      });
      if (!corpo.children.length) novaLinha();
      return true;
    }

    // Digitar o nome de um insumo cadastrado puxa custo e unidade do estoque;
    // qualquer outro nome segue avulso. Mexer no custo desfaz o vínculo — o
    // número deixa de ser o do cadastro, então o selo sairia mentindo.
    corpo.addEventListener('input', function (e) {
      const tr = e.target.closest('tr');
      if (e.target.classList.contains('ins-nome')) {
        const achado = catalogo.find((i) => i.nome === e.target.value);
        if (achado) preencherLinha(tr, achado);
        else marcarEstoque(tr, false);
      } else if (e.target.classList.contains('ins-custo') && tr.dataset.estoque === '1') {
        const achado = catalogo.find((i) => i.nome === tr.querySelector('.ins-nome').value);
        if (!achado || num(e.target.value) !== achado.custo) marcarEstoque(tr, false);
      }
      recalcular();
    });
    corpo.addEventListener('click', function (e) {
      const botao = e.target.closest('.rem-linha');
      if (!botao) return;
      botao.closest('tr').remove();
      if (!corpo.children.length) novaLinha();
      recalcular();
    });
    form.addEventListener('input', recalcular);
    form.addEventListener('submit', (e) => e.preventDefault());

    document.getElementById('add-linha').addEventListener('click', function () {
      novaLinha();
      recalcular();
    });

    const selEstoque = document.getElementById('insumo-estoque');
    if (selEstoque) {
      document.getElementById('add-estoque').addEventListener('click', function () {
        const achado = catalogo.find((i) => i.nome === selEstoque.value);
        if (!achado) return;
        // Linha em branco no fim é aproveitada, em vez de deixar sobra vazia.
        const ultima = corpo.lastElementChild;
        const vazia = ultima && !ultima.querySelector('.ins-nome').value.trim() &&
          !num(ultima.querySelector('.ins-custo').value);
        const tr = vazia ? ultima : novaLinha();
        tr.querySelector('.ins-nome').value = achado.nome;
        preencherLinha(tr, achado);
        selEstoque.value = '';
        recalcular();
      });
    }

    const btnPeca = document.getElementById('copiar-peca');
    if (btnPeca) {
      btnPeca.addEventListener('click', function () {
        const sel = document.getElementById('peca_origem');
        if (!sel.value) return;
        function carregar() {
          btnPeca.disabled = true;
          fetch(btnPeca.dataset.urlBase + sel.value + '.json', { credentials: 'same-origin' })
            .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
            .then(function (ficha) {
              corpo.innerHTML = '';
              (ficha.insumos || []).forEach(function (i) {
                // Custo do cadastro → a linha entra marcada como insumo do estoque.
                novaLinha({
                  nome: i.nome, quantidade: i.quantidade, unidade: i.unidade,
                  custo: i.custo, estoque: true,
                });
              });
              if (!corpo.children.length) novaLinha();
              campo('peca_nome').value = ficha.nome || '';
              campo('mo_hora').value = '';
              campo('mo_horas').value = '';
              campo('mo_fixo').value = txt(ficha.mao_de_obra || 0);
              campo('extras').value = txt(ficha.extras || 0);
              campo('margem').value = txt(ficha.margem || 0);
              campo('praticado').value = txt(ficha.preco || 0);
              recalcular();
            })
            .catch(function () { avisarErro('Não foi possível carregar a ficha dessa peça.'); })
            .finally(function () { btnPeca.disabled = false; });
        }

        const temDados = linhas().some((l) => l.nome || l.custo) || valor('praticado') > 0;
        if (temDados) confirmar('Isto substitui o que está na calculadora. Continuar?', carregar);
        else carregar();
      });
    }

    document.getElementById('usar-sugerido').addEventListener('click', function () {
      const custo = calc.custoTotal(linhas(),
        calc.dinheiro(valor('mo_hora') * valor('mo_horas') + valor('mo_fixo')), valor('extras'));
      const redondo = calc.arredondarCima(calc.precoPorMargem(custo, valor('margem')), 5);
      campo('praticado').value = txt(redondo);
      recalcular();
    });

    // Impressão: o cabeçalho da folha só existe no papel, então é preenchido na
    // hora (vale também para Ctrl+P, não só para o botão).
    function prepararImpressao() {
      escrever('print-nome', campo('peca_nome').value.trim() || 'sem nome');
      escrever('print-data', new Date().toLocaleString('pt-BR', {
        dateStyle: 'short', timeStyle: 'short',
      }));
    }
    window.addEventListener('beforeprint', prepararImpressao);
    document.getElementById('imprimir').addEventListener('click', function () {
      prepararImpressao();
      window.print();
    });

    document.getElementById('limpar').addEventListener('click', function () {
      confirmar('Limpar todos os valores da calculadora?', function () {
        try { localStorage.removeItem(CHAVE); } catch (e) { /* modo privado */ }
        form.reset();
        corpo.innerHTML = '';
        novaLinha();
        recalcular();
      });
    });

    document.getElementById('copiar').addEventListener('click', function () {
      const itens = linhas().filter((l) => l.nome || l.custo);
      const texto = [
        'Simulação de preço' + (campo('peca_nome').value ? ' — ' + campo('peca_nome').value : ''),
        '',
        'Insumos:',
      ].concat(
        itens.map((l) => '  - ' + (l.nome || 'sem nome') + ': ' + l.quantidade + ' ' +
          (l.unidade || 'un') + ' x ' + brl(l.custo) + ' = ' + brl(calc.dinheiro(l.quantidade * l.custo))),
        [
          '  Subtotal insumos: ' + document.getElementById('r-insumos').textContent,
          'Mão de obra: ' + document.getElementById('r-mo').textContent,
          'Custos extras: ' + document.getElementById('r-extras').textContent,
          'CUSTO TOTAL: ' + document.getElementById('r-custo').textContent,
          '',
          'Margem desejada: ' + campo('margem').value + '%',
          'Preço sugerido: ' + document.getElementById('r-sugerido').textContent +
            ' (arredondado: ' + document.getElementById('r-redondo').textContent + ')',
          'Preço testado: ' + brl(valor('praticado')) +
            ' → recebe ' + document.getElementById('t-recebido').textContent +
            ', lucro ' + document.getElementById('t-lucro').textContent +
            ' (margem ' + document.getElementById('t-margem').textContent + ')',
        ]
      ).join('\n');
      // O toLocaleString do BRL separa "R$" do número com espaço não-quebrável
      // (U+00A0) — colado fora do navegador vira caractere estranho.
      navigator.clipboard.writeText(texto.replace(/[\u00A0\u202F]/g, ' ')).then(function () {
        const b = document.getElementById('copiar');
        const antes = b.innerHTML;
        b.innerHTML = '<i class="bi bi-check-lg"></i> Copiado';
        setTimeout(function () { b.innerHTML = antes; }, 1500);
      });
    });

    restaurar();
    recalcular();
  });
})(typeof globalThis !== 'undefined' ? globalThis : this);
