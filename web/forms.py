from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from dorm.models import Comment, Post, Inquiry, InquiryAnswer, OutingApply, Notice


class CustomSignupForm(UserCreationForm):
    email = forms.EmailField(required=True)
    full_name = forms.CharField(required=True)
    department = forms.CharField(required=True)
    phone_number = forms.CharField(required=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'full_name', 'department', 'phone_number', 'password1', 'password2')

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("이미 사용 중인 학번입니다.")
        return username

class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': '댓글을 입력하세요...',
                'style': 'resize: vertical;',
                'id': 'comment-textarea'
            })
        }
        labels = {
            'content': ''
        }

class PostForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ['title', 'content', 'image']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '제목을 입력하세요'
            }),
            'content': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 10,
                'placeholder': '내용을 입력하세요'
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            })
        }
        labels = {
            'title': '제목',
            'content': '내용',
            'image': '이미지 첨부'
        }


class InquiryForm(forms.ModelForm):
    class Meta:
        model = Inquiry
        fields = ['title', 'content']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'content': forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
        }

class InquiryAnswerForm(forms.ModelForm):
    class Meta:
        model = InquiryAnswer
        fields = ['answer']
        widgets = {
            'answer': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': '답변 내용을 입력하세요...'
            }),
        }


class OutingApplyForm(forms.ModelForm):
    class Meta:
        model = OutingApply
        fields = ['name', 'student_number', 'out_date']
        widgets = {
            'out_date': forms.DateInput(attrs={'type': 'date'})
        }

class NoticeForm(forms.ModelForm):
    class Meta:
        model = Notice
        fields = ['title', 'content', 'image']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'content': forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
            'image': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }