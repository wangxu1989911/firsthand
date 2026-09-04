(function () {
  "use strict";

  var form = document.getElementById("chat-form");
  var input = document.getElementById("message");
  var transcript = document.getElementById("transcript");
  var status = document.getElementById("status");

  function addTurn(role, text) {
    var li = document.createElement("li");
    li.className = "turn turn--" + role;
    var roleEl = document.createElement("span");
    roleEl.className = "turn__role";
    roleEl.textContent = role;
    var textEl = document.createElement("span");
    textEl.className = "turn__text";
    textEl.textContent = text;
    li.appendChild(roleEl);
    li.appendChild(textEl);
    transcript.appendChild(li);
    li.scrollIntoView({ block: "nearest" });
  }

  function lock(message) {
    input.disabled = true;
    form.querySelector("button").disabled = true;
    status.textContent = message || "This conversation is complete.";
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var text = input.value.trim();
    if (!text) {
      return;
    }
    addTurn("user", text);
    input.value = "";
    input.disabled = true;
    status.textContent = "…";

    fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("request failed");
        }
        return response.json();
      })
      .then(function (data) {
        addTurn("assistant", data.reply);
        if (data.done) {
          lock();
        } else {
          input.disabled = false;
          status.textContent = "";
          input.focus();
        }
      })
      .catch(function () {
        status.textContent = "Something went wrong. Please try again.";
        input.disabled = false;
      });
  });
})();
