from app.models.abstract import \
    AbstractObject, AbstractTag

from app.models.character import Character, Faction, Role

from app.models.chapter import Chapter

from app.models.auth import User

from app.models.tag import Tag, TagAssociation

from app.models.url import Url, UrlType

from app.models.location import Location

from app.models.event import Event, EventType

from app.models.edit import Edit

from app.models.match_exclusion import MatchExclusion

# Importing the `audit` module registers ORM event listeners that stamp
# created_by / last_edited_by on every model with those columns. Must
# happen after the models above are imported so mapper config is settled.
from app.models import audit  # noqa: F401