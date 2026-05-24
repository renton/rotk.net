from app import db


class MatchExclusion(db.Model):
    """Per-snippet "don't inline-tag this match" record.

    Used by the location-associations admin to suppress individual
    bad matches (a location alias that happens to overlap a person's
    name, for example) without losing the alias itself or all the
    legitimate matches that come with it.

    Polymorphic by target_type / target_id so the same table can
    later cover event / character match exclusions. The fingerprint
    that identifies a specific match is (match_text, before_snippet,
    after_snippet) — the same strings produced by find_*_mentions()
    in tools/book_parser.py, so render-time scans can dedupe via a
    set lookup."""

    __tablename__ = 'match_exclusion'

    id = db.Column(db.Integer, primary_key=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id', ondelete='CASCADE'), nullable=False)
    target_type = db.Column(db.String(32), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)
    match_text = db.Column(db.Text, nullable=False)
    before_snippet = db.Column(db.Text, nullable=False, default='')
    after_snippet = db.Column(db.Text, nullable=False, default='')
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    created_by = db.Column(db.String(64), nullable=False, default='rotk.net_system')

    def fingerprint(self):
        return (self.before_snippet or '', self.match_text or '', self.after_snippet or '')

    def __repr__(self):
        return f'<MatchExclusion ch={self.chapter_id} {self.target_type}:{self.target_id} {self.match_text!r}>'
