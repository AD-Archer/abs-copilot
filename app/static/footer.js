(function () {
  const footer = document.querySelector("[data-site-footer]");
  if (!footer) return;

  footer.className = "site-footer";
  footer.innerHTML = `
    <span>ABS Insight Copilot</span>
    <span>
      <a href="https://github.com/ad-archer/abs_copliot" target="_blank" rel="noopener noreferrer">GitHub: ad-archer/abs_copliot</a>
      ·
      <a href="https://antonioarcher.com" target="_blank" rel="noopener noreferrer">antonioarcher.com</a>
    </span>
  `;
})();

