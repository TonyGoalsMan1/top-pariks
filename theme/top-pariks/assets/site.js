const menuToggle = document.querySelector('.menu-toggle');
const navigation = document.getElementById('tp-navigation');

if (menuToggle && navigation) {
    const mobile = window.matchMedia('(max-width: 820px)');

    function setMenu(open) {
        navigation.hidden = mobile.matches && !open;
        menuToggle.setAttribute('aria-expanded', String(mobile.matches && open));
    }

    function syncMenu() {
        const focusWasInNav = navigation.contains(document.activeElement);
        const focusWasOnToggle = document.activeElement === menuToggle;
        menuToggle.hidden = !mobile.matches;
        setMenu(false);
        if (mobile.matches && focusWasInNav) {
            menuToggle.focus();
        }
        if (!mobile.matches && focusWasOnToggle) {
            navigation.querySelector('a')?.focus();
        }
    }

    menuToggle.addEventListener('click', () => {
        setMenu(navigation.hidden);
    });

    document.querySelector('.site-header').addEventListener('keydown', event => {
        if (event.key === 'Escape' && mobile.matches && !navigation.hidden) {
            event.preventDefault();
            setMenu(false);
            menuToggle.focus();
        }
    });

    mobile.addEventListener('change', syncMenu);
    syncMenu();
}

// Keep the full form usable before JavaScript loads or if it is disabled.
const filterToggle = document.querySelector('.atelier-filter-toggle');
const filters = document.getElementById('atelier-filter-form');
if (filterToggle && filters) {
    const compact = window.matchMedia('(max-width: 700px)');
    const setFilters = (open) => {
        filters.hidden = !open;
        filterToggle.setAttribute('aria-expanded', String(open));
    };
    const syncFilters = () => {
        filterToggle.hidden = !compact.matches;
        const focusInside = filters.contains(document.activeElement);
        setFilters(!compact.matches || focusInside);
    };
    filterToggle.addEventListener('click', () => setFilters(filters.hidden));
    filters.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !event.defaultPrevented && compact.matches && !filters.hidden) {
            event.preventDefault();
            setFilters(false);
            filterToggle.focus();
        }
    });
    compact.addEventListener('change', syncFilters);
    syncFilters();
}
