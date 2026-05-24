from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed
from wtforms import StringField, TextAreaField, BooleanField, SelectField,\
    SubmitField, IntegerField
from wtforms import FloatField
from wtforms_sqlalchemy.fields import QuerySelectMultipleField, QuerySelectField
from wtforms.validators import DataRequired, Length, Email, Regexp, Optional, URL, NumberRange
from wtforms import ValidationError
from tools.validators import validate_colour

from app.models import Faction, Role, UrlType, Location

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
        query_factory=lambda: Faction.query.filter(Faction.is_hidden.is_(False)).order_by(Faction.name).all(),
        get_label="name",
        allow_blank=True,
        blank_text='--- Any faction ---',
        blank_value=""
    )

    primary_faction = QuerySelectField(
        "Primary faction only",
        query_factory=lambda: Faction.query.filter(Faction.is_hidden.is_(False)).order_by(Faction.name).all(),
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
        query_factory=lambda: Faction.query.filter(Faction.is_hidden.is_(False)).all(),
        get_label="name"
    )
    primary_faction = QuerySelectField(
        "Primary faction (drives the highlight colour)",
        query_factory=lambda: Faction.query.filter(Faction.is_hidden.is_(False)).order_by(Faction.name).all(),
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


class AddUrlForm(FlaskForm):
    """Attach a new external link to a first-class object (currently
    surfaced only on the character edit page). `name` doubles as the
    visible description; `url` is the actual link target; `favicon` is
    an optional static-relative path to a small image rendered alongside
    the link; `url_type` is the UrlType pick."""
    name = StringField(
        "Description *",
        validators=[DataRequired(), Length(1, 255)],
        render_kw={"placeholder": "e.g. Wikipedia entry"},
    )
    url = StringField(
        "URL *",
        validators=[
            DataRequired(),
            Length(1, 2048),
            URL(require_tld=True, message="Enter a valid URL (including http(s)://)."),
        ],
        render_kw={"placeholder": "https://en.wikipedia.org/wiki/Cao_Cao"},
    )
    favicon = StringField(
        "Favicon path (under app/static/, optional)",
        validators=[Length(0, 255), Optional()],
        render_kw={"placeholder": "e.g. favicons/wikipedia.png"},
    )
    url_type = QuerySelectField(
        "Type",
        query_factory=lambda: UrlType.query.filter(UrlType.is_hidden.is_(False))
                                              .order_by(UrlType.name).all(),
        get_label="name",
        allow_blank=True,
        blank_text='— Untyped —',
        blank_value="",
    )
    submit = SubmitField("Add link")


class EditLocationForm(FlaskForm):
    name = StringField("Name *", validators=[DataRequired(), Length(1, 255)])
    chinese_name = StringField("Chinese name", validators=[Length(0, 255)])
    aliases = StringField("Aliases (comma-delimited)", validators=[Length(0, 255)])
    latitude = FloatField(
        "Latitude",
        validators=[Optional(), NumberRange(min=-90, max=90)],
        render_kw={"step": "any", "placeholder": "e.g. 34.7472"},
    )
    longitude = FloatField(
        "Longitude",
        validators=[Optional(), NumberRange(min=-180, max=180)],
        render_kw={"step": "any", "placeholder": "e.g. 113.6253"},
    )
    notes = TextAreaField("Notes")
    is_deleted = BooleanField("Is Deleted?")
    submit = SubmitField("Save")


class EditEventForm(FlaskForm):
    name = StringField("Name *", validators=[DataRequired(), Length(1, 255)])
    chinese_name = StringField("Chinese name", validators=[Length(0, 255)])
    aliases = StringField(
        "Aliases / keywords (comma-delimited)",
        validators=[Length(0, 255)],
        render_kw={"placeholder": "Battle of Red Cliffs, Chibi, 赤壁之战"},
    )
    location = QuerySelectField(
        "Location",
        query_factory=lambda: Location.query.filter(Location.is_deleted.is_(False))
                                              .order_by(Location.name).all(),
        get_label="name",
        allow_blank=True,
        blank_text='— None —',
        blank_value="",
    )
    geo_point_override = StringField(
        "Geo-point override (free-form)",
        validators=[Length(0, 255)],
        render_kw={"placeholder": "e.g. 29.7359,113.0156 — overrides the linked Location"},
    )
    hide_on_map = BooleanField("Hide on map")
    notes = TextAreaField("Notes")
    is_deleted = BooleanField("Is Deleted?")
    submit = SubmitField("Save")


class AddEventAssociationForm(FlaskForm):
    """Empty form for CSRF on the event-associations admin Add flow. The
    `search_terms` (comma-delimited) and `event_id` fields are read from
    request.form manually so we can split + validate the keyword list
    cleanly."""
    submit = SubmitField("Add")


class MergeFactionForm(FlaskForm):
    """Empty form used for CSRF on the faction merge POST. The actual
    `target_faction_id` is a hidden field populated by admin_picker.js
    when the admin picks from the datalist; the view validates it
    manually so we don't have to model it on the form too."""
    submit = SubmitField("Merge & hide")


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