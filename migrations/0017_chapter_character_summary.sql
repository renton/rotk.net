-- Per-(chapter, character) free-form summary string.
--
-- Mirrors `chapter_character.keywords` — text on the association
-- row capturing a fact that doesn't live on either parent. Holds a
-- short editorial writeup of what the character actually does in
-- this chapter (e.g. "Liu Bei's emissary; brokers the marriage
-- alliance with Sun Quan and escorts Lady Sun back to Jingzhou").
-- Empty by default; visible in the chapter sidebar's Characters
-- accordion when set; edited from /admin/chapter-associations.
--
-- Idempotent.

ALTER TABLE chapter_character
    ADD COLUMN IF NOT EXISTS summary TEXT NOT NULL DEFAULT '';
