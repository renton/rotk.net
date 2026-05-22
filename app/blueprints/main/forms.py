from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed
from wtforms import StringField, TextAreaField, BooleanField, SelectField,\
    SubmitField, IntegerField
from wtforms_sqlalchemy.fields import QuerySelectMultipleField, QuerySelectField
from wtforms.validators import DataRequired, Length, Email, Regexp, Optional
from wtforms import ValidationError
from tools.validators import validate_colour

from app.models import Faction, Role

class CharacterFilterForm(FlaskForm):

    search_query = StringField('Search', validators=[Optional()])

    role = QuerySelectField(
        "Role", 
        query_factory=lambda: Role.query.order_by(Role.name).all(),
        get_label="name",
        allow_blank=True,
        blank_text='--- Select a role ---',
        blank_value=""

    )
    any_faction = QuerySelectField(
        "Faction (any — past or present)",
        query_factory=lambda: Faction.query.order_by(Faction.name).all(),
        get_label="name",
        allow_blank=True,
        blank_text='--- Any faction ---',
        blank_value=""
    )

    primary_faction = QuerySelectField(
        "Primary faction only",
        query_factory=lambda: Faction.query.order_by(Faction.name).all(),
        get_label="name",
        allow_blank=True,
        blank_text='--- Any primary ---',
        blank_value=""
    )

    submit = SubmitField('Search')

class EditCharacterForm(FlaskForm):
    name = StringField("Name *", validators=[DataRequired()])
    chinese_name = StringField("Chinese Name")
    aliases = StringField("Aliases (comma-delimited)")
    courtesty_name = StringField("Courtesty Name")
    chinese_courtesty_name = StringField("Chinese Couresty Name")
    birth_date = StringField("Birth Date")
    death_date = StringField("Death Date")
    ancestral_home = StringField("Ancestral Home")
    notes = TextAreaField("Notes")

    roles = QuerySelectMultipleField(
        "Roles",
        query_factory=lambda: Role.query.all(),
        get_label="name"
    )
    factions = QuerySelectMultipleField(
        "Factions (all, past and present)",
        query_factory=lambda: Faction.query.all(),
        get_label="name"
    )
    primary_faction = QuerySelectField(
        "Primary faction (drives the highlight colour)",
        query_factory=lambda: Faction.query.order_by(Faction.name).all(),
        get_label="name",
        allow_blank=True,
        blank_text='— None —',
        blank_value="",
    )

    is_fictional = BooleanField("Is Fictional?")
    is_deleted = BooleanField("Is Deleted?")
    submit = SubmitField('Submit')

class EditFactionForm(FlaskForm):
    name = StringField("Name *", validators=[DataRequired()])
    font_colour = StringField(
        "Font Colour",
        validators=[validate_colour],
        render_kw={"type": "color"}
    )
    bg_colour = StringField(
        "Background Colour",
        validators=[validate_colour],
        render_kw={"type": "color"}
    )
    border_colour = StringField(
        "Border Colour",
        validators=[validate_colour],
        render_kw={"type": "color"}
    )

    icon = StringField("Icon")

    submit = SubmitField('Submit')

class UploadPortraitForm(FlaskForm):
    """Manually upload an image for a character, optionally tagging it and
    setting default/visible flags. Rendered as a fieldset on the character
    edit page; posts to main.upload_portrait."""
    image_file = FileField(
        "Image file",
        validators=[
            FileRequired(),
            FileAllowed(
                ['jpg', 'jpeg', 'png', 'gif', 'webp'],
                "Image files only (jpg, jpeg, png, gif, webp).",
            ),
        ],
    )
    tag_name = StringField(
        "Tag (existing or new — leave blank for no tag)",
        validators=[Optional()],
    )
    is_default = BooleanField(
        "Set as default for this character (auto-makes it visible)",
        default=False,
    )
    is_visible = BooleanField("Visible to the public", default=True)
    submit = SubmitField("Upload")


class EditRoleForm(FlaskForm):
    name = StringField("Name *", validators=[DataRequired()])
    font_colour = StringField(
        "Font Colour",
        validators=[validate_colour],
        render_kw={"type": "color"}
    )
    bg_colour = StringField(
        "Background Colour",
        validators=[validate_colour],
        render_kw={"type": "color"}
    )
    border_colour = StringField(
        "Border Colour",
        validators=[validate_colour],
        render_kw={"type": "color"}
    )

    icon = StringField("Icon")

    submit = SubmitField('Submit')