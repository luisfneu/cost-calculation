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
  document.addEventListener('input', function (e) {
    const t = e.target;
    if (t && t.matches && t.matches('[data-mask="tel"]')) {
      t.value = fmtTel(t.value);
    }
  });
  // Formata valores já preenchidos ao carregar.
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-mask="tel"]').forEach(function (i) {
      if (i.value) i.value = fmtTel(i.value);
    });
  });
})();
