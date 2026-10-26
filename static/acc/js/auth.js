/**
 * Avingine - Real-Time Client-Side Auth Form Validation
 * Provides inline feedback for email formatting, password length, confirmation matching, etc.
 */

document.addEventListener('DOMContentLoaded', () => {
    // Utility functions for inline validation feedback
    function showFieldError(input, message) {
        if (!input) return;

        // Visual state on input
        input.classList.remove('border-slate-300', 'focus:border-[#101820]', 'focus:ring-[#101820]');
        input.classList.add('border-red-400', 'focus:border-red-500', 'focus:ring-red-500');

        // Visual state on floating label
        const wrapper = input.closest('.relative') || input.parentElement;
        const label = wrapper ? wrapper.querySelector('label') : null;
        if (label) {
            label.classList.add('!text-red-500');
        }

        // Inline error paragraph
        let errorEl = findErrorElement(input, wrapper);
        if (errorEl) {
            errorEl.textContent = message;
            errorEl.classList.remove('hidden');
        }
    }

    function clearFieldError(input) {
        if (!input) return;

        // Visual state on input
        input.classList.remove('border-red-400', 'focus:border-red-500', 'focus:ring-red-500');
        input.classList.add('border-slate-300', 'focus:border-[#101820]', 'focus:ring-[#101820]');

        // Visual state on floating label
        const wrapper = input.closest('.relative') || input.parentElement;
        const label = wrapper ? wrapper.querySelector('label') : null;
        if (label) {
            label.classList.remove('!text-red-500');
        }

        // Inline error paragraph
        let errorEl = findErrorElement(input, wrapper);
        if (errorEl) {
            errorEl.textContent = '';
            errorEl.classList.add('hidden');
        }
    }

    function findErrorElement(input, wrapper) {
        if (!input) return null;
        const fieldName = input.name || input.id;
        
        // 1. Check data-for attribute
        let el = document.querySelector(`.inline-error[data-for="${fieldName}"]`);
        if (el) return el;

        // 2. Check next sibling of wrapper
        if (wrapper && wrapper.nextElementSibling && wrapper.nextElementSibling.classList.contains('inline-error')) {
            return wrapper.nextElementSibling;
        }

        // 3. Fallback: dynamically create underneath wrapper
        if (wrapper && wrapper.parentNode) {
            el = document.createElement('p');
            el.className = 'inline-error text-xs text-red-500 mt-1 pl-1';
            el.setAttribute('data-for', fieldName);
            wrapper.parentNode.insertBefore(el, wrapper.nextSibling);
            return el;
        }
        return null;
    }

    // Validation Rules
    function isValidEmail(email) {
        return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
    }

    // -------------------------------------------------------------
    // SIGNUP FORM VALIDATION
    // -------------------------------------------------------------
    const signupForm = document.querySelector('form[action*="signup"]');
    if (signupForm) {
        const emailInput = document.getElementById('signup-email') || signupForm.querySelector('input[name="email"]');
        const passInput = document.getElementById('signup-password') || signupForm.querySelector('input[name="password"]');
        const confirmInput = document.getElementById('signup-confirm-password') || signupForm.querySelector('input[name="confirm_password"]');
        const termsInput = document.getElementById('signup-terms') || signupForm.querySelector('input[name="terms"]');

        function validateSignupEmail() {
            if (!emailInput) return true;
            const val = emailInput.value.trim();
            if (!val) {
                showFieldError(emailInput, 'Email address is required.');
                return false;
            }
            if (!isValidEmail(val)) {
                showFieldError(emailInput, 'Please enter a valid email address.');
                return false;
            }
            clearFieldError(emailInput);
            return true;
        }

        function validateSignupPassword() {
            if (!passInput) return true;
            const val = passInput.value;
            if (!val) {
                showFieldError(passInput, 'Password is required.');
                return false;
            }
            if (val.length < 8) {
                showFieldError(passInput, 'Password must be at least 8 characters long.');
                return false;
            }
            clearFieldError(passInput);
            // Re-validate confirmation if it already has input
            if (confirmInput && confirmInput.value) {
                validateSignupConfirm();
            }
            return true;
        }

        function validateSignupConfirm() {
            if (!confirmInput || !passInput) return true;
            const passVal = passInput.value;
            const confirmVal = confirmInput.value;
            if (!confirmVal) {
                showFieldError(confirmInput, 'Please confirm your password.');
                return false;
            }
            if (passVal !== confirmVal) {
                showFieldError(confirmInput, 'Passwords do not match.');
                return false;
            }
            clearFieldError(confirmInput);
            return true;
        }

        function validateSignupTerms() {
            if (!termsInput) return true;
            if (!termsInput.checked) {
                showFieldError(termsInput, 'You must agree to the Terms of Service to continue.');
                return false;
            }
            clearFieldError(termsInput);
            return true;
        }

        // Real-time input listeners
        if (emailInput) {
            emailInput.addEventListener('blur', validateSignupEmail);
            emailInput.addEventListener('input', () => {
                if (emailInput.value.trim() && isValidEmail(emailInput.value)) {
                    clearFieldError(emailInput);
                }
            });
        }

        if (passInput) {
            passInput.addEventListener('input', () => {
                if (passInput.value.length >= 8) {
                    clearFieldError(passInput);
                }
                if (confirmInput && confirmInput.value) {
                    validateSignupConfirm();
                }
            });
            passInput.addEventListener('blur', validateSignupPassword);
        }

        if (confirmInput) {
            confirmInput.addEventListener('input', () => {
                if (passInput && confirmInput.value === passInput.value) {
                    clearFieldError(confirmInput);
                } else if (confirmInput.value.length >= (passInput ? passInput.value.length : 1)) {
                    validateSignupConfirm();
                }
            });
            confirmInput.addEventListener('blur', validateSignupConfirm);
        }

        if (termsInput) {
            termsInput.addEventListener('change', validateSignupTerms);
        }

        signupForm.addEventListener('submit', (e) => {
            const vEmail = validateSignupEmail();
            const vPass = validateSignupPassword();
            const vConfirm = validateSignupConfirm();
            const vTerms = validateSignupTerms();

            if (!vEmail || !vPass || !vConfirm || !vTerms) {
                e.preventDefault();
                // Focus first failing field
                if (!vEmail) emailInput?.focus();
                else if (!vPass) passInput?.focus();
                else if (!vConfirm) confirmInput?.focus();
                else if (!vTerms) termsInput?.focus();
            }
        });
    }

    // -------------------------------------------------------------
    // LOGIN FORM VALIDATION
    // -------------------------------------------------------------
    const loginForm = document.querySelector('form[action*="login"]');
    if (loginForm) {
        const emailInput = document.getElementById('login-email') || loginForm.querySelector('input[name="email"]');
        const passInput = document.getElementById('login-password') || loginForm.querySelector('input[name="password"]');

        function validateLoginEmail() {
            if (!emailInput) return true;
            const val = emailInput.value.trim();
            if (!val) {
                showFieldError(emailInput, 'Email address is required.');
                return false;
            }
            if (!isValidEmail(val)) {
                showFieldError(emailInput, 'Please enter a valid email address.');
                return false;
            }
            clearFieldError(emailInput);
            return true;
        }

        function validateLoginPassword() {
            if (!passInput) return true;
            if (!passInput.value) {
                showFieldError(passInput, 'Password is required.');
                return false;
            }
            clearFieldError(passInput);
            return true;
        }

        if (emailInput) {
            emailInput.addEventListener('blur', validateLoginEmail);
            emailInput.addEventListener('input', () => {
                if (emailInput.value.trim() && isValidEmail(emailInput.value)) {
                    clearFieldError(emailInput);
                }
            });
        }

        if (passInput) {
            passInput.addEventListener('input', () => {
                if (passInput.value) clearFieldError(passInput);
            });
            passInput.addEventListener('blur', validateLoginPassword);
        }

        loginForm.addEventListener('submit', (e) => {
            const vEmail = validateLoginEmail();
            const vPass = validateLoginPassword();

            if (!vEmail || !vPass) {
                e.preventDefault();
                if (!vEmail) emailInput?.focus();
                else if (!vPass) passInput?.focus();
            }
        });
    }

    // -------------------------------------------------------------
    // PASSWORD RESET REQUEST FORM VALIDATION
    // -------------------------------------------------------------
    const resetReqForm = document.querySelector('form[action*="password-reset"]:not([action*="confirm"])');
    if (resetReqForm) {
        const emailInput = document.getElementById('reset-email') || resetReqForm.querySelector('input[name="email"]');

        function validateResetEmail() {
            if (!emailInput) return true;
            const val = emailInput.value.trim();
            if (!val) {
                showFieldError(emailInput, 'Email address is required.');
                return false;
            }
            if (!isValidEmail(val)) {
                showFieldError(emailInput, 'Please enter a valid email address.');
                return false;
            }
            clearFieldError(emailInput);
            return true;
        }

        if (emailInput) {
            emailInput.addEventListener('blur', validateResetEmail);
            emailInput.addEventListener('input', () => {
                if (emailInput.value.trim() && isValidEmail(emailInput.value)) {
                    clearFieldError(emailInput);
                }
            });
        }

        resetReqForm.addEventListener('submit', (e) => {
            if (!validateResetEmail()) {
                e.preventDefault();
                emailInput?.focus();
            }
        });
    }

    // -------------------------------------------------------------
    // PASSWORD RESET CONFIRM FORM VALIDATION
    // -------------------------------------------------------------
    const resetConfirmForm = document.querySelector('form[action*="confirm"]');
    if (resetConfirmForm) {
        const emailInput = document.getElementById('reset-confirm-email') || resetConfirmForm.querySelector('input[name="email"]');
        const codeInput = document.getElementById('reset-code') || resetConfirmForm.querySelector('input[name="code"]');
        const newPassInput = document.getElementById('reset-new-password') || resetConfirmForm.querySelector('input[name="new_password"]');
        const confirmPassInput = document.getElementById('reset-confirm-new-password') || resetConfirmForm.querySelector('input[name="confirm_password"]');

        function validateConfirmEmail() {
            if (!emailInput) return true;
            const val = emailInput.value.trim();
            if (!val || !isValidEmail(val)) {
                showFieldError(emailInput, 'Please enter a valid email address.');
                return false;
            }
            clearFieldError(emailInput);
            return true;
        }

        function validateResetCode() {
            if (!codeInput) return true;
            const val = codeInput.value.trim();
            if (!val) {
                showFieldError(codeInput, 'Verification code is required.');
                return false;
            }
            if (!/^\d{6}$/.test(val)) {
                showFieldError(codeInput, 'Code must be exactly 6 digits.');
                return false;
            }
            clearFieldError(codeInput);
            return true;
        }

        function validateResetNewPass() {
            if (!newPassInput) return true;
            const val = newPassInput.value;
            if (!val) {
                showFieldError(newPassInput, 'New password is required.');
                return false;
            }
            if (val.length < 8) {
                showFieldError(newPassInput, 'Password must be at least 8 characters long.');
                return false;
            }
            clearFieldError(newPassInput);
            if (confirmPassInput && confirmPassInput.value) {
                validateResetConfirmPass();
            }
            return true;
        }

        function validateResetConfirmPass() {
            if (!confirmPassInput || !newPassInput) return true;
            const pVal = newPassInput.value;
            const cVal = confirmPassInput.value;
            if (!cVal) {
                showFieldError(confirmPassInput, 'Please confirm your new password.');
                return false;
            }
            if (pVal !== cVal) {
                showFieldError(confirmPassInput, 'Passwords do not match.');
                return false;
            }
            clearFieldError(confirmPassInput);
            return true;
        }

        if (emailInput) emailInput.addEventListener('blur', validateConfirmEmail);

        if (codeInput) {
            codeInput.addEventListener('input', () => {
                if (/^\d{6}$/.test(codeInput.value.trim())) {
                    clearFieldError(codeInput);
                }
            });
            codeInput.addEventListener('blur', validateResetCode);
        }

        if (newPassInput) {
            newPassInput.addEventListener('input', () => {
                if (newPassInput.value.length >= 8) clearFieldError(newPassInput);
                if (confirmPassInput && confirmPassInput.value) validateResetConfirmPass();
            });
            newPassInput.addEventListener('blur', validateResetNewPass);
        }

        if (confirmPassInput) {
            confirmPassInput.addEventListener('input', () => {
                if (newPassInput && confirmPassInput.value === newPassInput.value) {
                    clearFieldError(confirmPassInput);
                }
            });
            confirmPassInput.addEventListener('blur', validateResetConfirmPass);
        }

        resetConfirmForm.addEventListener('submit', (e) => {
            const vEmail = validateConfirmEmail();
            const vCode = validateResetCode();
            const vPass = validateResetNewPass();
            const vConfirm = validateResetConfirmPass();

            if (!vEmail || !vCode || !vPass || !vConfirm) {
                e.preventDefault();
                if (!vEmail) emailInput?.focus();
                else if (!vCode) codeInput?.focus();
                else if (!vPass) newPassInput?.focus();
                else if (!vConfirm) confirmPassInput?.focus();
            }
        });
    }
});
