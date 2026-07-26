(() => {
  const app = window.WorldFeed = window.WorldFeed || {};
  let dialogTrigger = null;

  function bindStoryControls() {
    document.querySelectorAll("[data-open-story]").forEach((control) => {
      control.addEventListener("click", () => {
        app.navigation.navigate("story", { captureOrigin: true, originControl: control });
      });
    });
  }

  function bindSourceDialog() {
    const dialog = document.getElementById("source-dialog");
    if (!dialog) return;
    document.querySelectorAll("[data-source-action]").forEach((control) => {
      control.addEventListener("click", () => {
        dialogTrigger = control;
        dialog.showModal();
      });
    });
    dialog.addEventListener("close", () => dialogTrigger?.focus({ preventScroll: true }));
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  }

  function initialize() {
    bindStoryControls();
    bindSourceDialog();
  }

  app.story = { initialize };
})();
