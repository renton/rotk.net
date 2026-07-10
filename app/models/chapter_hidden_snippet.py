from app import db


class ChapterHiddenSnippet(db.Model):
    """Per-chapter prose span to hide from the public reader.

    Semantically distinct from MatchExclusion:
      * MatchExclusion suppresses a NEEDLE's pill-wrapping at a
        specific occurrence — the text still appears in prose, just
        without the character/location badge.
      * ChapterHiddenSnippet removes the text ENTIRELY from the
        rendered chapter for public viewers. Admin editors see it
        as strikethrough with a Restore affordance.

    Fingerprint (before_snippet, match_text, after_snippet) mirrors
    MatchExclusion's shape — content-addressed so the hide travels
    with the content and survives rescrapes as long as the ~60-char
    context window is intact.
    """
    __tablename__ = 'chapter_hidden_snippet'

    id = db.Column(db.Integer, primary_key=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id', ondelete='CASCADE'), nullable=False)
    match_text = db.Column(db.Text, nullable=False)
    before_snippet = db.Column(db.Text, nullable=False, default='')
    after_snippet = db.Column(db.Text, nullable=False, default='')
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    created_by = db.Column(db.String(64), nullable=False, default='rotk.net_system')

    def __repr__(self):
        return f'<ChapterHiddenSnippet ch={self.chapter_id} {self.match_text!r}>'
