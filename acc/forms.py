from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class SignUpForm(forms.ModelForm):
    password = forms.CharField(
        label=_("Password"),
        widget=forms.PasswordInput(attrs={
            'id': 'signup-password',
            'placeholder': 'Create a strong password',
            'autocomplete': 'new-password',
            'class': 'w-full px-4 py-3 bg-surface-900/80 border border-slate-700/80 rounded-xl text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 transition-all duration-200 text-sm'
        })
    )
    confirm_password = forms.CharField(
        label=_("Confirm Password"),
        widget=forms.PasswordInput(attrs={
            'id': 'signup-confirm-password',
            'placeholder': 'Repeat your password',
            'autocomplete': 'new-password',
            'class': 'w-full px-4 py-3 bg-surface-900/80 border border-slate-700/80 rounded-xl text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 transition-all duration-200 text-sm'
        })
    )
    terms = forms.BooleanField(
        required=True,
        initial=True,
        error_messages={'required': _('You must agree to the Terms of Service to create an account.')},
        widget=forms.CheckboxInput(attrs={
            'id': 'signup-terms',
            'class': 'w-4 h-4 rounded bg-surface-900 border-slate-700 text-brand-500 focus:ring-brand-500/30 focus:ring-offset-0 focus:ring-2 transition'
        })
    )

    class Meta:
        model = User
        fields = ['email']
        widgets = {
            'email': forms.EmailInput(attrs={
                'id': 'signup-email',
                'placeholder': 'you@domain.com',
                'autocomplete': 'email',
                'class': 'w-full px-4 py-3 bg-surface-900/80 border border-slate-700/80 rounded-xl text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 transition-all duration-200 text-sm'
            })
        }

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError(_("An account with this email address already exists."))
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')

        if password and confirm_password:
            if password != confirm_password:
                self.add_error('confirm_password', _("Passwords do not match."))
            else:
                try:
                    validate_password(password)
                except ValidationError as e:
                    self.add_error('password', e)

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class LoginForm(forms.Form):
    email = forms.EmailField(
        label=_("Email address"),
        widget=forms.EmailInput(attrs={
            'id': 'login-email',
            'placeholder': 'you@domain.com',
            'autocomplete': 'email',
            'class': 'w-full px-4 py-3 bg-surface-900/80 border border-slate-700/80 rounded-xl text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 transition-all duration-200 text-sm'
        })
    )
    password = forms.CharField(
        label=_("Password"),
        widget=forms.PasswordInput(attrs={
            'id': 'login-password',
            'placeholder': 'Enter your password',
            'autocomplete': 'current-password',
            'class': 'w-full px-4 py-3 bg-surface-900/80 border border-slate-700/80 rounded-xl text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 transition-all duration-200 text-sm'
        })
    )
    remember_me = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'id': 'login-remember-me',
            'class': 'w-4 h-4 rounded bg-surface-900 border-slate-700 text-brand-500 focus:ring-brand-500/30 focus:ring-offset-0 focus:ring-2 transition'
        })
    )


class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(
        label=_("Registered Email"),
        widget=forms.EmailInput(attrs={
            'id': 'reset-email',
            'placeholder': 'Enter your account email',
            'autocomplete': 'email',
            'class': 'w-full px-4 py-3 bg-surface-900/80 border border-slate-700/80 rounded-xl text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 transition-all duration-200 text-sm'
        })
    )


class PasswordResetConfirmForm(forms.Form):
    email = forms.EmailField(
        label=_("Email Address"),
        widget=forms.EmailInput(attrs={
            'id': 'reset-confirm-email',
            'placeholder': 'you@domain.com',
            'class': 'w-full px-4 py-3 bg-surface-900/80 border border-slate-700/80 rounded-xl text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 transition-all duration-200 text-sm'
        })
    )
    code = forms.CharField(
        label=_("6-Digit Verification Code"),
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={
            'id': 'reset-code',
            'placeholder': '• • • • • •',
            'maxlength': '6',
            'autocomplete': 'one-time-code',
            'class': 'w-full px-4 py-3 tracking-widest text-center font-mono text-lg font-bold bg-surface-900/80 border border-slate-700/80 rounded-xl text-brand-400 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 transition-all duration-200'
        })
    )
    new_password = forms.CharField(
        label=_("New Password"),
        widget=forms.PasswordInput(attrs={
            'id': 'reset-new-password',
            'placeholder': 'Enter new password',
            'autocomplete': 'new-password',
            'class': 'w-full px-4 py-3 bg-surface-900/80 border border-slate-700/80 rounded-xl text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 transition-all duration-200 text-sm'
        })
    )
    confirm_password = forms.CharField(
        label=_("Confirm New Password"),
        widget=forms.PasswordInput(attrs={
            'id': 'reset-confirm-new-password',
            'placeholder': 'Confirm new password',
            'autocomplete': 'new-password',
            'class': 'w-full px-4 py-3 bg-surface-900/80 border border-slate-700/80 rounded-xl text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 transition-all duration-200 text-sm'
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')

        if new_password and confirm_password:
            if new_password != confirm_password:
                self.add_error('confirm_password', _("Passwords do not match."))
            else:
                try:
                    validate_password(new_password)
                except ValidationError as e:
                    self.add_error('new_password', e)

        return cleaned_data
