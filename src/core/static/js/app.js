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

// Choix d'une personne dans les résultats de recherche de l'annuaire.
document.addEventListener("click", function (event) {
  var button = event.target.closest("[data-pick-person]");
  if (!button) return;
  var target = button.getAttribute("data-target") || "requester";
  var input = document.getElementById("id_" + target);
  var label = document.getElementById(target + "-selected");
  var results = document.getElementById(target + "-results");
  if (input) input.value = button.getAttribute("data-pick-person");
  if (label) label.textContent = button.getAttribute("data-label");
  if (results) results.innerHTML = "";
});
