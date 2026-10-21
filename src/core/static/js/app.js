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
