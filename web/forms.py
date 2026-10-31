from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from dorm.models import Comment, Post, Inquiry, InquiryAnswer, OutingApply, Notice


class CustomSignupForm(UserCreationForm):
    email = forms.EmailField(required=True, error_messages={
        'required': '이메일을 입력해 주세요.', 'invalid': '이메일 주소 형식을 확인해 주세요.'})
    full_name = forms.CharField(required=True, error_messages={'required': '이름을 입력해 주세요.'})
    department = forms.CharField(required=True, error_messages={'required': '학과를 입력해 주세요.'})
    phone_number = forms.CharField(required=True, error_messages={'required': '전화번호를 입력해 주세요.'})
    error_messages = {**UserCreationForm.error_messages,
                      'password_mismatch': '두 비밀번호가 달라요. 같게 입력해 주세요.'}

    class Meta:
        model = User
        fields = ('username', 'email', 'full_name', 'department', 'phone_number', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].error_messages['required'] = '학번을 입력해 주세요.'
        self.fields['password1'].error_messages['required'] = '비밀번호를 입력해 주세요.'
        self.fields['password2'].error_messages['required'] = '비밀번호를 한 번 더 입력해 주세요.'

    def validate_password_for_user(self, user, **kwargs):
        # Django는 비밀번호 규칙 오류를 '비밀번호 확인' 칸에 붙인다. 규칙은 '비밀번호' 칸의 일이라 그쪽에 표시한다.
        super().validate_password_for_user(user, password_field_name='password1')

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("이미 가입한 학번이에요. 로그인해 주세요.")
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

class ChatQuestionForm(forms.Form):
    """학생 챗봇 질문 (knowledge.chat.MAX_QUESTION_LENGTH자까지)"""
    question = forms.CharField(max_length=500, strip=True, error_messages={
        'required': '질문을 입력해 주세요.',
        'max_length': '질문은 500자까지 입력할 수 있어요.',
    })
    # 이어지는 대화 번호. 없거나 형식이 틀리면 새 대화로 본다 (앞 대화 내용은 서버에만 있음)
    conversation_id = forms.CharField(max_length=64, required=False)


class ChatFeedbackForm(forms.Form):
    """챗봇 답 평가 (👍/👎와 👎 이유)"""
    log_id = forms.IntegerField(min_value=1)
    token = forms.CharField(max_length=64)
    rating = forms.ChoiceField(choices=[('up', '👍'), ('down', '👎')])
    reason = forms.ChoiceField(choices=[('', ''), ('wrong', '틀림'), ('irrelevant', '질문과 관계없음'),
                                        ('insufficient', '부족함')], required=False)


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