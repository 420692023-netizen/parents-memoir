# Parents Memoir · 时光家传

> Write a real biography of an ordinary person — your parents, a grandparent,
> or yourself.
> **The AI works as an interviewer, not a ghostwriter.** The pen stays with the
> family; the AI asks, follows up, organises, and reminds you to verify.

A **Skill** for WorkBuddy and similar coding agents. It turns "I should really
record my parents' story" into an executable pipeline: personalised interview
questions → timeline → digitising handwritten letters → fidelity-first drafting
→ four-layer review → print-ready book.

---

## Why this exists

Recording a parent's life is hard for three reasons, none of which is prose:

1. **You can't get them to talk.** "What was your childhood like?" gets you three
   sentences. "What did the accounting office smell like in winter?" gets you an
   hour.
2. **Memory is unreliable — and so is AI.** A confidently invented detail is
   worse than a blank.
3. **People disappear.** Once the elders are gone, the handwriting is unreadable
   and nobody knows who is in the photographs, the trail is permanently broken.

So: a **100-question interview library** tuned to the person's era and trade;
**uncertainty is always left blank** and flagged with candidates; and dedicated
workflows for letters, photographs and documents.

---

## What it does

| Branch | What happens |
| --- | --- |
| **Interview** | Question sets generated from the elder's decade, occupation and dialect (100-question library) |
| **Timeline** | Transcripts are placed on a life timeline; anything uncertain is marked `[?]`, never guessed |
| **Letters / handwriting** | Uncertain characters are **flagged, never silently corrected**; your corrections accumulate into a per-person glyph profile, so the same handwriting gets easier every time |
| **Photographs** | Originals paired with AI-restored copies, duplicates removed, people anchored by inscriptions and letter clues (**suggestions only**), undated photos dated by clothing, objects and blooming seasons |
| **Documents** | Hash-level duplicate detection across formats, plus a person-mention scan against your name registry |
| **Drafting** | Direct quotes preserved, dialect kept, no AI clichés — then a 4-layer review (facts / voice / anti-AI-voice / family read-through) |
| **Delivery** | Manuscript, print-ready book layout (PDF), and a family memory archive |

---

## Three red lines

Each of these comes from a real failure in a real project — the archive once
contained a sentence that said the opposite of what happened.

1. **The machine prompts; it does not decide.** Glyph similarity, logic and
   "common sense" have all been wrong here. Every conclusion is offered as
   `[?]` + candidates + context. Never written into the text as fact.
2. **Reasons are quoted, never invented.** Any "because…" in the archive must
   trace to an actual sentence the person said. If it can't, it is downgraded to
   "unverified". A fabricated reason reads smoothly and fits the conclusion —
   only checking word by word against the original reveals it.
3. **Every state carries a date.** Disability, health, ability and job titles are
   recorded as "since year X". Never infer someone's youth from how they are in
   old age. (We once identified the wrong person that way.)

---

## Install

```bash
# WorkBuddy
git clone https://github.com/420692023-netizen/parents-memoir.git \
  ~/.workbuddy/skills/parents-memoir
```

Or download `parents-memoir.zip` from the Releases page and unzip to the same
location.

**Requirements**: Python 3.9+. All scripts use the **standard library only**.
Pillow (`pip install pillow`) is optional and used solely by the photo branch.

---

## Language

The canonical version is **Simplified Chinese** (`SKILL.md`), because that is the
material it was built on: Chinese family letters, generation-name (字辈) rules,
and kinship terms that shift over time.

**The method is not language-bound.** Interviewing, timelines, flagging
uncertainty, dating photographs and the four-layer review work in any language.
What does need localising is the content: interview questions must fit your
country's eras and institutions, and photo-dating clues must fit its clothing
and objects.

- Translations and new language branches are very welcome: `i18n/<locale>/`
- See **[CONTRIBUTING.md](CONTRIBUTING.md)** — note that we do **not** accept a
  literal translation of the interview questions. Rewriting them for your
  country's elders is the actual contribution.

---

## Privacy by design

- **No data inside the scripts.** Name registries, generation-name templates and
  correction state are loaded at runtime from the user's own project file
  (`素材库/项目配置.md`). A different family works without editing any code.
- **No names are ever pre-filled.** Templates generate empty placeholders. The AI
  must not infer or write a real person's name from memory or context.
- **All bundled examples are generic** ("某年某月", "甲某乙某", "境外乙"),
  containing no identifiable information about any real person.

---

## License

**MIT** (see `LICENSE`). Free to use, modify, redistribute and use commercially;
the only obligation is to keep the copyright and licence notice.

The name "时光家传 / Parents Memoir" is **not** covered by the MIT grant — MIT
does not convey trademark rights.

---

## Author

**龚建新 (Gong Jianxin)** — 420692023@qq.com

Built by iterating on a real family archive; the rules in it (generation-name
validation, kinship-term timelines, dual-hash duplicate detection, date-tagged
questioning) all came out of mistakes made there. Issues and PRs welcome.
