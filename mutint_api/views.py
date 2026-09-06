"""MutInt's public read API: what a public instance publishes, for another instance to pull.

Every endpoint is a GET that answers JSON -- or, for a sample's `.gd` and VCF, the file --
and every one sees **public projects only**: `Project.is_public`, and nothing about who is
asking. There is no authentication, because there is nothing here that the site does not
already show an anonymous visitor; a private project is absent rather than forbidden, so
the API cannot be used to learn that one exists.

**The consumer in mind is another MutInt.** A local instance pulls a public one's data:
list the projects, walk an experiment's populations and samples, take each sample's `.gd`
or VCF and the experiment's reference, and hand them to the same importer the Add page
uses. So the payloads use MutInt's own vocabulary and carry the fields an importer needs --
a sample's `source_name` (its `A-F-I-R` coordinate as imported), its time point, its
population's strain -- and never a link into a page.

Two things a caller chooses, in the query string, the way a reader chooses them on a page:

- **The filter.** `min_freq`, `max_freq` and `ignore_genes` are the pages' own parameters,
  parsed by the same `ViewFilter`, so the API and the UI cannot disagree about what
  `min_freq=20` means. Unfiltered by default. Anything unparseable is a 400 rather than a
  quiet "everything": a caller who sent `min_freq=abc` and got every call back would have a
  wrong answer dressed as a right one.
- **The ancestor.** An experiment's own data (`experiments/<id>/mutations/`) is published
  *whole*, ancestor's calls included, because a pull wants the record and the local instance
  can designate the ancestor itself -- the experiment payload says which sample it is. The
  cross-experiment lookup (`mutations/?gene=`) subtracts designated ancestry, the way Search
  does: it is asking a question about evolution, and an ancestral mutation is the answer to
  a different one.
"""

import logging
import re

from django.http import Http404, HttpResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

from mutint_common.constants import SAMPLE_TYPE_CLONAL, SAMPLE_TYPE_MIXED
from mutint_common.logger import user_extra
from mutint_common.version import __version__
from mutint_experiment import paths
from mutint_experiment.ancestor import exclude_all_ancestry
from mutint_experiment.models import Experiment, Project, live
from mutint_filter.util import filter_mutation_calls, filtered_mutation_call_queryset
from mutint_filter.view_filter import PARAMS as FILTER_PARAMS, ViewFilter
from mutint_import.gd_import import export_gd_text
from mutint_import.vcf_export import export_vcf_text
from mutint_sample import ncbi
from mutint_sample.models import MutationCall, Sample
from mutint_sample.util import get_mutation_call_queryset, get_ordered_reseq_queryset

logger = logging.getLogger(__name__)

API_VERSION = 1

_HTML_TAG_RE = re.compile(r'<[^>]+>')
_GENE_SEP_RE = re.compile(r'[,|;]')
_VALID_GENE_RE = re.compile(r'[A-Za-z0-9]')


class BadRequest(Exception):
    """A caller's mistake, answered with a 400 and the reason."""


# --- the frame every endpoint shares -------------------------------------------------------

def api(fn):
    """GET only; JSON errors with the same shape for 400, 404 and 500."""
    @require_GET
    def wrapped(request, *args, **kwargs):
        try:
            return fn(request, *args, **kwargs)
        except Http404 as missing:
            return JsonResponse({"error": str(missing) or "not found"}, status=404)
        except (BadRequest, ValueError) as bad:
            return JsonResponse({"error": str(bad)}, status=400)
        except Exception:  # noqa: BLE001 -- the API must answer JSON, whatever broke
            logger.exception("api %s broke", request.path, extra=user_extra(request))
            return JsonResponse({"error": "internal error"}, status=500)
    wrapped.__name__ = fn.__name__
    wrapped.__doc__ = fn.__doc__
    return wrapped


def _requested_filter(request):
    """The caller's filter, or None: the three page parameters, parsed by `ViewFilter`."""
    if not any(name in request.GET for name in FILTER_PARAMS):
        return None
    return ViewFilter.from_params(request.GET)


