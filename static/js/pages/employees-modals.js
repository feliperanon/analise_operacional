/**
 * Gerenciamento de modais da página /employees (foco, aria-hidden, inert, ESC, backdrop único).
 */
(function () {
    'use strict';

    var SELECTOR_SHELL = '.emp-modal-shell, .emp-modal-layer';
    var portal = null;
    var sharedBackdrop = null;
    var lastTrigger = null;
    var openStack = [];

    function getPortal() {
        if (!portal) {
            portal = document.querySelector('[data-employees-modals-portal]');
        }
        return portal;
    }

    function getSharedBackdrop() {
        if (!sharedBackdrop) {
            sharedBackdrop = document.getElementById('employees-shared-backdrop');
        }
        return sharedBackdrop;
    }

    function isOpen(el) {
        return el && !el.hasAttribute('hidden');
    }

    function hideModalEl(el) {
        if (!el) return;
        el.setAttribute('hidden', '');
        el.classList.add('hidden');
        el.setAttribute('aria-hidden', 'true');
    }

    function showModalEl(el) {
        if (!el) return;
        el.removeAttribute('hidden');
        el.classList.remove('hidden');
        el.removeAttribute('aria-hidden');
    }

    function getOpenModals() {
        var root = getPortal();
        if (!root) return [];
        return Array.prototype.filter.call(root.querySelectorAll(SELECTOR_SHELL), isOpen);
    }

    function blurIfInside(node) {
        var active = document.activeElement;
        if (active && node && node.contains(active)) {
            active.blur();
        }
    }

    function setPortalOpenState() {
        var root = getPortal();
        if (!root) return;
        var anyOpen = getOpenModals().length > 0;
        var backdrop = getSharedBackdrop();

        if (anyOpen) {
            root.setAttribute('data-modal-open', 'true');
            root.removeAttribute('aria-hidden');
            if ('inert' in root) root.inert = false;
            if (backdrop) {
                backdrop.removeAttribute('hidden');
                backdrop.classList.remove('hidden');
            }
            document.documentElement.classList.add('employees-modal-open');
            document.body.classList.add('employees-modal-open');
        } else {
            blurIfInside(root);
            if (backdrop) {
                backdrop.setAttribute('hidden', '');
                backdrop.classList.add('hidden');
            }
            var applyClosed = function () {
                if (getOpenModals().length > 0) return;
                root.removeAttribute('data-modal-open');
                if ('inert' in root) root.inert = true;
                root.setAttribute('aria-hidden', 'true');
                document.documentElement.classList.remove('employees-modal-open');
                document.body.classList.remove('employees-modal-open');
            };
            if (typeof requestAnimationFrame === 'function') {
                requestAnimationFrame(applyClosed);
            } else {
                applyClosed();
            }
        }
    }

    function focusableIn(modal) {
        if (!modal) return [];
        var sel = [
            'a[href]',
            'button:not([disabled])',
            'input:not([disabled]):not([type="hidden"])',
            'select:not([disabled])',
            'textarea:not([disabled])',
            '[tabindex]:not([tabindex="-1"])',
        ].join(',');
        return Array.prototype.filter.call(modal.querySelectorAll(sel), function (el) {
            return el.offsetParent !== null || el.getClientRects().length > 0;
        });
    }

    function focusFirstField(modal) {
        var preferred = modal.querySelector(
            '[data-emp-modal-initial-focus], .emp-modal-body input:not([type="hidden"]), .emp-modal-body select, .emp-modal-body textarea'
        );
        var list = focusableIn(modal);
        var target = preferred && list.indexOf(preferred) >= 0 ? preferred : list[0];
        if (!target) {
            target = modal.querySelector('.emp-modal-close, [data-emp-modal-close]');
        }
        if (target && typeof target.focus === 'function') {
            try {
                target.focus({ preventScroll: true });
            } catch (e) {
                target.focus();
            }
        }
    }

    function restoreTrigger() {
        if (lastTrigger && typeof lastTrigger.focus === 'function') {
            try {
                lastTrigger.focus({ preventScroll: true });
            } catch (e) {
                lastTrigger.focus();
            }
        }
        lastTrigger = null;
    }

    function openEmployeeModal(id, trigger) {
        var modal = document.getElementById(id);
        if (!modal) return;

        if (trigger && trigger.focus) {
            lastTrigger = trigger;
        } else if (document.activeElement && document.activeElement !== document.body) {
            lastTrigger = document.activeElement;
        }

        closeAlpineImportDropdown();

        getOpenModals().forEach(function (other) {
            if (other.id !== id) {
                blurIfInside(other);
                hideModalEl(other);
            }
        });
        openStack = openStack.filter(function (mid) {
            return mid === id;
        });

        showModalEl(modal);
        modal.setAttribute('aria-modal', 'true');
        if (!modal.getAttribute('role')) modal.setAttribute('role', 'dialog');

        var title = modal.querySelector('[id$="-title"], .emp-modal-header .sys-section-heading, .emp-modal-header h3');
        if (title && title.id) {
            modal.setAttribute('aria-labelledby', title.id);
        }

        var body = modal.querySelector('.emp-modal-body');
        if (body) body.scrollTop = 0;

        openStack.push(id);

        setPortalOpenState();
        requestAnimationFrame(function () {
            focusFirstField(modal);
        });
    }

    function closeEmployeeModal(id, evt) {
        if (evt) evt.preventDefault();
        var modal = document.getElementById(id);
        if (!modal || !isOpen(modal)) return;

        blurIfInside(modal);
        hideModalEl(modal);

        openStack = openStack.filter(function (mid) {
            return mid !== id;
        });

        var stillOpen = getOpenModals();
        if (stillOpen.length === 0) {
            restoreTrigger();
        }
        setPortalOpenState();
    }

    function closeAllEmployeeModals() {
        getOpenModals().forEach(function (modal) {
            blurIfInside(modal);
            hideModalEl(modal);
        });
        openStack = [];
        restoreTrigger();
        setPortalOpenState();
    }

    function closeTopEmployeeModal() {
        if (openStack.length) {
            closeEmployeeModal(openStack[openStack.length - 1]);
            return;
        }
        var open = getOpenModals();
        if (open.length) {
            closeEmployeeModal(open[open.length - 1].id);
        }
    }

    function closeAlpineImportDropdown() {
        document.querySelectorAll('.employees-hero__import-wrap [x-data]').forEach(function (el) {
            if (el.__x && el.__x.$data && 'open' in el.__x.$data) {
                el.__x.$data.open = false;
            }
        });
    }

    function onBackdropClick(evt) {
        var backdrop = evt.target.closest('#employees-shared-backdrop, [data-emp-modal-dismiss]');
        if (!backdrop) return;
        var open = getOpenModals();
        if (!open.length) return;
        closeEmployeeModal(open[open.length - 1].id, evt);
    }

    function onKeydown(evt) {
        if (evt.key !== 'Escape') return;
        var open = getOpenModals();
        if (!open.length) return;
        evt.preventDefault();
        closeTopEmployeeModal();
    }

    function sealAllModalsClosed() {
        var root = getPortal();
        if (!root) return;
        root.querySelectorAll(SELECTOR_SHELL).forEach(hideModalEl);
        var backdrop = getSharedBackdrop();
        if (backdrop) {
            backdrop.setAttribute('hidden', '');
            backdrop.classList.add('hidden');
        }
        openStack = [];
        lastTrigger = null;
        document.documentElement.classList.remove('employees-modal-open');
        document.body.classList.remove('employees-modal-open');
        root.removeAttribute('data-modal-open');
        if ('inert' in root) root.inert = true;
        root.setAttribute('aria-hidden', 'true');
    }

    function init() {
        var root = getPortal();
        if (!root) return;

        sealAllModalsClosed();

        root.addEventListener('click', onBackdropClick);

        document.addEventListener('click', function (evt) {
            var closeBtn = evt.target.closest('[data-emp-modal-close]');
            if (!closeBtn) return;
            var modal = closeBtn.closest(SELECTOR_SHELL);
            if (modal) closeEmployeeModal(modal.id, evt);
        });

        document.addEventListener('keydown', onKeydown);
    }

    window.openEmployeeModal = openEmployeeModal;
    window.closeEmployeeModal = closeEmployeeModal;
    window.closeAllEmployeeModals = closeAllEmployeeModals;
    window.closeEmpModal = closeEmployeeModal;

    window.openAddEmployeeModal = function () {
        var body = document.getElementById('addModalScroll');
        if (body) body.scrollTop = 0;
        openEmployeeModal('addModal', document.activeElement);
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
