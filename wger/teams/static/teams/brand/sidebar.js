/* Sidebar of Athlete Lab Pro: remembers whether it is folded or hidden and marks the current page. */
(function () {
    var STORAGE_KEY = 'alp-sidebar-collapsed';
    var HIDDEN_KEY = 'alp-sidebar-hidden';
    var root = document.documentElement;

    function read(key) {
        try {
            return window.localStorage.getItem(key) === '1';
        } catch (error) {
            return false;
        }
    }

    function store(key, value) {
        try {
            window.localStorage.setItem(key, value ? '1' : '0');
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

    function applyHidden(hidden) {
        root.classList.toggle('alp-sidebar-hidden', hidden);
    }

    // Before the page is drawn, so a folded or hidden sidebar does not flash open
    applyCollapsed(read(STORAGE_KEY), null);
    applyHidden(read(HIDDEN_KEY));

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
        var hide = document.querySelector('.alp-sidebar-hide');
        var show = document.querySelector('.alp-sidebar-show');
        applyCollapsed(read(STORAGE_KEY), button);
        if (button) {
            button.addEventListener('click', function () {
                var collapsed = !root.classList.contains('alp-sidebar-collapsed');
                applyCollapsed(collapsed, button);
                store(STORAGE_KEY, collapsed);
            });
        }
        if (hide && show) {
            // Outside of the sidebar, so it stays on screen while the sidebar is away
            document.body.appendChild(show);
            hide.addEventListener('click', function () {
                applyHidden(true);
                store(HIDDEN_KEY, true);
                show.focus();
            });
            show.addEventListener('click', function () {
                applyHidden(false);
                store(HIDDEN_KEY, false);
                hide.focus();
            });
        }
        markCurrentPage();
        nameTopLevelEntries();
    });
})();
