document.addEventListener('DOMContentLoaded', function() {
  var copyBtns = document.querySelectorAll('.copy-btn');
  copyBtns.forEach(function(btn) {
    btn.addEventListener('click', function() {
      var target = btn.getAttribute('data-copy') || btn.getAttribute('data-copy-target');
      if (target) {
        var codeEl = document.getElementById(target);
        if (codeEl) {
          var text = codeEl.textContent || codeEl.innerText;
          navigator.clipboard.writeText(text).then(function() {
            btn.textContent = '복사됨!';
            setTimeout(function() { btn.textContent = '복사'; }, 2000);
          });
        } else {
          navigator.clipboard.writeText(target).then(function() {
            btn.textContent = '복사됨!';
            setTimeout(function() { btn.textContent = '복사'; }, 2000);
          });
        }
      }
    });
  });
});
