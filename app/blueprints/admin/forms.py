from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired

from tools.validators import validate_colour


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
