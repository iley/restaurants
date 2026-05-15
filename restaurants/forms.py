from django import forms

from .models import Restaurant


class RatingForm(forms.ModelForm):
    class Meta:
        model = Restaurant
        fields = ["rating"]
        widgets = {
            "rating": forms.NumberInput(attrs={
                "class": "input",
                "min": 1,
                "max": 10,
                "placeholder": "1–10 (blank = wishlist)",
            }),
        }


class CommentsForm(forms.ModelForm):
    class Meta:
        model = Restaurant
        fields = ["comments"]
        widgets = {
            "comments": forms.Textarea(attrs={
                "class": "textarea",
                "rows": 8,
                "placeholder": "Markdown supported",
            }),
        }