# --- what is public ------------------------------------------------------------------------

def _projects():
    return live(Project.objects.filter(is_public=True)).order_by("name", "id")


def _project(pk):
    project = _projects().filter(pk=pk).first()
    if project is None:
        raise Http404("no public project %s" % pk)
    return project


def _experiments():
    return live(Experiment.objects.filter(project__is_public=True,
                                          project__deleted_at__isnull=True)
                ).select_related("project").order_by("project__name", "name", "id")


def _experiment(pk):
    experiment = _experiments().filter(pk=pk).first()
    if experiment is None:
        raise Http404("no public experiment %s" % pk)
    return experiment


def _samples(experiment):
    # The ancestor too: a pull wants the whole record, and the experiment payload says
    # which sample the ancestor is.
    return get_ordered_reseq_queryset(experiment.id, include_ancestor=True)


def _sample(pk):
    sample = (Sample.objects.filter(pk=pk)
              .select_related("population__experiment__project").first())
    if sample is None or not _is_public(sample.population.experiment):
        raise Http404("no public sample %s" % pk)
    return sample


def _is_public(experiment):
    project = experiment.project
    return (experiment.deleted_at is None and project is not None
            and project.is_public and project.deleted_at is None)


def _public_calls():
    return MutationCall.objects.filter(**{
        paths.to_experiment(paths.FROM_CALL, "project__is_public"): True,
        paths.to_experiment(paths.FROM_CALL, "project__deleted_at__isnull"): True,
        paths.to_experiment(paths.FROM_CALL, "deleted_at__isnull"): True,
    })


# --- payloads ------------------------------------------------------------------------------

def project_payload(project, experiment_ids=None):
    if experiment_ids is None:
        experiment_ids = list(_experiments().filter(project=project)
                              .values_list("id", flat=True))
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "created": project.date.isoformat() if project.date else None,
        "experiment_ids": experiment_ids,
        "url": reverse("api_project", args=[project.id]),
    }


def experiment_payload(experiment):
    return {
        "id": experiment.id,
        "project_id": experiment.project_id,
        "name": experiment.name,
        "notes": experiment.notes or "",
        "doi": experiment.doi or "",
        "created": experiment.date.isoformat() if experiment.date else None,
        "locked": experiment.locked_at is not None,
        "ancestor_sample_id": experiment.ancestor_id,
        "url": reverse("api_experiment", args=[experiment.id]),
        "samples_url": reverse("api_experiment_samples", args=[experiment.id]),
        "mutations_url": reverse("api_experiment_mutations", args=[experiment.id]),
        "reference_url": reverse("api_experiment_reference", args=[experiment.id]),
    }


def population_payload(population):
    return {
        "id": population.id,
        "name": population.name,
        "strain": population.strain or "",
        "species": population.species or "",
        "description": population.description or "",
    }


def sample_payload(sample):
    population = sample.population
    return {
        "id": sample.id,
        "experiment_id": population.experiment_id,
        "population_id": population.id,
        "population": population.name,
        "time_point": sample.time_point,
        "name": sample.name,
        "label": sample.label,
        "description": sample.description or "",
        # The coordinate as it was imported (`A-F-I-R`), which is what a local instance
        # names the file it pulls, so the importer places it the same way.
        "source_name": sample.source_name or "",
        "sample_type": SAMPLE_TYPE_MIXED if sample.is_mixed else SAMPLE_TYPE_CLONAL,
        "is_hypermutator": sample.is_hypermutator,
        "is_contaminated": sample.is_contaminated,
        "is_low_coverage": sample.is_low_coverage,
        # The three supplemental groups core writes, verbatim: what breseq said about
        # itself, how the sample was sequenced, and what a curator noted.
        "breseq": dict(sample.breseq),
        "sequencing": dict(sample.sequencing),
        "curation": dict(sample.curation),
        "bam_stored": sample.bam_stored,
        "coverage_stored": sample.coverage_stored,
        "report_stored": sample.report_stored,
        "gd_url": reverse("api_sample_gd", args=[sample.id]),
        "vcf_url": reverse("api_sample_vcf", args=[sample.id]),
    }


