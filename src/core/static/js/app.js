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

// Mentions « @technicien » dans une note interne (FR-014d) : suggestions au fil de la frappe.
// Le choix insère « @Prénom Nom » en texte ; le serveur reconnaît la mention à l'enregistrement.
var mention = { menu: null, area: null, items: [], index: 0, ctx: null };

function mentionFold(text) {
  return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}
function mentionPeople(area) {
  var form = area.closest("[data-composer]");
  var data = form && form.querySelector("#mentionable");
  try { return data ? JSON.parse(data.textContent) : []; } catch (e) { return []; }
}
function mentionAllowed(area) {
  var checked = area.closest("[data-composer]").querySelector('input[name="visibility"]:checked');
  return !checked || checked.value === "interne";
}
function mentionContext(area) {
  var selection = window.getSelection();
  if (!selection.rangeCount || !selection.isCollapsed) return null;
  var node = selection.anchorNode;
  if (!node || node.nodeType !== 3 || !area.contains(node)) return null;
  var before = node.textContent.slice(0, selection.anchorOffset);
  var match = before.match(/(?:^|[\s (])@([^\s @]{0,40})$/);
  if (!match) return null;
  return { node: node, start: selection.anchorOffset - match[1].length - 1, end: selection.anchorOffset, query: match[1] };
}
function mentionClose() {
  if (mention.menu) mention.menu.remove();
  if (mention.area) {
    mention.area.removeAttribute("aria-activedescendant");
    mention.area.setAttribute("aria-expanded", "false");
  }
  mention.menu = null; mention.items = []; mention.ctx = null;
}
function mentionRender() {
  mention.menu.querySelectorAll("[role=option]").forEach(function (li, i) {
    li.setAttribute("aria-selected", String(i === mention.index));
    if (i === mention.index) {
      mention.area.setAttribute("aria-activedescendant", li.id);
      li.scrollIntoView({ block: "nearest" });
    }
  });
}
function mentionOpen(area, ctx) {
  var query = mentionFold(ctx.query);
  var items = mentionPeople(area).filter(function (p) {
    var haystack = [p.name].concat(p.name.split(/[\s-]+/), [p.email.split("@")[0]]);
    return haystack.some(function (h) { return mentionFold(h).indexOf(query) === 0; });
  }).slice(0, 8);
  if (!items.length) { mentionClose(); return; }
  if (!mention.menu) {
    mention.menu = document.createElement("ul");
    mention.menu.className = "mention-menu";
    mention.menu.id = "mention-menu";
    mention.menu.setAttribute("role", "listbox");
    mention.menu.setAttribute("aria-label", "Techniciens à mentionner");
    area.parentElement.appendChild(mention.menu);
    area.setAttribute("aria-controls", "mention-menu");
    area.setAttribute("aria-expanded", "true");
  }
  mention.area = area; mention.items = items; mention.ctx = ctx; mention.index = 0;
  mention.menu.innerHTML = "";
  items.forEach(function (p, i) {
    var li = document.createElement("li");
    li.id = "mention-option-" + i;
    li.setAttribute("role", "option");
    li.textContent = p.name;
    if (p.email) {
      var email = document.createElement("span");
      email.className = "muted";
      email.textContent = p.email;
      li.appendChild(email);
    }
    li.addEventListener("mousedown", function (event) { event.preventDefault(); mentionChoose(i); });
    mention.menu.appendChild(li);
  });
  var caret = window.getSelection().getRangeAt(0).getBoundingClientRect();
  var box = area.parentElement.getBoundingClientRect();
  mention.menu.style.top = (caret.bottom ? caret.bottom - box.top + 4 : area.offsetTop + area.offsetHeight) + "px";
  mention.menu.style.left = Math.max(0, Math.min((caret.left || box.left) - box.left, box.width - 280)) + "px";
  mentionRender();
}
function mentionChoose(i) {
  var person = mention.items[i], ctx = mention.ctx, area = mention.area;
  if (!person || !ctx) return;
  var text = ctx.node.textContent;
  ctx.node.textContent = text.slice(0, ctx.start) + "@" + person.name + " " + text.slice(ctx.end);
  var range = document.createRange();
  range.setStart(ctx.node, ctx.start + person.name.length + 2);
  range.collapse(true);
  var selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  mentionClose();
  area.dispatchEvent(new Event("input", { bubbles: true }));  // synchronise l'éditeur
}
document.addEventListener("input", function (event) {
  var area = event.target.closest && event.target.closest("[data-composer] .rich-area");
  if (!area) return;
  var ctx = mentionAllowed(area) && mentionContext(area);
  if (ctx) mentionOpen(area, ctx); else mentionClose();
});
document.addEventListener("keydown", function (event) {
  if (!mention.menu || event.target !== mention.area) return;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    var n = mention.items.length;
    mention.index = (mention.index + (event.key === "ArrowDown" ? 1 : n - 1)) % n;
    mentionRender();
  } else if (event.key === "Enter" || event.key === "Tab") {
    event.preventDefault();
    mentionChoose(mention.index);
  } else if (event.key === "Escape") {
    event.preventDefault();
    mentionClose();
  }
});
document.addEventListener("focusout", function (event) {
  if (mention.menu && event.target === mention.area) mentionClose();
});
document.addEventListener("htmx:beforeSwap", mentionClose);
