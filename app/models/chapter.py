from app import db
from sqlalchemy.ext.hybrid import hybrid_property

from app.models.abstract import AbstractObject

class Chapter(AbstractObject):
    chapter_num = db.Column(db.Integer, index=True, unique=True)

    content = db.Column(db.Text, default="", nullable=False)

    @hybrid_property
    def title(self):        
        return self.name

    def __repr__(self):
        return f'<Chapter {self.chapter_num}>'