def mutation_payload(mutation):
    return {
        "id": mutation.id,
        "experiment_id": mutation.experiment_id,
        "seq_id": mutation.seq_id or "",
        "start_position": mutation.start_position,
        "end_position": mutation.end_position,
        "mutation_type": mutation.mutation_type,
        "sequence_change": mutation.sequence_change,
        "protein_change": mutation.protein_change or "",
        "gene": mutation.gene or "",
        "gene_name": mutation.gene_name or "",
        "locus_tag": mutation.locus_tag or "",
        "product": mutation.product or "",
        "snp_type": mutation.snp_type or "",
        "mutation_category": mutation.mutation_category or "",
        "feature_length": mutation.feature_length,
        "annotation": mutation.annotation,
    }


def call_payload(call):
    return {
        "id": call.id,
        "mutation_id": call.mutation_id,
        "sample_id": call.sample_id,
        "frequency": call.frequency,
        "present": call.present,
        "source": call.source or "",
    }


def _calls_payload(calls):
    """`{"mutations": [...], "calls": [...]}` -- each mutation once, each call once.

    Matrix-shaped rather than nested, so a mutation carried by forty samples is described
    once and a caller can pivot either way.
    """
    mutations = {}
    rows = []
    for call in calls:
        if call.mutation_id not in mutations:
            mutations[call.mutation_id] = mutation_payload(call.mutation)
        rows.append(call_payload(call))
    return {"mutations": list(mutations.values()), "calls": rows,
            "count": len(rows)}


# --- endpoints -----------------------------------------------------------------------------

@api
def index(request):
    """What this API is, and where its collections are."""
    return JsonResponse({
        "mutint": __version__,
        "api": API_VERSION,
        "projects_url": reverse("api_projects"),
        "experiments_url": reverse("api_experiments"),
        "genes_url": reverse("api_genes"),
        "mutations_url": reverse("api_mutations"),
        "filter_parameters": list(FILTER_PARAMS),
    })


@api
def projects(request):
    experiments_by_project = {}
    for project_id, experiment_id in _experiments().values_list("project_id", "id"):
        experiments_by_project.setdefault(project_id, []).append(experiment_id)
    return JsonResponse({"projects": [
        project_payload(project, experiments_by_project.get(project.id, []))
        for project in _projects()]})


@api
def project(request, pk):
    project = _project(pk)
    return JsonResponse({
        **project_payload(project),
        "experiments": [experiment_payload(e)
                        for e in _experiments().filter(project=project)],
    })


@api
def experiments(request):
    return JsonResponse({"experiments": [experiment_payload(e) for e in _experiments()]})


@api
def experiment(request, pk):
    experiment = _experiment(pk)
    samples = list(_samples(experiment).select_related("population"))
    populations = {}
    for sample in samples:
        populations.setdefault(sample.population_id, sample.population)
    return JsonResponse({
        **experiment_payload(experiment),
        "project": project_payload(experiment.project),
        "populations": [population_payload(p) for p in populations.values()],
        "samples": [sample_payload(s) for s in samples],
    })


@api
def experiment_samples(request, pk):
    experiment = _experiment(pk)
    return JsonResponse({"samples": [
        sample_payload(s) for s in _samples(experiment).select_related("population")]})


@api
def experiment_mutations(request, pk):
    """Every call in the experiment, through the caller's filter, ancestor included."""
    experiment = _experiment(pk)
    view_filter = _requested_filter(request)
    calls = filter_mutation_calls(get_mutation_call_queryset(experiment.id),
                                  view_filter=view_filter)
    return JsonResponse({"experiment_id": experiment.id,
                         "ancestor_sample_id": experiment.ancestor_id,
                         **_calls_payload(calls)})


