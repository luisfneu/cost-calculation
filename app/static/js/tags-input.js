/* Campo de tags com chips: digitar + vírgula (ou Enter) cria uma tag.
   Mantém o valor separado por vírgula no input[hidden name=tags]. */
(function () {
  const box = document.getElementById('tags-box');
  if (!box) return;
  const hidden = document.getElementById('tags-hidden');
  const chipsEl = document.getElementById('tags-chips');
  const entrada = document.getElementById('tags-entrada');

  let tags = (hidden.value || '').split(',').map(t => t.trim()).filter(Boolean);

  function sync() { hidden.value = tags.join(', '); }

  function render() {
    chipsEl.innerHTML = '';
    tags.forEach((t, i) => {
      const chip = document.createElement('span');
      chip.className = 'tag-chip';
      chip.innerHTML = '#' + t + ' <button type="button" data-i="' + i + '" title="Remover">&times;</button>';
      chipsEl.appendChild(chip);
    });
    sync();
  }

  function add(texto) {
    texto = (texto || '').trim().replace(/^#/, '');
    if (texto && !tags.some(t => t.toLowerCase() === texto.toLowerCase())) {
      tags.push(texto);
      render();
    }
  }

  entrada.addEventListener('keydown', function (e) {
    if (e.key === ',' || e.key === 'Enter') {
      e.preventDefault();
      add(entrada.value);
      entrada.value = '';
    } else if (e.key === 'Backspace' && !entrada.value && tags.length) {
      tags.pop();
      render();
    }
  });
  // Ao colar "a, b, c" quebra em várias tags.
  entrada.addEventListener('input', function () {
    if (entrada.value.indexOf(',') !== -1) {
      entrada.value.split(',').forEach(add);
      entrada.value = '';
    }
  });
  // Sair do campo também vira tag (não perde o que foi digitado).
  entrada.addEventListener('blur', function () { add(entrada.value); entrada.value = ''; });
  // Clicar em qualquer parte do box foca a digitação.
  box.addEventListener('click', function (e) { if (e.target === box || e.target === chipsEl) entrada.focus(); });
  chipsEl.addEventListener('click', function (e) {
    const b = e.target.closest('button');
    if (b) { tags.splice(parseInt(b.dataset.i, 10), 1); render(); }
  });

  render();
})();
