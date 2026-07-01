(function () {
  document.addEventListener('DOMContentLoaded', () => {
    const wrapper = document.getElementById('yeti-wrapper');
    const inputUser = document.getElementById('access-username');
    const inputPwd = document.getElementById('secret-word');
    const toggle = document.getElementById('gate-visibility');
    const yetiHead = document.getElementById('yeti-head');
    const yetiEyes = document.getElementById('yeti-eyes');
    const yetiMuzzle = document.getElementById('yeti-muzzle');

    function moveHead(ratio) {
      // ratio 0 to 1
      const maxOffset = 25;
      const offset = (ratio * 2 - 1) * maxOffset; // -25 to +25
      
      if (yetiHead) yetiHead.style.transform = `translateX(${offset * 0.8}px) translateY(8px)`;
      if (yetiEyes) yetiEyes.style.transform = `translateX(${offset * 1.2}px) translateY(4px)`;
      if (yetiMuzzle) yetiMuzzle.style.transform = `translateX(${offset * 1.5}px) translateY(6px)`;
    }

    function resetHead() {
      if (yetiHead) yetiHead.style.transform = `translate(0, 0)`;
      if (yetiEyes) yetiEyes.style.transform = `translate(0, 0)`;
      if (yetiMuzzle) yetiMuzzle.style.transform = `translate(0, 0)`;
    }

    if (inputUser) {
      inputUser.addEventListener('focus', () => {
        if (wrapper) wrapper.classList.remove('typing-password');
        const len = Math.min(inputUser.value.length, 30);
        moveHead(len / 30);
      });

      inputUser.addEventListener('input', () => {
        const len = Math.min(inputUser.value.length, 30);
        moveHead(len / 30);
      });

      inputUser.addEventListener('blur', () => {
        resetHead();
      });
    }

    if (inputPwd) {
      inputPwd.addEventListener('focus', () => {
        resetHead();
        if (inputPwd.type === 'text') {
          if (wrapper) wrapper.classList.remove('typing-password');
        } else {
          if (wrapper) wrapper.classList.add('typing-password');
        }
      });
      inputPwd.addEventListener('blur', () => {
        if (wrapper) wrapper.classList.remove('typing-password');
      });
    }

    if (toggle) {
      toggle.addEventListener('click', () => {
        if (!inputPwd) return;
        
        const isPassword = inputPwd.type === 'password';
        inputPwd.type = isPassword ? 'text' : 'password';
        toggle.setAttribute('aria-pressed', String(isPassword));
        
        if (document.activeElement === inputPwd) {
          if (isPassword) {
            // text visible, paws down
            if (wrapper) wrapper.classList.remove('typing-password');
          } else {
            // password hidden, paws up
            if (wrapper) wrapper.classList.add('typing-password');
          }
        }
        inputPwd.focus();
      });
    }
  });
})();
