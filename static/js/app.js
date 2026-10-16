(() => {
    // Sidebar toggle logic
    const toggle = document.getElementById("sidebar-toggle");
    const sidebar = document.getElementById("sidebar");
    const backdrop = document.getElementById("sidebar-backdrop");
    if (toggle && sidebar && backdrop) {
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
    }

    // Disable action buttons on submit to avoid duplicate clicks
    document.querySelectorAll("form.single-submit-form").forEach((form) => {
        form.addEventListener("submit", function () {
            const btn = this.querySelector("button[type='submit']");
            if (btn) {
                btn.disabled = true;
                btn.classList.add("opacity-60", "cursor-not-allowed");
            }
        });
    });
})();