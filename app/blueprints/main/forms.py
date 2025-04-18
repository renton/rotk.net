from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, BooleanField, SelectField,\
    SubmitField, IntegerField
from wtforms_sqlalchemy.fields import QuerySelectMultipleField, QuerySelectField
from wtforms.validators import DataRequired, Length, Email, Regexp
from wtforms import ValidationError
from tools.validators import validate_colour

from app.models import Faction, Role

class CharacterFilterForm(FlaskForm):
    role = QuerySelectField(
        "Role", 
        query_factory=lambda: Role.query.order_by(Role.name).all(),
        get_label="name",
        allow_blank=True,
        blank_text='--- Select a role ---',
        blank_value=""

    )
    faction = QuerySelectField(
        "Faction", 
        query_factory=lambda: Faction.query.order_by(Faction.name).all(),
        get_label="name",
        allow_blank=True,
        blank_text='--- Select a faction ---',
        blank_value=""
    )

    search_past_factions = BooleanField("Search past factions", default=True)

    submit = SubmitField('Filter')

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
        "Factions", 
        query_factory=lambda: Faction.query.all(),
        get_label="name"
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