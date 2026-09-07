# mutint-api

MutInt's public read API, at `/api/`.

It publishes an instance's **public projects**: projects, experiments, populations and samples,
each sample's `.gd` and VCF, the experiment's reference, a gene list, and a cross-experiment
lookup. Read-only, no sign-in, public projects only — and a private project is *absent* rather
than forbidden.

**The consumer in mind is a local MutInt pulling a public one's data**, which is why the payloads
speak MutInt's vocabulary and carry what the importer needs (`source_name`, the `A-F-I-R`
coordinate) rather than links into pages.

It is optional on purpose: a private deployment leaves this repo out of `.gitmodules` and has no
`/api/` at all.

## Installing

```bash
git submodule add ../mutint-api mutint-api
```

MIT licensed. See [mutint-core](https://github.com/mutint/mutint-core) for the platform.
