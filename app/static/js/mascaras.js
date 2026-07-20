/* Máscaras de digitação. Aplica em inputs com data-mask.
   data-mask="tel" -> (00) 00000-0000 (ou fixo com 8 dígitos). */
(function () {
  function fmtTel(v) {
    let d = String(v || '').replace(/\D/g, '');
    if (d.startsWith('55') && d.length > 11) d = d.slice(2);  // remove DDI ao exibir
    d = d.slice(0, 11);
    if (!d) return '';
    let out = '(' + d.slice(0, 2);
    if (d.length >= 3) {
      out += ') ';
      if (d.length <= 6) out += d.slice(2);
      else if (d.length <= 10) out += d.slice(2, 6) + '-' + d.slice(6);
      else out += d.slice(2, 7) + '-' + d.slice(7);
    }
    return out;
  }
  window.mascaraTel = fmtTel;  // reutilizável em outros scripts

  // data-mask="money" -> 0,00 (vírgula decimal, ponto de milhar). Formata da
  // direita p/ esquerda: os 2 últimos dígitos são os centavos.
  function fmtMoney(v) {
    let d = String(v || '').replace(/\D/g, '').replace(/^0+/, '');
    if (!d) return '';
    while (d.length < 3) d = '0' + d;
    const cents = d.slice(-2);
    const int = d.slice(0, -2).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    return int + ',' + cents;
  }
  window.mascaraMoney = fmtMoney;

  document.addEventListener('input', function (e) {
    const t = e.target;
    if (!t || !t.matches) return;
    if (t.matches('[data-mask="tel"]')) t.value = fmtTel(t.value);
    else if (t.matches('[data-mask="money"]')) t.value = fmtMoney(t.value);
  });
  // Formata valores já preenchidos ao carregar.
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-mask="tel"]').forEach(function (i) {
      if (i.value) i.value = fmtTel(i.value);
    });
    document.querySelectorAll('[data-mask="money"]').forEach(function (i) {
      if (i.value) i.value = fmtMoney(i.value);
    });
  });
})();
