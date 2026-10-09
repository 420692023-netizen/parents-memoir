# Contributing

Thanks for your interest in **Parents Memoir / 时光家传**.

This project helps ordinary families turn oral history, letters and photos into a
dignified printed biography. The hard part is never the writing — it is asking the
right question, knowing when to leave a blank, and not letting a machine invent a
detail. Contributions that serve those three things are very welcome.

---

## What we need most

| Area | Why it matters | Difficulty |
| --- | --- | --- |
| **New language branches** (`i18n/<locale>/`) | The method is universal; the interview questions, dialect handling and dating clues are not. | Medium |
| **Interview question libraries** per era / occupation | "What did you do at the supply cooperative?" beats "tell me about your life". | Easy |
| **Photo-dating clue tables** (clothing, objects, hairstyles by decade & country) | This is how you date an undated photo. Currently China-focused. | Medium |
| **Handwriting / dialect knowledge** | Per-person glyph profiles; regional variant characters. | Hard |
| **Scripts** | Standard library only, no new runtime dependencies. | Medium |

---

## Language branches

The canonical version is **Chinese (Simplified)** in the repository root.
Translations live under `i18n/<locale>/`:

```
i18n/
  en/          English
  zh-Hant/     Traditional Chinese (also useful for dialect/variant characters)
  ja/          Japanese
  ko/          Korean
  <your locale>/
```

### What to translate

| File | Translate? | Notes |
| --- | --- | --- |
| `SKILL.md` | Yes | The core. Keep all red-line rules intact. |
| `references/interview-questions.md` | Yes | **Do not translate literally.** Re-write the questions so they fit your country's eras, institutions and occupations. A literal translation produces questions no elder in your country can answer. |
| `references/photo-archive.md` | Partly | The workflow is universal; the "dating clue table" must be rebuilt for your country. |
| `references/handwriting-profile.md` | Partly | Chinese-specific parts (字辈 / generation names) have no direct equivalent — replace them with whatever naming convention your culture uses, or drop the section and say so. |
| `scripts/*.py` | No | Language-neutral. Keep code and comments in English. |
| `README.en.md`, `README.md` | Optional | A README in your language is welcome. |

### Rules that must survive translation

1. **Never resolve uncertainty.** The `[?]` marker and the "flag, never guess"
   rule are the heart of this project. A translation that lets the model fill in
   a blank confidently is a regression.
2. **Never invent a reason.** Every "because…" in an archive must trace back to a
   quoted sentence. If it cannot, it must be downgraded to "待核 / unverified".
3. **Never infer state backwards in time.** Record "since year X" — do not
   describe someone's youth using how they are in old age.
4. **No real people.** Examples must stay generic ("某年某月", "甲某乙某",
   "境外乙"). Never add a real name, address or letter quote.
5. **The AI is a prompter, not an arbiter.** Suggestions are suggestions; the
   family member decides.

### How to submit

1. Fork the repository.
2. Create `i18n/<locale>/` and add your files.
3. Open a PR titled `i18n(<locale>): add <language> branch`.
4. In the PR body, state: which files you translated, which parts you
   **re-wrote for local context** (interview questions, dating tables), and
   which sections you intentionally dropped as not applicable.

We will not merge a literal machine translation of the interview questions.
Re-writing them for your country is the actual contribution.

---

## Script contributions

- **Python 3.9+, standard library only.** Pillow is the single optional
  dependency, used only by the photo branch.
- Read-only with respect to user directories unless explicitly asked.
- No hardcoded family data inside the scripts: person lists, generation-name
  templates and correction state are all loaded at runtime from the user's own
  project (`素材库/项目配置.md`). If a script cannot find them, it must fail
  loudly — never silently guess.
- Add or update a check in `pack.py` when you add a new class of mistake.

---

## License

By contributing you agree that your contribution is licensed under the
**MIT License** (see `LICENSE`), and that you keep the copyright notice intact.