@api
def experiment_reference(request, pk):
    """The reference's contigs, and where core serves the FASTA and GFF3 themselves."""
    experiment = _experiment(pk)
    contigs = [{
        "id": state["id"],
        "length": state["length"],
        "aliases": state["aliases"],
        "accession": state["accession"],
        "status": state["status"],
        "is_verified": state["is_verified"],
    } for state in ncbi.contig_states(experiment)]
    return JsonResponse({
        "experiment_id": experiment.id,
        "contigs": contigs,
        "fasta_url": reverse("reference_fasta", args=[experiment.id]) if contigs else None,
        "gff3_url": reverse("reference_gff3", args=[experiment.id]) if contigs else None,
    })


@api
def sample(request, pk):
    sample = _sample(pk)
    return JsonResponse({**sample_payload(sample),
                         "population_detail": population_payload(sample.population)})


def _file(text, filename, content_type="text/plain; charset=utf-8"):
    response = HttpResponse(text, content_type=content_type)
    response["Content-Disposition"] = 'attachment; filename="%s"' % filename
    return response


@api
def sample_gd(request, pk):
    """The sample's mutations as a GenomeDiff, the file the Add page imports."""
    sample = _sample(pk)
    return _file(export_gd_text(sample), "%s.gd" % (sample.source_name or sample.id))


@api
def sample_vcf(request, pk):
    """The sample's mutations as VCF -- core's `vcf_export`, byte-for-byte for a call that
    arrived as VCF and regenerated from the reference otherwise."""
    sample = _sample(pk)
    return _file(export_vcf_text(sample), "%s.vcf" % (sample.source_name or sample.id))


def _strip_html(text):
    """breseq writes a gene column like `<i><b>168 genes</b><BR>yjgN`; the name is the tail."""
    if "<BR>" in text:
        text = text.rsplit("<BR>", 1)[-1]
    return _HTML_TAG_RE.sub("", text).strip()


@api
def genes(request):
    """Every gene named by a call in a public project, through the caller's filter."""
    view_filter = _requested_filter(request)
    queryset, _ = filtered_mutation_call_queryset(exclude_all_ancestry(_public_calls()),
                                                  view_filter=view_filter)
    names = set()
    for entry in queryset.values_list("mutation__gene", flat=True).distinct():
        if not entry:
            continue
        for name in _GENE_SEP_RE.split(_strip_html(entry)):
            name = name.strip()
            if name and _VALID_GENE_RE.search(name):
                names.add(name)
    # "Do not list a gene I asked you to ignore" -- a set lookup here, where
    # `gene_is_filtered`'s per-mutation subset rule would be the wrong unit.
    if view_filter is not None and view_filter.genes:
        names -= view_filter.genes_set
    return JsonResponse({"genes": sorted(names), "count": len(names)})


@api
def mutations(request):
    """Calls across every public experiment matching `gene`, `strain`, `project` and/or
    `experiment`, designated ancestry subtracted, through the caller's filter."""
    criteria = {}
    gene = request.GET.get("gene", "").strip()
    strain = request.GET.get("strain", "").strip()
    if gene:
        criteria["mutation__gene__icontains"] = gene
    if strain:
        criteria[paths.to_population(paths.FROM_CALL, "strain")] = strain
    for name, path in (("project", paths.to_experiment(paths.FROM_CALL, "project_id")),
                       ("experiment", paths.to_experiment_id(paths.FROM_CALL))):
        value = request.GET.get(name, "").strip()
        if value:
            if not value.isdigit():
                raise BadRequest("%s must be an id" % name)
            criteria[path] = int(value)
    if not criteria:
        raise BadRequest("give at least one of gene, strain, project, experiment")
    view_filter = _requested_filter(request)
    calls = filter_mutation_calls(exclude_all_ancestry(_public_calls().filter(**criteria)),
                                  view_filter=view_filter)
    samples = {}
    for call in calls:
        if call.sample_id not in samples:
            samples[call.sample_id] = sample_payload(call.sample)
    return JsonResponse({"criteria": {k: request.GET[k] for k in
                                      ("gene", "strain", "project", "experiment")
                                      if request.GET.get(k, "").strip()},
                         "samples": list(samples.values()),
                         **_calls_payload(calls)})
