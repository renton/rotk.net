from app import db


class Annotation(db.Model):
    """Per-(chapter, paragraph) annotation.

    Section identity is content-addressed: `section_text` is the
    whitespace-normalised full text of the paragraph the annotation
    applies to. Render time compares each <p>'s normalised text to
    `section_text` to decide which annotations sit on it.

    is_public determines visibility:
      * True — visible to everyone (public reader + admin), black icon.
      * False — visible only to admins, red icon + exclamation.
    """
    __tablename__ = 'annotation'

    id = db.Column(db.Integer, primary_key=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id', ondelete='CASCADE'), nullable=False)
    section_text = db.Column(db.Text, nullable=False)
    body = db.Column(db.Text, nullable=False)
    is_public = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    created_by = db.Column(db.String(64), nullable=False, default='rotk.net_system')

    chapter = db.relationship('Chapter')

    def __repr__(self):
        return f'<Annotation id={self.id} ch={self.chapter_id} public={self.is_public}>'
