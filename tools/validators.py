import re
from wtforms import ValidationError

def validate_colour(form, field):
    if not re.match(r"^#(?:[0-9a-fA-F]{3}){1,2}$", field.data):
        raise ValidationError("Please select a valid colour.")