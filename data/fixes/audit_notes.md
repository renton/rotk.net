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
- [x] ch5 — 29 ops (Yue Jing spelling, Li Feng 'Anguo'-in-'Wu Anguo' false positive removed, Hu Zhen junk keyword, Qiao/Julu keywords, 7 relationships incl. Cao/Xiahou clan web, ~18 summary rewrites)
- [x] ch6 — 36 ops (Campaign vs Dong Zhuo event added, Qiao/Yiyang/Great River keywords, ~32 summary rewrites — many had wrong fates: demoted-not-killed, executed ministers, murdered Qiao Mao, Eight Wise Ones mixups)
- [x] ch7 — 33 ops (South Land/Great River assocs, 11 relationships incl. the whole Sun family roll + Liu Biao↔Lady Cai + Kuai brothers, ~20 summary rewrites)
- [x] ch8 — 13 ops (Diao Chan age 16→21 + concubine relationship, Dong Huang nephew, Imperial Rector self-title fix, Great River assoc, sage-citation fixes)
- [x] ch9 — 20 ops (Luoyang assoc removed, Lü Bu–Diao Chan relationship, 18 summary fixes incl. Li Su executed by Lü Bu, plotters vs purge-victims mixups, gate-opening fifth column)
- [x] ch10 — 25 ops (7 missing summaries filled, Nanyang false assoc removed, Cao Song↔Cao De sibling, Bian Rang/Fan Chou/Li Meng/Wang Fang/Liu Dai/Yu Jin summary corrections)
- [x] ch11 — 35 ops (8 missing summaries incl. Lü Bu's, Guan Hai kill credited to Guan Yu not Taishi Ci, Zhao Yun Beihai/Xuzhou mixup, Zhang Miao↔Zhang Chao + Confucius→Kong Rong relationships)
- [x] ch12 — 27 ops (Battle of Yan Province event added, 6 missing summaries, He Man kill credited to Cao Hong, Xue Lan/Zhang Miao fate fixes, Dian Wei/Xiahou Yuan rescue details)
- [x] ch13 — 45 ops (Empress He→Empress Fu wrong-person fix, 11 missing summaries, 2 admin-note 'summaries' replaced, 4 relationships incl. Guo Si/Yang Biao marriages, ~25 summary corrections)
- [x] ch14 — 35 ops (13 missing summaries, Cao Bao is LÜ BU's father-in-law not Zhang Fei's, Xu Huang kills Li Yue not Li Xian and refuses the murder-gift, Li Jue→Li Bie nephew)
- [x] ch15 — 37 ops (Liang Da 'Tai'-in-'Zhou Tai' removal, 9 missing summaries, Yan Yu dup-note replaced, Young Overlord kill fixes, 4 relationships incl. Sun Ce↔Zhou Yu sworn)
- [x] ch16 — 42 ops (12 missing summaries, Lady Yan/Lady Zhou wrong-person fix, 2 dup-note summaries replaced, 8 relationships incl. Cao Cao→Cao Ang and the Lü Bu household)
- [x] ch17 — 45 ops (Ji Chang 'Xiahou' junk keyword, 13 missing summaries incl. Wang Hou's borrowed head, Ji Ling/Zhang Xun/Lei Xu not killed, Duan Wei/Wu Xi kill credits, Dian Wei→Dian Man)
- [x] ch18 — 43 ops (You Province bare-'You' keyword fix, 8 missing summaries, Taishan bandits mislabeled as Lü Bu's eight generals, Jia Xu's double victory, 4 relationships incl. Liu Bei's marriages)
- [x] ch19 — 28 ops (6 missing summaries incl. Lü Bu's end and Liu An, Hou Cheng steals Red Hare not the halberd, Taishan chiefs at Xiao Pass, Zhang Yang assassination subplot, Chen Deng's triple-cross)
- [x] ch20 — 35 ops (Liu Hong wrong-person fix #2: Emperor Ling removed, Liu Bei's father [3849] added; Emperor Xian summary restored to Liu Xie; Yang Biao victim-not-conspirator; 14 missing summaries; Fu Wan→Empress Fu + Liu Xiong→Liu Hong relationships)
- [x] ch21 — 31 ops (9 missing summaries, Zhao Yun premature-rejoin fix, Lu Zhao wrong-side fix, Yuan Shu's on-page death, Guan Yu's ruse credited, Yuan Shu→Yuan Yin nephew)
- [x] ch22 — 21 ops (bare You/Ji/Yan keyword fixes, 6 missing summaries, Zhao Yan manifesto assoc added, Xun Yu's takedown, Tian Feng premature jailing, Chunyu Qiong ch30 spillover)
- [x] ch23 — 24 ops (19 missing summaries incl. Ji Ping the martyr-physician and the whole Mi Heng diatribe cast, Zhang Xiu dup-note replaced, Liu Ye envoy credit)
- [x] ch24 — 21 ops (3 missing summaries, Sun Qian/Jian Yong/Mi Zhu flight mixups, Tian Feng not yet jailed, scabies-refusal added to Yuan Shao, 3 relationships incl. Dong Cheng↔Consort Dong)
- [x] ch25 — 15 ops (4 missing summaries, Tian Feng jailed THIS chapter, Yan Liang two-not-three kills, ch26 spillovers pulled back, Cheng Yu's double trap)
- [x] ch26 — 17 ops (Battle of Dushi Ford event gets its first chapter, letter-carrier fixed Chen Zhen not Sun Qian, Cai Yang/Cao Cao ch27 spillovers, 2 missing summaries)
- [x] ch27 — 23 ops (13 missing summaries for the five-passes cast, Wang Zhi empty keywords, invented 'pass-edict' removed from Cao Cao/Guan Yu, Hu Hua→Hu Ban relationship)
- [x] ch28 — 20 ops (5 missing summaries incl. Zhou Cang's debut, Guo Chang farm-host fix, Guan Ping adoption relationships, Cai Yang→Qin Qi nephew)
- [x] ch29 — 29 ops (17 missing summaries incl. Yu Ji the haunting saint, Hua Xin envoy/governor fix, Guo Jia's prophecy, Qiao-sister marriages: Sun Ce↔Da Qiao, Zhou Yu↔Xiao Qiao)
- [x] ch30 — 22 ops (12 missing summaries, Jia Xu's invented council quote fixed, Wuchao raid roster corrected, catapult 'Rumblers' restored, Han Meng/Chunyu Qiong fates fixed)
- [x] ch31 — 44 ops (Yin Kui wrong-person fix: politician 2905 removed, astrologer 2906 added; Liu Bang added as 'Founder of Han'; 5 Yuan-family relationships; Gao Lan/Liu Pi/Shi Huan on-page deaths; Tian Feng suicide-sequence fix; bare-'You' keyword restriction; 6 missing + ~25 thin/wrong summaries)
- [x] ch32 — 44 ops (Xu Province false-positive assoc removed, bare-'You' restriction, 10 missing summaries incl. Peng Ji's death arc and the Lü brothers, Shen Pei's north-facing execution, Wang Xiu wrong-master fix, Feng Li/Li Mu/Ma Yan/Yin Kai 'minor' fixes, Cao Pi ch33 spillover pulled back, 4 relationships)
- [x] ch33 — 46 ops (Battle of Ye event added to ch32, Xu Province + Bronze Bird Tower false assocs removed, Wuhuan Chu keywords fixed from bare 'Chu', Mao Dun/Xin Ping/Guo Tu on-page deaths, Yuan Tan died at Nanpi not Pingyuan, Gao Gan killed by Wang Yan at Shanglu, Wang Xiu mourner scene, 3 relationships incl. Cao Pi↔Lady Zhen)
- [x] ch34 — 28 ops (9 missing summaries incl. the three Cai brothers and Su Dongpo, Kuai Liang is-dead fix, Liu Qi/Sun Qian wrong-content fixes, Yi Ji's three warnings, Zhao Yun's Dilu capture, 8 relationships: Jingzhou heir family + Cai brothers + Lady Gan→Liu Shan)
- [x] ch35 — 16 ops (Xu Shu/Shan Fu debut summary was missing, Lü brothers' on-page deaths, Cai Mao death-sentence-and-reprieve, Liu Biao letter-not-visit fix, Pang Tong 'named as Young Phoenix' fix, Pang Degong→Pang Tong uncle relationship)
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

From ch35_audit.json (1):
- Pang Degong [1726] → Pang Tong [1739] Pibling/Nibling

From ch34_audit.json (8):
- Cai Mao [68] ↔ Lady Cai [61] Sibling; Cai Mao ↔ Cai He [3767] + ↔ Cai Zhong [3768] + ↔ Cai Xun [3769] Sibling
- Liu Biao [1313] → Liu Qi [1395] + → Liu Cong [1323] Parent/Child
- Lady Cai [61] → Liu Cong [1323] Parent/Child
- Lady Gan [592] → Liu Shan [1401] Parent/Child

From ch33_audit.json (3):
- Gongsun Du [650] → Gongsun Kang [657] Parent/Child
- Yuan Xi [3013] ↔ Lady Zhen [3345] Husband/Wife
- Cao Pi [121] ↔ Lady Zhen [3345] Husband/Wife

From ch32_audit.json (4):
- Ju Shou [1107] → Ju Gu [3755] Parent/Child
- Xin Ping [2608] ↔ Xin Pi [2607] Sibling
- Lü Xiang [1573] ↔ Lü Kuang [1565] Sibling
- Shen Pei [1925] → Shen Rong [1926] Pibling/Nibling

From ch31_audit.json (5):
- Yuan Shao [3006] → Yuan Xi [3013] + → Yuan Shang [3005] Parent/Child
- Yuan Shao [3006] ↔ Lady Liu [1299] Husband/Wife
- Lady Liu [1299] → Yuan Shang [3005] Parent/Child
- Yuan Shao [3006] → Gao Gan [604] Pibling/Nibling

From ch29_audit.json (3):
- Sun Ce [2060] → Da Qiao [1794] Husband/Wife; Zhou Yu [3466] → Xiao Qiao [1796] Husband/Wife
- Da Qiao [1794] ↔ Xiao Qiao [1796] Sibling

From ch28_audit.json (4):
- Cai Yang [72] → Qin Qi [3734] Pibling/Nibling
- Guan Ding [3737] → Guan Ping [698] + → Guan Neng [3738] Parent/Child
- Guan Yu [704] → Guan Ping [698] Parent/Child (adoptive)

From ch24_audit.json (3):
- Dong Cheng [410] ↔ Consort Dong [402] Sibling
- Liu Xie [1434] → Consort Dong [402] Husband/Wife
- Yuan Shao [3006] → Yuan Tan [3011] Parent/Child

From ch21_audit.json (1):
- Yuan Shu [3008] → Yuan Yin [3021] Pibling/Nibling

From ch20_audit.json (2):
- Fu Wan [579] → Fu Shou/Empress Fu [578] Parent/Child
- Liu Xiong [3701] → Liu Hong [3849] Parent/Child

From ch18_audit.json (4):
- Liu Bei [1311] → Lady Mi [1677] + → Lady Gan [592] Husband/Wife
- Mi Zhu [1682] ↔ Lady Mi [1677] Sibling; ↔ Mi Fang [1678] Sibling

From ch17_audit.json (1):
- Dian Wei [376] → Dian Man [375] Parent/Child

From ch16_audit.json (8):
- Cao Cao [86] → Cao Ang [80] Parent/Child; → Cao Amin [3688] Pibling/Nibling
- Zhang Ji [3134] → Zhang Xiu [3233] Pibling/Nibling; ↔ Lady Zhou [3689] Husband/Wife
- Lü Bu [1547] ↔ Lady Yan [2761] + ↔ Lady Cao [3687] Husband/Wife
- Cao Bao [82] → Lady Cao [3687] Parent/Child; Chen Gui [216] → Chen Deng [207] Parent/Child

From ch15_audit.json (4):
- Yan Baihu [2762] ↔ Yan Yu [2794] Sibling; Liu Dai [1325] ↔ Liu Yao [1452] Sibling
- Sun Ce [2060] ↔ Zhou Yu [3466] Sworn Brother; Wu Jing [2466] → Sun Ce Pibling/Nibling

From ch14_audit.json (1):
- Li Jue [1185] → Li Bie [3678] Pibling/Nibling

From ch13_audit.json (4):
- Fu De [565] ↔ Fu Shou/Empress Fu [578] Sibling
- Guo Si [753] → Lady Qiong [3666] Husband/Wife; Yang Biao [2803] → Lady Kai [3667] Husband/Wife
- Li Jue [1185] → Li Xian [1229] Pibling/Nibling

From ch11_audit.json (2):
- Zhang Miao [3174] ↔ Zhang Chao [3082] Sibling
- Confucius [3659] → Kong Rong [1117] Ancestor/Descendant

From ch10_audit.json (1):
- Cao Song [130] ↔ Cao De [3658] Sibling

From ch9_audit.json (1):
- Lü Bu [1547] → Diao Chan [3641] Husband/Wife

From ch8_audit.json (2):
- Dong Zhuo [444] → Dong Huang [422] Pibling/Nibling
- Dong Zhuo [444] → Diao Chan [3641] Husband/Wife (concubine)

From ch7_audit.json (11):
- Sun Jian [2081] → Sun Ce [2060], Sun Quan [2105], Sun Yi [2121], Sun Kuang [2088],
  Sun Lang [2089], Sun Ren [3639] Parent/Child; → Sun Hu [3640] Parent/Child (adoptive)
- Sun Jian ↔ Sun Jing [2084] Sibling; Gongsun Zan [664] ↔ Gongsun Yue [663] Sibling
- Liu Biao [1313] → Lady Cai [61] Husband/Wife; Kuai Liang [1129] ↔ Kuai Yue [1131] Sibling

From ch5_audit.json (7):
- Bao Xin [20] ↔ Bao Zhong [3618] Sibling
- Xiahou Ying [3616] → Xiahou Dun [2535] Ancestor/Descendant
- Xiahou Dun [2535] ↔ Xiahou Yuan [2556] Cousin
- Cao Cao [86] ↔ Cao Ren [123], ↔ Cao Hong [100], ↔ Xiahou Dun [2535], ↔ Xiahou Yuan [2556] Cousin

From ch4_audit.json (3):
- Lü Boshe [1546] ↔ Cao Song [130] Sworn Brother
- Liu Bian [1312] → Consort Tang [2148] Husband/Wife
- Yuan Wei [3012] → Yuan Shao [3006] Pibling/Nibling

From ch3_audit.json (5):
- Yuan Shao [3006] ↔ Yuan Shu [3008] Sibling; Cui Yi [3609] ↔ Cui Lie [331] Sibling
- Ding Yuan [398] → Lü Bu [1547] Parent/Child (adoptive); Dong Zhuo [444] → Lü Bu Parent/Child (adoptive)
- Dong Zhuo [444] ↔ Dong Min [429] Sibling

## Report-only findings (need manual action, no apply-fixes op exists)

From ch33:
- **Peng An has no Character row** — Yuan Tan's champion, slain by Xu
  Huang in a few bouts before Nanpi (ch33 ¶44). Create + associate to
  ch33 if wanted.

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

From ch29:
- **Duplicate Lu Fan rows**: Lü Fan [1554] (Sun Ce's adviser since
  ch15) vs Lu Fan [3742] (proposes Yu Ji's rain wager, ch29) — same
  man 呂範. Merge via admin UI.

From ch20:
- **Duplicate Emperor Jing rows**: ch1 used Liu Qi [3590]; ch20
  associates Liu Qi [3586] (kw 'Emperor Jing') — same emperor, two
  rows. The applied ch1 relationship (3590 → Liu Sheng) sits on the
  other row. Merge via admin UI.

From ch15:
- Yan Yu [2794] carried the literal summary "(duplicate record)" — find
  and merge its twin (another 嚴輿 row).

From ch14:
- Cao Bao's daughter is Lü Bu's wife ("my son-in-law... Lu Bu") — again
  blocked by the missing in-law relationship type.
- "Yewang" (Yang Feng's camp, ¶4) has no Location row.

From ch13:
- **Duplicate Yang Feng rows**: [2816] (associated to ch13) carried the
  literal summary "(duplicate record; same person - see 2815)". Merge /
  soft-delete one. Same for **Zhang Ji [3134]** whose summary was
  "(duplicate record)" — find its twin (likely another 張濟/張既 row).
- Empress He [831] was associated to ch13 via bare 'Empress' keyword —
  she died in ch4; ch13's empress is Fu Shou [578]. Fixed in the file.
- Dongjian, Dayang, Shanbei (flight waypoints) have no Location rows.

From ch10:
- **Duplicate Liu Xiu rows**: ch6 associates Liu Xiu [3577], ch10
  associates Liu Xiu [1438] — both are the Latter Han founder. Merge /
  soft-delete one via admin UI.

From ch7:
- Cai Mao is Liu Biao's brother-in-law (stated twice) — no in-law
  relationship type exists (same gap as Dong Zhuo's sons-in-law).
- Sun Jian's two wives (Lady Wu and her sister) are unnamed in ch7
  prose; Lady Wu [2450] left unassociated — no usable needle.
- Location aliases are single-word for many rows ('Wen', 'Shang',
  'You', 'Ji', 'Jing') — these are the root cause of the location
  false-positive associations seen in ch2/ch3. Worth an eventual
  sweep, but per-chapter keywords are the safe fix for now.

From ch6:
- Liu Xie's ch6 keyword 'Emperor' also matches "the First Emperor" (Qin
  Shi Huang) 4× and "the Emperor's mother" in the seal-lore flashback
  (¶69–70) — needs per-snippet MatchExclusions via
  /admin/chapter-associations; a keyword change would lose the many
  legit "the Emperor" mentions.
- "Fan Chong" (Red Eyebrows leader, ¶19) has no Character row — minor.
- Kuai Liang ↔ Kuai Yue sibling relationship deferred until a chapter
  whose prose states it.

From ch5:
- "Liangdong" (Sun Jian's fallback camp, ¶60) has no Location row.
- Li Feng's [1160] keyword set includes 'Anguo' (likely his courtesy
  name) — it false-matches "Wu Anguo"; only ch5 affected (Wu Anguo
  appears nowhere else).

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
