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

// Compteurs de la fiche ticket (HH:MM:SS, secondes ouvrées) : le serveur donne la valeur au
// chargement ; elle avance jusqu'à la fin de la plage ouvrée en cours (data-tick-until).
function tickCounters() {
  var now = Date.now();
  document.querySelectorAll("[data-counter]").forEach(function (el) {
    if (!el.hasAttribute("data-tick-until")) return;
    if (!el._loadedAt) el._loadedAt = now;
    var until = Date.parse(el.getAttribute("data-tick-until"));
    var s = Number(el.getAttribute("data-counter")) + Math.floor((Math.min(now, until) - el._loadedAt) / 1000);
    var pad = function (n) { return String(n).padStart(2, "0"); };
    el.textContent = pad(Math.floor(s / 3600)) + ":" + pad(Math.floor(s / 60) % 60) + ":" + pad(s % 60);
  });
}
setInterval(tickCounters, 1000);
document.addEventListener("DOMContentLoaded", tickCounters);
document.addEventListener("htmx:afterSwap", tickCounters);

// Éditeur enrichi (core/partials/rich_editor.html) : images collées, glissées ou insérées.
// Les images sont intégrées en data: et converties en pièces jointes par le serveur.
var RICH_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];
var RICH_MAX_BYTES = 10 * 1024 * 1024;

function richInit(root) {
  (root || document).querySelectorAll("[data-rich-editor]:not([data-ready])").forEach(function (box) {
    box.setAttribute("data-ready", "");
    var source = box.querySelector("textarea");
    var hidden = box.querySelector('input[type="hidden"]');
    var area = box.querySelector(".rich-area");
    var toolbar = box.querySelector(".rich-toolbar");
    var picker = box.querySelector("[data-rich-file]");
    var error = box.querySelector(".rich-error");
    if (!source || !hidden || !area) return;

    area.textContent = source.value;  // texte déjà saisi (réaffichage après erreur)
    var label = box.querySelector('label[for="' + source.id + '"]');
    if (label) label.removeAttribute("for");  // le libellé désigne désormais la zone éditable
    source.hidden = true;
    source.removeAttribute("required");
    area.hidden = false;
    toolbar.hidden = false;

    function sync() {
      hidden.value = area.querySelector("img") || area.textContent.trim() ? area.innerHTML : "";
      source.value = area.innerText;
    }
    function fail(message) {
      error.textContent = message;
      error.hidden = false;
      setTimeout(function () { error.hidden = true; }, 6000);
    }
    function insertNode(node) {
      var selection = window.getSelection();
      if (selection.rangeCount && area.contains(selection.getRangeAt(0).commonAncestorContainer)) {
        var range = selection.getRangeAt(0);
        range.deleteContents();
        range.insertNode(node);
        range.setStartAfter(node);
        range.collapse(true);
        selection.removeAllRanges();
        selection.addRange(range);
      } else {
        area.appendChild(node);
      }
      sync();
    }
    function insertImages(files) {
      Array.prototype.forEach.call(files, function (file) {
        if (RICH_TYPES.indexOf(file.type) === -1) { fail(file.name + " : seules les images PNG, JPEG, GIF et WebP sont acceptées."); return; }
        if (file.size > RICH_MAX_BYTES) { fail(file.name + " : image trop lourde (10 Mo maximum)."); return; }
        var reader = new FileReader();
        reader.onload = function () {
          var img = document.createElement("img");
          img.src = reader.result;
          img.alt = file.name || "Image collée";
          insertNode(img);
        };
        reader.readAsDataURL(file);
      });
    }

    area.addEventListener("input", sync);
    area.addEventListener("paste", function (event) {
      var data = event.clipboardData;
      if (!data) return;
      var images = Array.prototype.filter.call(data.files || [], function (f) { return f.type.indexOf("image/") === 0; });
      event.preventDefault();
      if (images.length) { insertImages(images); return; }
      // Texte collé sans mise en forme (évite le HTML parasite des traitements de texte).
      insertNode(document.createTextNode(data.getData("text/plain")));
    });
    area.addEventListener("dragover", function (event) { event.preventDefault(); });
    area.addEventListener("drop", function (event) {
      if (!event.dataTransfer || !event.dataTransfer.files.length) return;
      event.preventDefault();
      insertImages(event.dataTransfer.files);
    });
    box.querySelector("[data-rich-insert]").addEventListener("click", function () { picker.click(); });
    picker.addEventListener("change", function () { insertImages(picker.files); picker.value = ""; area.focus(); });
    var form = box.closest("form");
    if (form) form.addEventListener("submit", sync);
    sync();
  });
}
document.addEventListener("DOMContentLoaded", function () { richInit(document); });
document.addEventListener("htmx:load", function (event) { richInit(event.target); });

// Panneau dépliable (ex. formulaire de résolution de la fiche ticket).
document.addEventListener("click", function (event) {
  var toggle = event.target.closest("[data-toggle-panel]");
  if (!toggle) return;
  var panel = document.getElementById(toggle.getAttribute("data-toggle-panel"));
  if (!panel) return;
  panel.hidden = !panel.hidden;
  document.querySelectorAll('[aria-controls="' + panel.id + '"]').forEach(function (b) {
    b.setAttribute("aria-expanded", String(!panel.hidden));
  });
  if (!panel.hidden) {
    var first = panel.querySelector("textarea, input:not([type=hidden]), select");
    if (first) first.focus();
  }
});

// Zone de réponse : l'aide et le libellé du bouton suivent le choix réponse / note interne.
document.addEventListener("change", function (event) {
  var radio = event.target.closest("[data-composer] input[type=radio]");
  if (!radio) return;
  var form = radio.closest("[data-composer]");
  var choice = radio.parentElement.querySelector("[data-hint]");
  if (!choice) return;
  form.querySelector("[data-composer-hint]").textContent = choice.getAttribute("data-hint");
  form.querySelector("[data-composer-submit]").textContent = choice.getAttribute("data-submit");
});

// Création rapide (catégorie, outil) : Entrée dans le panneau crée l'élément au lieu
// d'envoyer le formulaire de qualification qui l'englobe.
document.addEventListener("keydown", function (event) {
  if (event.key !== "Enter") return;
  var panel = event.target.closest("[data-quick-add]");
  if (!panel || event.target.tagName === "TEXTAREA") return;
  event.preventDefault();
  panel.querySelector("[data-quick-submit]").click();
});
