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

## Relationship type ids (verified live 2026-07-12)

Parent/Child=1, Husband/Wife=3, Sworn Brother=4, Sibling=5, Cousin=7,
Pibling/Nibling=10, Grandparent/Grandchild=14,
Great-Grandparent/Grandchild=16, Ancestor/Descendant=18.
No adoptive/step/liege types exist — note adoptive ties in `_note` on a
Parent/Child op (ch1 did this for Cao Teng→Cao Song).

## Progress

- [x] ch1 — 14 ops (done before this batch; APPLIED by Ren — its 9 relationships are live, and he created Liu Hong [3849] = Liu Bei's father)
- [x] ch2 — 75 ops (Zhang Bao 'Zhang Ba' spelling, Liu Xian [3601] dup removal, Liang Da 'Tai' alias fix, 17 relationships, ~35 summary rewrites)
- [x] ch3 — 37 ops (Massacre of the Eunuchs event added to ch3, Shang/Taishan Commandery false-positive removals, 5 relationships incl. both Lü Bu adoptions, ~27 summary rewrites)
- [x] ch4 — 17 ops (Empress Dong added to ch4, Qiao keyword, 3 relationships, 12 summary rewrites) + data/fixes/sex_audit.json (73 ops: every Empress/Lady/Consort + Diao Chan/Qiaos/Cai Yan/Sun Ren had sex=male)
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

ch1_audit.json: APPLIED — all 9 relationships live in DB (verified 2026-07-12).
Live baseline also includes: Liu Yan→Liu Zhang, Liu Bei→Liu Shan,
Zhang Ling/Zhang Heng/Zhang Lu chain, Ma Teng→Ma Chao (+uncle Ma Dai,
cousin Ma Chao↔Ma Dai), Xun Yu→Xun You (uncle), Han Sui↔Ma Teng sworn,
Liu Bei/Guan Yu/Zhang Fei sworn triangle, Liu Hong[3849]→Liu Bei.

From ch2_audit.json (17):
- He Jin [844] ↔ Empress He [831] Sibling; He Jin ↔ He Miao [852] Sibling;
  He Miao ↔ Empress He Sibling
- Lady of Wuyang [2502] → He Jin, → He Miao Parent/Child
- Empress He [831] → Liu Bian [1312] Parent/Child; Emperor Ling [1351] → Liu Bian Parent/Child
- Lady Wang [3599] → Liu Xie [1434] Parent/Child; Liu Bian ↔ Liu Xie Sibling (half)
- Empress Dowager Dong [403] → Emperor Ling [1351] Parent/Child; → Liu Xie Grandparent
- Liu Chang [3602] → Emperor Ling Parent/Child; Liu Chang ↔ Empress Dong Husband/Wife
- Emperor Huan [3582] → Emperor Ling Parent/Child (adoptive)
- Dong Chong [411] ↔ Empress Dong [403] Sibling
- Sun Tzu [3594] → Sun Jian [2081] Ancestor/Descendant
- Xu Chang [2623] → Xu Hao [3597] Parent/Child

From ch4_audit.json (3):
- Lü Boshe [1546] ↔ Cao Song [130] Sworn Brother
- Liu Bian [1312] → Consort Tang [2148] Husband/Wife
- Yuan Wei [3012] → Yuan Shao [3006] Pibling/Nibling

From ch3_audit.json (5):
- Yuan Shao [3006] ↔ Yuan Shu [3008] Sibling; Cui Yi [3609] ↔ Cui Lie [331] Sibling
- Ding Yuan [398] → Lü Bu [1547] Parent/Child (adoptive); Dong Zhuo [444] → Lü Bu Parent/Child (adoptive)
- Dong Zhuo [444] ↔ Dong Min [429] Sibling

## Report-only findings (need manual action, no apply-fixes op exists)

From ch1:
- "Yuan Mountains" (ch1 ¶6 omen scene) has no Location row — create via
  admin UI + associate if wanted.
- ~~Liu Bei's father needs a Character row~~ DONE — Ren created Liu
  Hong [3849]. Five OTHER Liu Hong rows exist (1351–1355); 1352 (Jin,
  Zhongjia) vs 1353 (bare "Han politician") look like possible dupes.

From ch2:
- **Liu Xian [3601] is a duplicate of Liu Xie [1434]** — created from
  ch2's "Liu Xian" spelling of the future Emperor Xian. After applying
  ch2_audit.json it has no chapters; soft-delete it via the admin UI.
- **Liang Da [1263] cleanup is multi-chapter.** His alias 'Tai'
  false-matched every "X Tai" name (Zhou Tai, Chen Tai, Zheng Tai...),
  giving him 21 bogus chapter associations + book_mention_count 106 +
  a Koei portrait of Taigong Wang(!). ch2_audit.json fixes the global
  alias ('Tai' → 'Liang Tai') and removes the ch2 association. In-range
  chapters (15, 44, 48, 49, 51, 55) get checked as their audits come
  up; OUT-OF-RANGE chapters still carrying the bogus association +
  'Liang Da,Tai' keywords: 61, 67, 68, 75, 76, 78, 82, 83, 84, 107,
  109, 110, 111, 114. The portrait should also be reviewed manually.
- "Jiedu" (Liu Chang's fief, ¶81) has no Location row.
- Event "Massacre of the Eunuchs" [11] is associated to ch2 but never
  inline-tags (the massacre itself is ch3; ch2 is the plotting). Left
  associated on purpose — sidebar context. ch3_audit.json adds it to
  ch3 too.

From ch4 (and the sex sweep):
- **data/fixes/sex_audit.json** fixes sex=female on 73 characters (every
  Empress/Lady/Consort row, Diao Chan, Da/Xiao Qiao, Cai Yan, Fu Shou,
  Lü Zhi, Sun Ren, Duan Qiaoxiao). Apply it early — relationship labels
  (Mother/Daughter/Wife) resolve from Character.sex.
- Possible duplicate female rows to eyeball: Empress Bian [33] vs Lady
  Bian [35]; Empress Zhen [3344] vs Lady Zhen [3345]; Lady Wuyang
  [3608] vs Lady of Wuyang [2502] (2502 is the one associated to ch2).
- No Location row for the inn / Chenggao hamlet needed; nothing missing.

From ch3:
- No "in-law" relationship type exists. Ch3 states Niu Fu and Li Ru are
  both Dong Zhuo's sons-in-law — worth a Parent-in-law/Child-in-law
  type if wanted; skipped for now.
