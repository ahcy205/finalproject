from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from .models import (
    Dorm, OutingApply, Notice, Post, Comment,
    UserProfile, Inquiry, InquiryAnswer
)

class UserProfileSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)
    full_name = serializers.CharField(read_only=True)
    is_staff = serializers.SerializerMethodField()
    is_superuser = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = [
            'user_id', 'username', 'email', 'full_name',
            'department', 'reward_point', 'penalty_point',
            'is_staff', 'is_superuser'
        ]

    def get_is_staff(self, obj) -> bool:
        return obj.user.is_staff

    def get_is_superuser(self, obj) -> bool:
        return obj.user.is_superuser

class DormSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True)

    class Meta:
        model = Dorm
        fields = [
            'id', 'user_id', 'name', 'student_number','content', 'gender',
            'building_name', 'r_number', 'position', 'is_available'
        ]

class OutingApplySerializer(serializers.ModelSerializer):
    class Meta:
        model = OutingApply
        fields = ['id', 'name', 'student_number', 'out_date', 'applied_at', 'status']
        read_only_fields = ['applied_at', 'status']

class NoticeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notice
        fields = ['id', 'title', 'content', 'date', 'image']

class NoticeCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notice
        fields = ['title', 'content', 'image']

class CommentSerializer(serializers.ModelSerializer):
    author_id = serializers.IntegerField(source='author.id', read_only=True)
    anon_author = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = ['id', 'author_id', 'anon_author', 'content', 'created_at']

    def get_anon_author(self, obj) -> str:
        return f"{obj.author_id % 10000:04d}"

    def create(self, validated_data):
        request = self.context.get('request', None)
        if request and hasattr(request, "user"):
            validated_data['author'] = request.user
        return super().create(validated_data)

class PostSerializer(serializers.ModelSerializer):
    author_id = serializers.IntegerField(source='author.id', read_only=True)
    anon_author = serializers.SerializerMethodField()
    comments = CommentSerializer(many=True, read_only=True)

    class Meta:
        model = Post
        fields = [
            'id', 'author_id', 'anon_author',
            'title', 'content', 'image',
            'created_at', 'updated_at', 'comments'
        ]

    def get_anon_author(self, obj) -> str:
        return f"{obj.author_id % 10000:04d}"

    def create(self, validated_data):
        request = self.context.get('request', None)
        if request and hasattr(request, "user"):
            validated_data['author'] = request.user
        return super().create(validated_data)

class InquiryAnswerSerializer(serializers.ModelSerializer):
    admin_id = serializers.IntegerField(source='admin.id', read_only=True)
    admin_username = serializers.CharField(source='admin.username', read_only=True)

    class Meta:
        model = InquiryAnswer
        fields = ['id', 'admin_id', 'admin_username', 'answer', 'answered_at']

class InquirySerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    answer = serializers.SerializerMethodField()

    class Meta:
        model = Inquiry
        fields = ['id', 'user_id', 'username', 'title', 'content', 'created_at', 'answer']

    @extend_schema_field(InquiryAnswerSerializer(allow_null=True))
    def get_answer(self, obj):
        try:
            return InquiryAnswerSerializer(obj.inquiryanswer).data
        except InquiryAnswer.DoesNotExist:
            return None

class InquiryCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Inquiry
        fields = ['title', 'content']

class InquiryAnswerCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = InquiryAnswer
        fields = ['answer']

class ChatQuestionSerializer(serializers.Serializer):
    """학생 챗봇 질문 (knowledge.chat.MAX_QUESTION_LENGTH자까지)"""
    question = serializers.CharField(max_length=500, trim_whitespace=True)
