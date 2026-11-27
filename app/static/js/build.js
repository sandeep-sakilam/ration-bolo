// Footer build identity: the commit this app was built from (F25).
(() => {
  "use strict";
  const foot = document.querySelector("footer.foot");
  if (!foot) return;
  fetch("/health").then((r) => r.json()).then((h) => {
    const b = h.build || {};
    const span = document.createElement("span");
    span.id = "build";
    span.append(" · build ");
    if (b.url) {
      const a = document.createElement("a");
      a.href = b.url; a.textContent = b.short; a.rel = "noopener";
      span.appendChild(a);
    } else {
      span.append(b.short || "unknown");
    }
    foot.appendChild(span);
  }).catch(() => {});
})();
