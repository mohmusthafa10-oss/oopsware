(() => {
    const toggle = document.getElementById("sidebar-toggle");
    const sidebar = document.getElementById("sidebar");
    const backdrop = document.getElementById("sidebar-backdrop");
    if (!toggle || !sidebar || !backdrop) return;

    function setOpen(open) {
        sidebar.classList.toggle("-translate-x-full", !open);
        backdrop.classList.toggle("hidden", !open);
        toggle.setAttribute("aria-expanded", String(open));
    }

    toggle.addEventListener("click", () =>
        setOpen(toggle.getAttribute("aria-expanded") !== "true")
    );
    backdrop.addEventListener("click", () => setOpen(false));
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") setOpen(false);
    });
})();