from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models


class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    USER = "user", "Employee / Intern"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def get_by_natural_key(self, email):
        # Case-insensitive login.
        return self.get(email__iexact=email)

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required.")
        extra_fields.setdefault("role", Role.USER)
        user = self.model(email=self.normalize_email(email).lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields["role"] = Role.ADMIN
        extra_fields["is_superuser"] = True
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.USER)
    is_active = models.BooleanField(default=True)
    must_change_password = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return f"{self.full_name} <{self.email}>"

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def tracks_attendance(self) -> bool:
        """Admins are management-only: no schedule, attendance, reports, or tasks."""
        return self.role == Role.USER

    @property
    def is_staff(self) -> bool:
        # Django's built-in admin site is for superusers only. Product admins use /manage/.
        return self.is_active and self.is_superuser

    def clean(self):
        super().clean()
        if self.email:
            self.email = self.email.strip().lower()  # runs before the uniqueness check
        self._ensure_an_admin_remains()

    def _ensure_an_admin_remains(self):
        """The last active admin can't be deactivated or demoted."""
        if not self.pk:
            return
        before = User.objects.filter(pk=self.pk).values("role", "is_active").first()
        if not before or before["role"] != Role.ADMIN or not before["is_active"]:
            return
        if self.role == Role.ADMIN and self.is_active:
            return
        others = User.objects.filter(role=Role.ADMIN, is_active=True).exclude(pk=self.pk)
        if not others.exists():
            raise ValidationError(
                "This is the last active admin. Create or keep another active admin first."
            )