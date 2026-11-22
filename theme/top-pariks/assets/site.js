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
