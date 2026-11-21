# Sample inputs for the demo eval set

We have no past SOWs, so we write 3 to 5 sample inputs in different domains and forms, each with gaps
planted on purpose and an answer key. The eval measures how many planted gaps the agents find and how
many false gaps they raise.

| File | Form | Domain | Status |
| --- | --- | --- | --- |
| `one_line_classifieds.txt` | One-line idea | Classifieds | Input ready; answer key to write |
| `ecommerce_brief.md` + `ecommerce_brief.answers.yaml` | Short brief | E-commerce | Ready |
| Full Word SOW | Word document | Business tool | To write (senior person) |
| Reference website link | URL | Any | To pick |

Run the eval: `python -m sdlc_agent.evals samples/*.answers.yaml`

## Answer key format (`<sample>.answers.yaml`)

See `ecommerce_brief.answers.yaml` for a full example.

- `input`: the sample (`kind` text, file or url; file paths are relative to the key).
- `intake_answers`: what a client would type into the intake form. Leave planted gaps unanswered,
  or the questionnaire fills them and Stage 1 rightly does not report them.
- `gaps`: the planted gaps, each with an id, type (sow, nfr, domain_checklist, competitor), text and
  `match` terms.
- `requirements`: what a senior analyst would extract, with `match` terms.
- `also_valid`: real gaps that were not planted. They are not counted as false gaps.

`match` is a list of term groups: an item matches when every group has at least one term at the start
of a word in the gap (description or client question) or requirement text, case-insensitive. Add a
test wording to `tests/test_evals.py` for each planted gap so a change to the terms cannot silently
break matching.

Gaps that match neither a planted gap nor `also_valid` are listed in the report under "review". After
a human decides, add real ones to `also_valid`; what is left counts as false gaps.
