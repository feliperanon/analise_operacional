(function () {
    "use strict";

    function initDecisionForm() {
        var form = document.getElementById("checklistDecisionForm");
        var comment = document.getElementById("decisionComment");
        var hint = document.getElementById("decisionHint");
        if (!form || !comment || !hint) return;

        var defaultHint = hint.getAttribute("data-default-hint") || hint.textContent || "";

        function setHint(text, tone) {
            hint.textContent = text || defaultHint;
            hint.classList.remove("is-warning", "is-danger");
            if (tone) {
                hint.classList.add(tone);
            }
        }

        Array.prototype.slice.call(form.querySelectorAll("[data-decision-action]")).forEach(function (button) {
            button.addEventListener("click", function (event) {
                var requireComment = button.getAttribute("data-require-comment") === "true";
                var requiredHint = button.getAttribute("data-required-hint") || "Adicione um comentario antes de continuar.";
                var confirmMessage = button.getAttribute("data-confirm-message");
                var submitHint = button.getAttribute("data-submit-hint") || defaultHint;

                comment.required = requireComment;

                if (requireComment && !comment.value.trim()) {
                    event.preventDefault();
                    setHint(requiredHint, "is-warning");
                    comment.focus();
                    return;
                }

                if (confirmMessage && !window.confirm(confirmMessage)) {
                    event.preventDefault();
                    setHint(defaultHint, "");
                    return;
                }

                setHint(submitHint, "");
            });
        });

        comment.addEventListener("input", function () {
            if (comment.value.trim()) {
                setHint(defaultHint, "");
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initDecisionForm);
    } else {
        initDecisionForm();
    }
})();
