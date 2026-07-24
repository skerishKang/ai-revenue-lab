document.addEventListener('DOMContentLoaded', function() {
  var copyBtns = document.querySelectorAll('.copy-btn');
  copyBtns.forEach(function(btn) {
    btn.addEventListener('click', function() {
      var text = null;
      var targetId = btn.getAttribute('data-copy-target');
      if (targetId) {
        var codeEl = document.getElementById(targetId);
        if (codeEl) {
          text = codeEl.textContent || codeEl.innerText;
        }
      } else {
        text = btn.getAttribute('data-copy');
      }
      if (text) {
        navigator.clipboard.writeText(text).then(function() {
          btn.textContent = '복사됨!';
          setTimeout(function() { btn.textContent = '복사'; }, 2000);
        });
      }
    });
  });
});
