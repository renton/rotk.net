from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Length, Email, Regexp, EqualTo, ValidationError

from app.models import User
from tools.validators import validate_colour


class CreateUserForm(FlaskForm):
    """Admin-side form for creating a new user.

    Differs from auth.RegistrationForm in three ways: it's admin-only;
    new users are marked `confirmed=True` (no email verification needed
    when an admin vouches for them); and there's an explicit
    `is_administrator` checkbox so admins can stamp out other admins
    directly. The validation rules (email format, username pattern,
    password length, uniqueness) match the public registration form so
    behaviour stays consistent."""

    email = StringField('Email', validators=[
        DataRequired(), Length(1, 64), Email(),
    ])
    username = StringField('Username', validators=[
        DataRequired(),
        Length(3, 64),
        Regexp(
            r'^[A-Za-z][A-Za-z0-9_.]*$', 0,
            'Usernames must start with a letter and contain only letters, '
            'numbers, dots, or underscores.',
        ),
    ])
    password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=8, message='Password must be at least 8 characters.'),
        EqualTo('password2', message='Passwords must match.'),
    ])
    password2 = PasswordField('Confirm password', validators=[DataRequired()])
    is_administrator = BooleanField('Grant administrator access')
    submit = SubmitField('Create user')

    def validate_email(self, field):
        if User.query.filter_by(email=field.data.lower()).first():
            raise ValidationError('Email already registered.')

    def validate_username(self, field):
        if User.query.filter_by(username=field.data).first():
            raise ValidationError('Username already in use.')


class EditUrlTypeForm(FlaskForm):
    """Create/edit form for a UrlType (essentially a tag for Url categories).
    `icon` is a Font Awesome class string, e.g. 'fa-brands fa-wikipedia-w'
    — entered as free text; rendered as `<i class="{{ icon }}">` next to
    matching Url entries."""
    name = StringField("Name *", validators=[DataRequired(), Length(1, 255)])
    icon = StringField(
        "Font Awesome icon class",
        validators=[Length(0, 80)],
        render_kw={"placeholder": "e.g. fa-brands fa-wikipedia-w"},
    )
    font_colour = StringField(
        "Font Colour",
        validators=[validate_colour],
        render_kw={"type": "color"},
    )
    bg_colour = StringField(
        "Background Colour",
        validators=[validate_colour],
        render_kw={"type": "color"},
    )
    border_colour = StringField(
        "Border Colour",
        validators=[validate_colour],
        render_kw={"type": "color"},
    )
    submit = SubmitField("Save")


class EditTagForm(FlaskForm):
    name = StringField("Name *", validators=[DataRequired()])
    font_colour = StringField(
        "Font Colour",
        validators=[validate_colour],
        render_kw={"type": "color"},
    )
    bg_colour = StringField(
        "Background Colour",
        validators=[validate_colour],
        render_kw={"type": "color"},
    )
    border_colour = StringField(
        "Border Colour",
        validators=[validate_colour],
        render_kw={"type": "color"},
    )
    submit = SubmitField("Save")
