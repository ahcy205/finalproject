from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


def post_image_path(instance, filename):
    return f"posts/{instance.author.id}/{filename}"


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    full_name = models.CharField(max_length=100, blank=True, default="")
    department = models.CharField(max_length=50, blank=True, default="")
    phone_number = models.CharField(max_length=20, blank=True, default="")
    reward_point = models.IntegerField(default=0)
    penalty_point = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.full_name or self.user.username} ({self.department})"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


class Dorm(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=20, blank=True, default="")
    student_number = models.CharField(max_length=10, unique=True)
    content = models.TextField(blank=True, null=True, default="")
    GENDER_CHOICES = [("male", "Male"), ("female", "Female")]
    gender = models.CharField(max_length=6, choices=GENDER_CHOICES)
    building_name = models.CharField(max_length=50, blank=True, default="")
    r_number = models.IntegerField(default=0)
    position = models.IntegerField(
        choices=[(0, "미배정"), (1, "1"), (2, "2"), (3, "3"), (4, "4")],
        default=0
    )
    is_available = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} - {self.student_number} - {self.gender}"


class OutingApply(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Standby'),
        ('approved', 'approve'),
        ('rejected', 'not approve'),
    ]

    # 신청한 계정. 이름·학번은 신청서에 적은 값 그대로 보관한다.
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='outing_applies')
    name = models.CharField(max_length=20)
    student_number = models.CharField(max_length=10)
    out_date = models.DateField()
    applied_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='pending'
    )

    def __str__(self):
        return f"{self.name} - {self.student_number} - {self.out_date} ({self.get_status_display()})"


class Inquiry(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=100)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.user.username})"


class InquiryAnswer(models.Model):
    inquiry = models.OneToOneField(Inquiry, on_delete=models.CASCADE)
    admin = models.ForeignKey(User, on_delete=models.CASCADE, related_name='inquiry_answers')
    answer = models.TextField()
    answered_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"answer ({self.inquiry.title})"


class Post(models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    content = models.TextField()
    image = models.ImageField(upload_to=post_image_path, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"[{self.author.username}] {self.title}"


class Like(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='likes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'post')

    def __str__(self):
        return f"{self.user.username} likes Post({self.post.id})"


class Comment(models.Model):
    post = models.ForeignKey(Post, related_name='comments', on_delete=models.CASCADE)
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.author.username}] comment on {self.post.id}"


class Notice(models.Model):
    title   = models.CharField(max_length=200)
    content = models.TextField()
    image   = models.ImageField(
        upload_to='notices/%Y/%m/%d/',
        blank=True,
        null=True
    )
    date    = models.DateField(auto_now_add=True)

    def __str__(self):
        return self.title
