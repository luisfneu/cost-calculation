// Página "Meus favoritos": lê os ids do localStorage (sh_favs), busca os dados
// atuais das peças em /publico/pecas e monta a grade com remover (×) e, no hover,
// selecionar tamanho + Comprar (adiciona ao carrinho compartilhado).
(function () {
  const KEY = 'sh_favs';
  const grid = document.getElementById('favg');
  const vazio = document.getElementById('favg-vazio');
  const contador = document.getElementById('favg-count');
  const badge = document.getElementById('favs-badge');
  if (!grid) return;

  const fmt = v => (parseFloat(v) || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

  function lerFavs() { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { return {}; } }
  function salvarFavs(f) { localStorage.setItem(KEY, JSON.stringify(f)); }
  function atualizarBadge(n) { if (badge) { badge.textContent = n; badge.hidden = n === 0; } }

  function cardHTML(p) {
    const tams = p.tamanhos.map(x =>
      `<option value="${x.t}" data-disp="${x.disp ? 1 : 0}">${x.t}${x.disp ? '' : ' (sob encomenda)'}</option>`).join('');
    const preco = (p.preco_de ? `<span class="favg-de">${fmt(p.preco_de)}</span>` : '') + `<span>${fmt(p.preco)}</span>`;
    return `
      <div class="favg-card" data-id="${p.id}">
        <div class="favg-thumb">
          <button type="button" class="favg-x" data-rem aria-label="Remover">✕</button>
          <a href="${p.url}">${p.foto ? `<img src="${p.foto}" alt="" loading="lazy">` : ''}</a>
          <div class="favg-hover">
            <select class="form-select form-select-sm favg-tam" aria-label="Tamanho">
              <option value="">Tam…</option>${tams}
            </select>
            <button type="button" class="btn btn-sm btn-primary favg-buy">Comprar</button>
          </div>
        </div>
        <div class="favg-nome"><a href="${p.url}" class="text-reset text-decoration-none">${p.nome}</a></div>
        <div class="favg-preco mt-1">${preco}</div>
      </div>`;
  }

  function render(pecas) {
    grid.innerHTML = pecas.map(cardHTML).join('');
    // guarda os dados por id para o Comprar
    grid._pecas = {};
    pecas.forEach(p => { grid._pecas[p.id] = p; });
    if (contador) contador.textContent = pecas.length;
    if (vazio) vazio.hidden = pecas.length > 0;
  }

  async function carregar() {
    const favs = lerFavs();
    const ids = Object.keys(favs);
    atualizarBadge(ids.length);
    if (!ids.length) { render([]); return; }
    try {
      const r = await fetch('/publico/pecas?ids=' + ids.join(','));
      const d = await r.json();
      const pecas = d.pecas || [];
      // remove dos favoritos ids que sumiram da loja (peça oculta/excluída)
      const vivos = new Set(pecas.map(p => String(p.id)));
      let mudou = false;
      ids.forEach(id => { if (!vivos.has(String(id))) { delete favs[id]; mudou = true; } });
      if (mudou) { salvarFavs(favs); atualizarBadge(Object.keys(favs).length); }
      render(pecas);
    } catch (e) { render(Object.values(favs)); }   // offline: mostra o que tem salvo
  }

  grid.addEventListener('click', e => {
    const card = e.target.closest('.favg-card');
    if (!card) return;
    const id = card.dataset.id;
    if (e.target.closest('[data-rem]')) {
      const favs = lerFavs(); delete favs[id]; salvarFavs(favs);
      atualizarBadge(Object.keys(favs).length);
      card.remove();
      const n = grid.querySelectorAll('.favg-card').length;
      if (contador) contador.textContent = n;
      if (vazio) vazio.hidden = n > 0;
      return;
    }
    if (e.target.closest('.favg-buy')) {
      const p = grid._pecas && grid._pecas[id];
      const sel = card.querySelector('.favg-tam');
      if (!p || !sel.value) { sel.classList.add('is-invalid'); setTimeout(() => sel.classList.remove('is-invalid'), 1200); return; }
      const opt = sel.options[sel.selectedIndex];
      const item = { id: p.id, nome: p.nome, preco: p.preco, tam: sel.value,
                     encomenda: p.sob_encomenda || opt.dataset.disp === '0', foto: p.foto || '' };
      if (window.SHCart && window.SHCart.add) window.SHCart.add(item);
    }
  });

  carregar();
})();
