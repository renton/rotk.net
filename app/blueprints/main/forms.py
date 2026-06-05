from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed
from wtforms import StringField, TextAreaField, BooleanField, SelectField,\
    SubmitField, IntegerField
from wtforms import FloatField
from wtforms_sqlalchemy.fields import QuerySelectMultipleField, QuerySelectField
from wtforms.validators import DataRequired, Length, Email, Regexp, Optional, URL, NumberRange
from wtforms import ValidationError
from tools.validators import validate_colour

from app.models import Faction, Role, UrlType, Location, LocationType, EventType

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
        query_factory=lambda: Role.query.order_by(Role.name).all(),
        get_label="name",
        # `size` makes the multi-select taller so the admin can see ~14
        # options at once instead of the browser default of ~4. Pair with
        # ctrl/cmd-click for multi-select. Sorted alphabetically in the
        # query_factory above.
        render_kw={"size": 14},
    )
    factions = QuerySelectMultipleField(
        "Factions (all, past and present)",
        query_factory=lambda: Faction.query.filter(Faction.is_hidden.is_(False))
                                            .order_by(Faction.name).all(),
        get_label="name",
        render_kw={"size": 14},
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
    edit page; posts to main.upload_portrait.

    `source_site` and `source_url` are optional credit fields — same
    columns the scrapers populate. Leaving them blank falls back to
    'Manual upload' so we always have something in source_site for the
    UI."""
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
    source_site = StringField(
        "Source site (credit label)",
        validators=[Optional(), Length(0, 255)],
        render_kw={"placeholder": "e.g. koei.fandom.com, Wikipedia, Personal photo"},
    )
    source_url = StringField(
        "Source URL (link back to original, optional)",
        validators=[Optional(), Length(0, 1000)],
        render_kw={"placeholder": "https://…"},
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


def _location_parent_label(loc):
    """Render a Location option label as "Name (Type)" when the type is
    set, falling back to just the name. The disambiguator helps admins
    pick the right parent when several locations share a name across
    different administrative tiers."""
    if loc.location_type is not None:
        return f"{loc.name} ({loc.location_type.name})"
    return loc.name


class EditLocationForm(FlaskForm):
    name = StringField("Name *", validators=[DataRequired(), Length(1, 255)])
    chinese_name = StringField("Chinese name", validators=[Length(0, 255)])
    aliases = StringField("Aliases (comma-delimited)", validators=[Length(0, 255)])
    # Both classification + nesting are optional — there's pre-existing
    # data without either, and not every Location fits the conventional
    # admin-division chain (passes, landmarks, etc.).
    location_type = QuerySelectField(
        "Type",
        query_factory=lambda: LocationType.query
                              .filter(LocationType.is_deleted.is_(False))
                              .filter(LocationType.is_hidden.is_(False))
                              .order_by(LocationType.name).all(),
        get_label='name',
        allow_blank=True,
        blank_text='— None —',
    )
    parent = QuerySelectField(
        "Parent location",
        query_factory=lambda: Location.query
                              .filter(Location.is_deleted.is_(False))
                              .order_by(Location.name).all(),
        get_label=_location_parent_label,
        allow_blank=True,
        blank_text='— None —',
    )
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
    # JSONB column shown as a JSON string in the admin UI. Validated
    # on submit (empty allowed; otherwise must parse and be a
    # Polygon or MultiPolygon GeoJSON Geometry).
    geojson = TextAreaField(
        "GeoJSON polygon",
        description="Optional. GeoJSON Geometry object (Polygon or "
                    "MultiPolygon). Used to draw a boundary on /map. "
                    "Ignored at render time if latitude + longitude "
                    "are also set.",
        render_kw={"rows": 6, "placeholder":
                   '{"type":"Polygon","coordinates":[[[lng,lat], ...]]}',
                   "spellcheck": "false",
                   "style": "font-family: ui-monospace, monospace; font-size: 0.85rem;"},
    )
    notes = TextAreaField("Notes")
    is_deleted = BooleanField("Is Deleted?")
    submit = SubmitField("Save")

    def validate_geojson(self, field):
        """Allow empty, otherwise require valid GeoJSON Polygon/
        MultiPolygon JSON. Parsed value is exposed on the field so
        the view can write the dict (not the string) into JSONB."""
        import json as _json
        from wtforms.validators import ValidationError
        raw = (field.data or '').strip()
        if not raw:
            field.parsed = None
            return
        try:
            obj = _json.loads(raw)
        except _json.JSONDecodeError as e:
            raise ValidationError(f"Not valid JSON: {e.msg} (line {e.lineno} col {e.colno})")
        if not isinstance(obj, dict):
            raise ValidationError("GeoJSON must be a JSON object")
        if obj.get('type') not in ('Polygon', 'MultiPolygon'):
            raise ValidationError(
                "GeoJSON 'type' must be 'Polygon' or 'MultiPolygon' "
                "(use the latitude/longitude fields for single points)"
            )
        if not isinstance(obj.get('coordinates'), list):
            raise ValidationError("'coordinates' must be an array")
        field.parsed = obj


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
    event_type = QuerySelectField(
        "Event type",
        query_factory=lambda: EventType.query.filter(EventType.is_deleted.is_(False))
                                              .filter(EventType.is_hidden.is_(False))
                                              .order_by(EventType.name).all(),
        get_label="name",
        allow_blank=True,
        blank_text='— None —',
        blank_value="",
    )
    date = StringField(
        "Date (free-form)",
        validators=[Length(0, 64)],
        render_kw={"placeholder": "e.g. 208 AD, or Winter 208 AD - Spring 209 AD"},
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


class MergeLocationForm(FlaskForm):
    """Empty form used for CSRF on the location merge POST. Same shape
    as MergeFactionForm — the actual `target_location_id` is a hidden
    field populated by admin_picker.js."""
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