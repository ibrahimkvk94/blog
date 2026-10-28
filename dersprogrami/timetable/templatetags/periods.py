"""Ders saatinin belirli gündeki saatleri (günlere göre farklı saat varsa o)."""

from django import template

register = template.Library()


@register.filter
def start_on(period, day):
    """{{ period|start_on:gun }} → o günün başlangıç saati (time) ya da None."""
    return period.times(day)[0] if period else None


@register.filter
def span_on(period, day):
    """{{ period|span_on:gun }} → "08:00–08:40"."""
    return period.span(day) if period else ""
