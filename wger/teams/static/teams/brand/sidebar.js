/* Sidebar of Athlete Lab Pro: remembers whether it is collapsed and marks the current page. */
(function () {
    var STORAGE_KEY = 'alp-sidebar-collapsed';
    var root = document.documentElement;

    function readCollapsed() {
        try {
            return window.localStorage.getItem(STORAGE_KEY) === '1';
        } catch (error) {
            return false;
        }
    }

    function storeCollapsed(collapsed) {
        try {
            window.localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0');
        } catch (error) {
            // Private windows may refuse storage, the sidebar then just starts open
        }
    }

    function applyCollapsed(collapsed, button) {
        root.classList.toggle('alp-sidebar-collapsed', collapsed);
        if (button) {
            var label = collapsed ? button.dataset.labelExpand : button.dataset.labelCollapse;
            button.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
            button.setAttribute('aria-label', label);
            button.setAttribute('title', label);
        }
    }

    // Before the page is drawn, so a collapsed sidebar does not flash open
    applyCollapsed(readCollapsed(), null);

    function markCurrentPage() {
        var path = window.location.pathname;
        var current = null;
        var links = document.querySelectorAll('.alp-navbar .navbar-nav.me-auto a.dropdown-item[href]');

        links.forEach(function (link) {
            var url = new URL(link.href, window.location.href);
            if (url.origin !== window.location.origin || url.pathname === '/') {
                return;
            }

            var target = url.pathname;
            var matches = path === target || (target.endsWith('/') && path.indexOf(target) === 0);

            // The most specific entry wins
            if (matches && (current === null || target.length > current.target.length)) {
                current = { link: link, target: target };
            }
        });

        if (current !== null) {
            current.link.classList.add('alp-current');
            current.link.setAttribute('aria-current', 'page');
        }
    }

    // The folded sidebar shows icons only, the name of each entry is then its tooltip
    function nameTopLevelEntries() {
        document.querySelectorAll('.alp-navbar .navbar-nav > .nav-item > .nav-link').forEach(function (link) {
            var name = link.textContent.replace(/\s+/g, ' ').trim();
            if (name && !link.getAttribute('title')) {
                link.setAttribute('title', name);
            }
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        var button = document.querySelector('.alp-sidebar-toggle');
        applyCollapsed(readCollapsed(), button);
        if (button) {
            button.addEventListener('click', function () {
                var collapsed = !root.classList.contains('alp-sidebar-collapsed');
                applyCollapsed(collapsed, button);
                storeCollapsed(collapsed);
            });
        }
        markCurrentPage();
        nameTopLevelEntries();
    });
})();
