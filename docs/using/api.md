# The API

A MutInt instance with the `mutint-api` component installed publishes its **public projects**
at `/api/`, read-only and without signing in. Nothing is published that a visitor to the site
could not already see: private projects are absent, not forbidden.

It exists so that one MutInt can pull another's data. Walk the projects, take an
experiment's samples, fetch each sample's `.gd` or VCF and the experiment's reference, and
hand them to the Add page (or `./mutint import`) of a local instance.

Every endpoint answers JSON except the two file downloads. Errors answer JSON too:
`{"error": "..."}` with status 400 for a bad request, 404 for anything not public.

| Endpoint | What it answers |
|---|---|
| `GET /api/` | the MutInt version, the API version, and where the collections are |
| `GET /api/projects/` | every public project, with its experiment ids |
| `GET /api/projects/<id>/` | one project and its experiments |
| `GET /api/experiments/` | every public experiment |
| `GET /api/experiments/<id>/` | one experiment, its populations and its samples |
| `GET /api/experiments/<id>/samples/` | the samples alone |
| `GET /api/experiments/<id>/mutations/` | every mutation and every call in the experiment, matrix-shaped |
| `GET /api/experiments/<id>/reference/` | the reference's contigs, and where the FASTA and GFF3 are served |
| `GET /api/samples/<id>/` | one sample |
| `GET /api/samples/<id>/gd` | the sample's mutations as a GenomeDiff file |
| `GET /api/samples/<id>/vcf` | the sample's mutations as VCF |
| `GET /api/genes/` | every gene named by a call in a public project |
| `GET /api/mutations/?gene=&strain=&project=&experiment=` | calls across public experiments matching the criteria |

## Filtering

`min_freq`, `max_freq` and `ignore_genes` are accepted wherever calls are answered, and mean
exactly what they mean on the site's pages: the same parser reads both. Nothing is filtered
unless you ask. A value that cannot be parsed is a 400, not an unfiltered answer.

## The ancestor

`experiments/<id>/mutations/` publishes the experiment **whole**, the designated ancestor's
calls included; the experiment payload names that sample in `ancestor_sample_id`, so a local
instance can designate it too. The cross-experiment lookup at `mutations/` subtracts
designated ancestry, as Search does: it asks what evolved, and an ancestral mutation is the
answer to a different question.

## Pulling an experiment

```bash
base=https://example.org/api
curl -s $base/experiments/ | jq '.experiments[] | {id, name}'
curl -s $base/experiments/7/ | jq '.samples[] | {id, source_name}'
curl -s -o 1-500-1-1.gd $base/samples/123/gd
curl -s -o reference.fasta https://example.org/mutations/reference/7/fasta
```

Name each `.gd` by the sample's `source_name` and the importer places it under the same
population and time point.
