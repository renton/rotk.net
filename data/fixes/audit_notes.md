# Chapter audit tracker (ch2–ch58)

Working notes for the batch audit producing `data/fixes/chN_audit.json`
files. Apply each with
`flask apply-fixes data/fixes/chN_audit.json --apply` on ambrose
(removal ops prompt an extra confirm). Files are independent and
idempotent — order doesn't matter, duplicates no-op.

Audit checks per chapter: false-positive character associations
(substring keyword matches), wrong-person keywords, missing
location/event associations, event keywords that never match the prose,
relationships stated in prose but missing, and chapter-character
summaries (add missing / rewrite thin ones).

## Progress

- [x] ch1 — 14 ops (done before this batch)
- [ ] ch2
- [ ] ch3
- [ ] ch4
- [ ] ch5
- [ ] ch6
- [ ] ch7
- [ ] ch8
- [ ] ch9
- [ ] ch10
- [ ] ch11
- [ ] ch12
- [ ] ch13
- [ ] ch14
- [ ] ch15
- [ ] ch16
- [ ] ch17
- [ ] ch18
- [ ] ch19
- [ ] ch20
- [ ] ch21
- [ ] ch22
- [ ] ch23
- [ ] ch24
- [ ] ch25
- [ ] ch26
- [ ] ch27
- [ ] ch28
- [ ] ch29
- [ ] ch30
- [ ] ch31
- [ ] ch32
- [ ] ch33
- [ ] ch34
- [ ] ch35
- [ ] ch36
- [ ] ch37
- [ ] ch38
- [ ] ch39
- [ ] ch40
- [ ] ch41
- [ ] ch42
- [ ] ch43
- [ ] ch44
- [ ] ch45
- [ ] ch46
- [ ] ch47
- [ ] ch48
- [ ] ch49
- [ ] ch50
- [ ] ch51
- [ ] ch52
- [ ] ch53
- [ ] ch54
- [ ] ch55
- [ ] ch56
- [ ] ch57
- [ ] ch58
- [x] ch59 — 15 ops (done earlier)

## Relationships proposed across fix files (dedupe list)

Fix files aren't applied yet, so live-data reads won't show these.
Check here before proposing a relationship op.

From ch1_audit.json:
- Cao Song [130] → Cao Cao [86] Parent/Child
- Cao Teng [132] → Cao Song [130] Parent/Child (adoptive)
- Zhang Jue [3154] ↔ Zhang Bao [3069] Sibling
- Zhang Jue [3154] ↔ Zhang Liang [3164] Sibling
- Zhang Bao [3069] ↔ Zhang Liang [3164] Sibling
- Liu Yuanqi [1471] → Liu Bei [1311] Pibling/Nibling
- Liu Sheng [3585] → Liu Bei [1311] Ancestor/Descendent
- Liu Qi (Emperor Jing) [3590] → Liu Sheng [3585] Parent/Child
- Emperor Ling [1351] → Liu Xie (Emperor Xian) [1434] Parent/Child

## Report-only findings (need manual action, no apply-fixes op exists)

From ch1:
- "Yuan Mountains" (ch1 ¶6 omen scene) has no Location row — create via
  admin UI + associate if wanted.
- Liu Bei's father "Liu Hong" has no Character row (ch1 keyword fix
  just untags him). Five Liu Hong rows exist (1351–1355); 1352 (Jin,
  Zhongjia) vs 1353 (bare "Han politician") look like possible dupes.
