from functools import wraps
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse


def ops_required(view_func):
    """
    Decorator for views that checks that the user is logged in and
    is an Ops staff member (user.is_ops, user.is_superuser, or user.is_staff).
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            path = request.get_full_path()
            return redirect(f"{reverse('acc:login')}?{REDIRECT_FIELD_NAME}={path}")

        has_ops_access = bool(
            getattr(request.user, 'is_ops', False)
            or request.user.is_superuser
            or request.user.is_staff
        )

        if not has_ops_access:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
                return JsonResponse({
                    'success': False,
                    'error': 'Permission denied. Ops access required.'
                }, status=403)
            return render(request, 'ops/access_denied.html', {
                'required_role': 'Ops Admin',
            }, status=403)

        return view_func(request, *args, **kwargs)

    return _wrapped_view


def ops_or_marketer_required(view_func):
    """
    Decorator for views accessible by both Ops staff and Marketers.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            path = request.get_full_path()
            return redirect(f"{reverse('acc:login')}?{REDIRECT_FIELD_NAME}={path}")

        has_access = bool(
            getattr(request.user, 'is_ops', False)
            or getattr(request.user, 'is_marketer', False)
            or request.user.is_superuser
            or request.user.is_staff
        )

        if not has_access:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
                return JsonResponse({
                    'success': False,
                    'error': 'Permission denied. Ops or Marketer access required.'
                }, status=403)
            return render(request, 'ops/access_denied.html', {
                'required_role': 'Ops or Marketer',
            }, status=403)

        return view_func(request, *args, **kwargs)

    return _wrapped_view
