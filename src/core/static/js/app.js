// Petits comportements transverses (sans dépendance) : copie dans le presse-papiers.
document.addEventListener("click", function (event) {
  var button = event.target.closest("[data-copy]");
  if (!button) return;
  var value = button.getAttribute("data-copy");
  navigator.clipboard.writeText(value).then(function () {
    var label = button.textContent;
    button.textContent = "Copié";
    setTimeout(function () { button.textContent = label; }, 1500);
  });
});

// Sélecteur de personne (directory/partials/person_picker.html) : choix puis carte.
function pickerParts(target) {
  var root = document.querySelector('[data-picker="' + target + '"]');
  if (!root) return null;
  return {
    root: root,
    input: root.querySelector('input[type="hidden"]'),
    card: root.querySelector(".picker-selected"),
    search: root.querySelector(".picker-search"),
    query: root.querySelector('input[type="search"]'),
    results: document.getElementById(target + "-results"),
  };
}

document.addEventListener("click", function (event) {
  var pick = event.target.closest("[data-pick-person]");
  if (pick) {
    var parts = pickerParts(pick.getAttribute("data-target") || "requester");
    if (!parts) return;
    parts.input.value = pick.getAttribute("data-pick-person");
    parts.input.dispatchEvent(new Event("change", { bubbles: true }));
    ["name", "email", "entite", "site"].forEach(function (slot) {
      var el = parts.card.querySelector('[data-slot="' + slot + '"]');
      if (el) el.textContent = pick.getAttribute("data-" + slot) || "";
    });
    parts.card.hidden = false;
    parts.search.hidden = true;
    parts.results.innerHTML = "";
    parts.query.value = "";
    return;
  }
  var reset = event.target.closest("[data-picker-reset]");
  if (reset) {
    var p = pickerParts(reset.getAttribute("data-picker-reset"));
    if (!p) return;
    p.input.value = "";
    p.input.dispatchEvent(new Event("change", { bubbles: true }));
    p.card.hidden = true;
    p.search.hidden = false;
    p.query.focus();
  }
});

// Chronomètres en cours : affichage du temps écoulé (hh:mm:ss), y compris après un échange HTMX.
function tickTimers() {
  document.querySelectorAll("[data-timer-start]").forEach(function (el) {
    var start = Date.parse(el.getAttribute("data-timer-start"));
    if (isNaN(start)) return;
    var s = Math.max(0, Math.floor((Date.now() - start) / 1000));
    var pad = function (n) { return String(n).padStart(2, "0"); };
    el.textContent = pad(Math.floor(s / 3600)) + ":" + pad(Math.floor(s / 60) % 60) + ":" + pad(s % 60);
  });
}
setInterval(tickTimers, 1000);
document.addEventListener("DOMContentLoaded", tickTimers);
document.addEventListener("htmx:afterSwap", tickTimers);
