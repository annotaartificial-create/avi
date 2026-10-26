import logging
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib import messages
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.utils.translation import gettext_lazy as _

from main.models import SiteSetting
from .models import PasswordResetCode
from .forms import (
    SignUpForm,
    LoginForm,
    PasswordResetRequestForm,
    PasswordResetConfirmForm
)

logger = logging.getLogger(__name__)
User = get_user_model()


def signup_view(request):
    if request.user.is_authenticated:
        return redirect('engine:game')

    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Log the user in immediately after signup
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            site_name = SiteSetting.load().name
            messages.success(request, f"Welcome to {site_name}, {user.display_name}! Your account has been created.")
            return redirect('engine:game')
    else:
        form = SignUpForm()

    return render(request, 'acc/signup.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('engine:game')

    next_url = request.GET.get('next')
    if not next_url or next_url == 'acc:dashboard':
        next_url = 'engine:game'

    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email'].strip().lower()
            password = form.cleaned_data['password']
            remember_me = form.cleaned_data.get('remember_me')

            # Django's ModelBackend supports USERNAME_FIELD='email'
            user = authenticate(request, username=email, password=password)
            if user is None:
                user = authenticate(request, email=email, password=password)

            if user is not None:
                if user.is_active:
                    login(request, user)
                    if not remember_me:
                        # Session expires when browser closes
                        request.session.set_expiry(0)
                    else:
                        # 2 weeks session
                        request.session.set_expiry(1209600)
                    
                    messages.success(request, f"Welcome back, {user.display_name}!")
                    target_url = request.POST.get('next') or next_url
                    if not target_url or target_url == 'acc:dashboard':
                        target_url = 'engine:game'
                    return redirect(target_url)
                else:
                    form.add_error(None, _("This account has been disabled. Please contact support."))
            else:
                form.add_error(None, _("Invalid email or password. Please try again."))
    else:
        form = LoginForm()

    return render(request, 'acc/login.html', {'form': form, 'next': next_url})


def logout_view(request):
    logout(request)
    messages.info(request, _("You have been logged out securely."))
    return redirect('acc:login')


def password_reset_request_view(request):
    if request.user.is_authenticated:
        return redirect('engine:game')

    if request.method == 'POST':
        form = PasswordResetRequestForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email'].strip().lower()
            user = User.objects.filter(email__iexact=email).first()

            if user and user.is_active:
                reset_code = PasswordResetCode.generate_code_for_user(user)
                site_conf = SiteSetting.load()
                
                # Send verification code via email
                subject = f"{site_conf.name} - Your Password Reset Code"
                message = (
                    f"Hello,\n\n"
                    f"You requested to reset your password for your {site_conf.name} account.\n"
                    f"Your 6-digit verification code is:\n\n"
                    f"    {reset_code.code}\n\n"
                    f"This code is valid for 15 minutes. If you did not request this, please ignore this email.\n\n"
                    f"— {site_conf.name} Security Team"
                )
                try:
                    send_mail(
                        subject,
                        message,
                        site_conf.contact_email,
                        [email],
                        fail_silently=False,
                    )
                except Exception as e:
                    logger.error(f"Failed to send password reset email: {e}")

            # Store email in session to prefill the next step
            request.session['reset_email'] = email
            messages.success(request, _("If an active account exists with that email, a 6-digit verification code has been sent."))
            return redirect('acc:password_reset_confirm')
    else:
        form = PasswordResetRequestForm()

    return render(request, 'acc/password_reset.html', {'form': form})


def password_reset_confirm_view(request):
    if request.user.is_authenticated:
        return redirect('engine:game')

    prefilled_email = request.session.get('reset_email', request.GET.get('email', ''))

    if request.method == 'POST':
        form = PasswordResetConfirmForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email'].strip().lower()
            code = form.cleaned_data['code'].strip()
            new_password = form.cleaned_data['new_password']

            user = User.objects.filter(email__iexact=email).first()
            if not user:
                form.add_error(None, _("Invalid email or reset code."))
            else:
                reset_record = PasswordResetCode.objects.filter(
                    user=user,
                    code=code,
                    is_used=False
                ).first()

                if reset_record and reset_record.is_valid():
                    user.set_password(new_password)
                    user.save()
                    reset_record.is_used = True
                    reset_record.save()
                    
                    # Clear session email
                    request.session.pop('reset_email', None)

                    messages.success(request, _("Your password has been reset successfully! You can now log in."))
                    return redirect('acc:login')
                else:
                    form.add_error(None, _("The code is invalid or has expired. Please request a new one."))
    else:
        form = PasswordResetConfirmForm(initial={'email': prefilled_email})

    return render(request, 'acc/password_reset_confirm.html', {'form': form, 'email': prefilled_email})


@login_required
def dashboard_view(request):
    """
    Authenticated landing view showing user profile & account metadata.
    """
    return render(request, 'acc/dashboard.html', {'user': request.user})
