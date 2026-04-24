(function () {
    "use strict";

    var DEBOUNCE_MS = 420;

    function $(id) {
        return document.getElementById(id);
    }

    function scheduleFilterSubmit(filtersForm, debounceRef) {
        if (!filtersForm) return;
        if (debounceRef.t) clearTimeout(debounceRef.t);
        debounceRef.t = setTimeout(function () {
            filtersForm.submit();
        }, DEBOUNCE_MS);
    }

    function bindModalBackdrop(shell, closeFn) {
        if (!shell || typeof closeFn !== "function") return;
        shell.addEventListener(
            "click",
            function (e) {
                if (e.target === shell) closeFn();
            },
            { passive: true }
        );
    }

    function refreshSelectionState(selectAll, rowCheckboxes, selectedCount, selectedState, defaultLabel) {
        var count = rowCheckboxes.filter(function (cb) {
            return cb.checked;
        }).length;
        if (selectedCount) selectedCount.textContent = String(count);
        if (selectedState) selectedState.classList.toggle("hidden", count === 0);
        if (defaultLabel) defaultLabel.classList.toggle("hidden", count > 0);
        if (selectAll) {
            selectAll.indeterminate = count > 0 && count < rowCheckboxes.length;
            selectAll.checked = rowCheckboxes.length > 0 && count === rowCheckboxes.length;
        }
    }

    function init() {
        var filtersForm = $("filtersForm");
        var debounceRef = { t: null };
        var searchInput = $("searchInput");
        var equipmentInput = $("equipmentInput");
        if (searchInput) {
            searchInput.addEventListener(
                "input",
                function () {
                    scheduleFilterSubmit(filtersForm, debounceRef);
                },
                { passive: true }
            );
        }
        if (equipmentInput) {
            equipmentInput.addEventListener(
                "input",
                function () {
                    scheduleFilterSubmit(filtersForm, debounceRef);
                },
                { passive: true }
            );
        }

        var selectAll = $("selectAll");
        var rowCheckboxes = Array.prototype.slice.call(document.querySelectorAll(".row-checkbox"));
        var selectedCount = $("selectedCount");
        var selectedState = $("selectedState");
        var defaultLabel = $("defaultLabel");

        function onSelectionChange() {
            refreshSelectionState(selectAll, rowCheckboxes, selectedCount, selectedState, defaultLabel);
        }

        if (selectAll) {
            selectAll.addEventListener(
                "change",
                function () {
                    rowCheckboxes.forEach(function (cb) {
                        cb.checked = selectAll.checked;
                    });
                    onSelectionChange();
                },
                { passive: true }
            );
        }
        rowCheckboxes.forEach(function (cb) {
            cb.addEventListener("change", onSelectionChange, { passive: true });
        });
        onSelectionChange();

        var bulkDeleteBtn = $("openBulkDeleteBtn");
        if (bulkDeleteBtn) {
            bulkDeleteBtn.addEventListener("click", function () {
                window.openBulkModal();
            });
        }

        document.querySelectorAll(".js-checklist-edit").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var id = parseInt(btn.getAttribute("data-id") || "0", 10);
                var equipment = btn.getAttribute("data-equipment") || "";
                var observations = btn.getAttribute("data-observations") || "";
                window.openEditModal(id, equipment, observations);
            });
        });

        bindModalBackdrop($("createModal"), window.closeCreateModal);
        bindModalBackdrop($("importModal"), window.closeImportModal);
        bindModalBackdrop($("editModal"), window.closeEditModal);
        bindModalBackdrop($("bulkModal"), window.closeBulkModal);
        bindModalBackdrop($("bulkDeleteConfirmModal"), window.closeBulkDeleteConfirmModal);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    window.openCreateModal = function () {
        var m = $("createModal");
        if (m) m.classList.remove("hidden");
    };
    window.closeCreateModal = function () {
        var m = $("createModal");
        if (m) m.classList.add("hidden");
    };
    window.openImportModal = function () {
        var m = $("importModal");
        if (m) m.classList.remove("hidden");
    };
    window.closeImportModal = function () {
        var m = $("importModal");
        if (m) m.classList.add("hidden");
    };
    window.openBulkModal = function () {
        var m = $("bulkModal");
        if (m) m.classList.remove("hidden");
    };
    window.closeBulkModal = function () {
        var m = $("bulkModal");
        if (m) m.classList.add("hidden");
    };
    window.openEditModal = function (id, equipment, observations) {
        var form = $("editForm");
        if (form) form.action = "/admin/routine/checklists/" + id + "/edit";
        var eq = $("editEquipmentCode");
        if (eq) eq.value = equipment || "";
        var obs = $("editObservations");
        if (obs) obs.value = observations || "";
        var m = $("editModal");
        if (m) m.classList.remove("hidden");
    };
    window.closeEditModal = function () {
        var m = $("editModal");
        if (m) m.classList.add("hidden");
    };
    window.closeBulkDeleteConfirmModal = function () {
        var m = $("bulkDeleteConfirmModal");
        if (m) m.classList.add("hidden");
    };
    window.confirmBulkDelete = function () {
        var rowCheckboxes = Array.prototype.slice.call(document.querySelectorAll(".row-checkbox"));
        var checked = rowCheckboxes.filter(function (cb) {
            return cb.checked;
        });
        if (!checked.length) {
            window.closeBulkModal();
            return;
        }
        var n = $("bulkDeleteCount");
        if (n) n.textContent = String(checked.length);
        window.closeBulkModal();
        var c = $("bulkDeleteConfirmModal");
        if (c) c.classList.remove("hidden");
    };
    window.submitBulkDelete = function () {
        var f = $("bulkDeleteForm");
        if (f) f.submit();
    };
})();
