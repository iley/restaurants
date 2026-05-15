from django import forms

from .models import Photo, Restaurant, Visit


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


class VisitForm(forms.ModelForm):
    class Meta:
        model = Visit
        fields = ["date", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"class": "input", "type": "date"}),
            "notes": forms.Textarea(attrs={
                "class": "textarea",
                "rows": 2,
                "placeholder": "Notes (optional)",
            }),
        }


class PhotoForm(forms.ModelForm):
    class Meta:
        model = Photo
        fields = ["image", "caption"]
        widgets = {
            "caption": forms.TextInput(attrs={
                "class": "input",
                "placeholder": "Caption (optional)",
            }),
        }


class PhotoCaptionForm(forms.ModelForm):
    class Meta:
        model = Photo
        fields = ["caption"]
        widgets = {
            "caption": forms.TextInput(attrs={
                "class": "input",
                "placeholder": "Caption (optional)",
            }),
        }
