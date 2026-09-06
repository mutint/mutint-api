# CLAUDE.md — mutint-api

MutInt's public read API, at `/api/`. Optional: a deployment that does not list this repo in
`.gitmodules` has no API. `docs/using/api.md` is the endpoint reference; this file is the
reasoning.

**It faces another MutInt.** The vision is that a local instance pulls a public one's data
into itself, so the vocabulary is MutInt's own (projects, experiments, populations, samples,
mutations, calls) and what a sample publishes is what the Add page accepts: its `.gd`
(`mutint_import.gd_import.export_gd_text`), its VCF (`mutint_import.vcf_export`), and the
experiment's reference through core's own FASTA and GFF3 routes. The payloads carry
`source_name`, the `A-F-I-R` coordinate as imported, because that is how the importer
places a file. No payload links into a page.

**It was `mutint_interop_query` in core**: six endpoints shaped for one other website, POSTs
for lookups, and search links back to aledb.org baked into every row. None of that survives,
including the path; there is no `/interop-query/` alias. What did survive is the posture its
last rewrite established, and it is worth keeping: public projects only; the reader's filter
parameters, parsed by core's `ViewFilter`, unfiltered by default and a 400 when unparseable
rather than a quiet "everything"; and no key ever emitted under two names.

**Public means `Project.is_public`, checked here, not through `permissions.py`.** An
anonymous caller already gets `ROLE_READ` on a public project there, so the two agree; the
direct check is so that a private project is *absent* (404) rather than forbidden (403), and
the API cannot be used to learn what exists. Soft-deleted projects and experiments are absent
too.

**Two ancestor rules, deliberately.** `experiments/<id>/mutations/` is a pull and publishes
the record whole, ancestor included, with `ancestor_sample_id` beside it. `mutations/?gene=`
is a question across experiments and subtracts designated ancestry the way Search does.
The docs say so; a caller who wants the other behaviour has the other endpoint.

**GET only, and the `api_` prefix on route names.** Core has `reference_view`, `sample_bam`
and the like; a plugin's route names must not shadow a page's.

## Tests

`./mutint test mutint_api` from an assembled project; core has no plugin discovery. The
fixture is a real breseq-folder import through `mutint_import.tests.breseq_fixture`, made
public, beside a private one that must never appear.
