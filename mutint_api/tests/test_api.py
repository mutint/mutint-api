"""The public read API, end to end, over a real import.

One public experiment imported through the breseq-folder fixture -- two samples in one
population at two time points, a SNP shared by both and an AMP in one -- beside a private
experiment that must never appear. Every endpoint is read as an anonymous client, because
that is who the API is for.

Runs only in an assembled project: `./mutint test mutint_api`.
"""

import json
import shutil
import tempfile

from django.test import TestCase, override_settings

from mutint_experiment.models import Experiment, Project
from mutint_import import breseq_folder
from mutint_import.tests import breseq_fixture
from mutint_sample.models import Mutation, Sample

GD_FIXED = """#=GENOME_DIFF\t1.0
#=REFSEQ\ttest_ref
SNP\t1\t.\ttest_ref\t100\tA\tgene_name=thrA\tgene_product=aspartokinase\tfrequency=1
AMP\t2\t.\ttest_ref\t120\t10\t3\tgene_name=thrA\tgene_product=aspartokinase\tfrequency=1
"""

GD_POLYMORPHIC = """#=GENOME_DIFF\t1.0
#=REFSEQ\ttest_ref
SNP\t1\t.\ttest_ref\t100\tA\tgene_name=thrA\tgene_product=aspartokinase\tfrequency=0.42
"""


class _Fixture(TestCase):
    def setUp(self):
        self.store = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.store, True)
        patcher = override_settings(MUTINT_STORE_DIR=self.store)
        patcher.enable()
        self.addCleanup(patcher.disable)

        self.experiment = self._import("Public", "pub", public=True)
        self.private = self._import("Private", "priv", public=False)
        self.samples = list(Sample.objects.filter(
            population__experiment=self.experiment).order_by("time_point"))

    def _import(self, project_name, experiment_name, *, public):
        drop = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, drop, True)
        breseq_fixture.write_sample(drop, "1-1-1-1", gd_text=GD_FIXED)
        breseq_fixture.write_sample(drop, "1-2-1-1", gd_text=GD_POLYMORPHIC)
        breseq_folder.import_breseq_folders(
            drop, project_name=project_name, experiment_name=experiment_name,
            owner_name="tester")
        experiment = Experiment.objects.get(name=experiment_name)
        Project.objects.filter(pk=experiment.project_id).update(is_public=public)
        return Experiment.objects.get(pk=experiment.pk)

    def get(self, path, **params):
        response = self.client.get(path, params)
        return response.status_code, (json.loads(response.content)
                                      if response["Content-Type"].startswith("application/json")
                                      else response.content.decode())


class IndexTestCase(_Fixture):
    def test_the_index_names_the_versions_and_the_collections(self):
        from mutint_common.version import __version__
        status, body = self.get("/api/")
        self.assertEqual(200, status)
        self.assertEqual(__version__, body["mutint"])
        self.assertEqual(1, body["api"])
        self.assertEqual("/api/projects/", body["projects_url"])
        self.assertEqual(["min_freq", "max_freq", "ignore_genes"], body["filter_parameters"])

    def test_get_only(self):
        self.assertEqual(405, self.client.post("/api/projects/").status_code)


class ProjectsTestCase(_Fixture):
    def test_only_public_projects_are_listed(self):
        status, body = self.get("/api/projects/")
        self.assertEqual(200, status)
        self.assertEqual(["Public"], [p["name"] for p in body["projects"]])
        self.assertEqual([self.experiment.id], body["projects"][0]["experiment_ids"])

    def test_a_private_project_is_absent_not_forbidden(self):
        status, body = self.get("/api/projects/%d/" % self.private.project_id)
        self.assertEqual(404, status)
        self.assertIn("error", body)

    def test_a_project_lists_its_experiments(self):
        status, body = self.get("/api/projects/%d/" % self.experiment.project_id)
        self.assertEqual(200, status)
        self.assertEqual([self.experiment.id], [e["id"] for e in body["experiments"]])
        self.assertEqual("/api/experiments/%d/" % self.experiment.id,
                         body["experiments"][0]["url"])

    def test_a_deleted_project_is_absent(self):
        from django.utils import timezone
        Project.objects.filter(pk=self.experiment.project_id).update(deleted_at=timezone.now())
        self.assertEqual([], self.get("/api/projects/")[1]["projects"])
        self.assertEqual(404, self.get("/api/experiments/%d/" % self.experiment.id)[0])


class ExperimentsTestCase(_Fixture):
    def test_only_public_experiments_are_listed(self):
        status, body = self.get("/api/experiments/")
        self.assertEqual([self.experiment.id], [e["id"] for e in body["experiments"]])

    def test_an_experiment_carries_its_populations_and_samples(self):
        status, body = self.get("/api/experiments/%d/" % self.experiment.id)
        self.assertEqual(200, status)
        self.assertEqual("pub", body["name"])
        self.assertEqual(["1"], [p["name"] for p in body["populations"]])
        self.assertEqual(["1-1-1-1", "1-2-1-1"], [s["source_name"] for s in body["samples"]])
        self.assertEqual([1.0, 2.0], [s["time_point"] for s in body["samples"]])
        self.assertIsNone(body["ancestor_sample_id"])
        self.assertFalse(body["locked"])

    def test_a_sample_payload_has_what_an_importer_needs_and_no_page_links(self):
        status, body = self.get("/api/samples/%d/" % self.samples[0].id)
        self.assertEqual(200, status)
        for key in ("source_name", "population", "time_point", "name", "sample_type",
                    "breseq", "sequencing", "curation", "gd_url", "vcf_url"):
            self.assertIn(key, body)
        self.assertEqual("clonal", body["sample_type"])
        self.assertNotIn("url", body)
        self.assertNotIn("aledb.org", json.dumps(body))

    def test_the_ancestor_is_listed_and_named(self):
        self.experiment.set_ancestor(self.samples[0])
        status, body = self.get("/api/experiments/%d/" % self.experiment.id)
        self.assertEqual(self.samples[0].id, body["ancestor_sample_id"])
        self.assertIn(self.samples[0].id, [s["id"] for s in body["samples"]])

    def test_a_private_sample_is_absent(self):
        private = Sample.objects.filter(population__experiment=self.private).first()
        self.assertEqual(404, self.get("/api/samples/%d/" % private.id)[0])


class MutationsTestCase(_Fixture):
    def test_an_experiments_mutations_are_matrix_shaped(self):
        status, body = self.get("/api/experiments/%d/mutations/" % self.experiment.id)
        self.assertEqual(200, status)
        self.assertEqual({("SNP", 100), ("AMP", 120)},
                         {(m["mutation_type"], m["start_position"]) for m in body["mutations"]})
        self.assertEqual(3, body["count"], "two calls of the SNP, one of the AMP")
        snp = [m for m in body["mutations"] if m["mutation_type"] == "SNP"][0]
        frequencies = sorted(c["frequency"] for c in body["calls"] if c["mutation_id"] == snp["id"])
        self.assertEqual([0.42, 1.0], frequencies)
        self.assertEqual("thrA", snp["gene"])

    def test_the_readers_filter_applies_and_a_bad_one_is_a_400(self):
        status, body = self.get("/api/experiments/%d/mutations/" % self.experiment.id,
                                min_freq="50")
        self.assertEqual(200, status)
        self.assertEqual(2, body["count"], "the 42% call is hidden")
        status, body = self.get("/api/experiments/%d/mutations/" % self.experiment.id,
                                min_freq="lots")
        self.assertEqual(400, status)
        self.assertIn("error", body)

    def test_the_experiment_is_published_whole_ancestor_included(self):
        self.experiment.set_ancestor(self.samples[0])
        status, body = self.get("/api/experiments/%d/mutations/" % self.experiment.id)
        self.assertEqual(3, body["count"])
        self.assertEqual(self.samples[0].id, body["ancestor_sample_id"])

    def test_the_cross_experiment_lookup_subtracts_ancestry(self):
        status, body = self.get("/api/mutations/", gene="thrA")
        self.assertEqual(200, status)
        self.assertEqual(3, body["count"], "the private experiment's calls are absent")
        self.assertEqual({self.experiment.id}, {m["experiment_id"] for m in body["mutations"]})
        self.experiment.set_ancestor(self.samples[0])
        status, body = self.get("/api/mutations/", gene="thrA")
        self.assertEqual(0, body["count"], "everything in the ancestor is subtracted")

    def test_the_lookup_needs_a_criterion_and_ids_must_be_ids(self):
        self.assertEqual(400, self.get("/api/mutations/")[0])
        self.assertEqual(400, self.get("/api/mutations/", project="seven")[0])
        status, body = self.get("/api/mutations/", experiment=str(self.private.id))
        self.assertEqual(0, body["count"])

    def test_the_lookup_can_name_a_strain_and_a_project(self):
        from mutint_experiment.models import Population
        Population.objects.filter(experiment=self.experiment).update(strain="MG1655")
        self.assertEqual(3, self.get("/api/mutations/", strain="MG1655")[1]["count"])
        self.assertEqual(0, self.get("/api/mutations/", strain="REL606")[1]["count"])
        self.assertEqual(3, self.get("/api/mutations/",
                                     project=str(self.experiment.project_id))[1]["count"])


class GenesTestCase(_Fixture):
    def test_genes_are_listed_once_across_public_projects(self):
        status, body = self.get("/api/genes/")
        self.assertEqual(200, status)
        self.assertEqual(["thrA"], body["genes"])

    def test_an_ignored_gene_is_not_listed(self):
        self.assertEqual([], self.get("/api/genes/", ignore_genes="thrA")[1]["genes"])


class FilesTestCase(_Fixture):
    def test_a_samples_gd_is_the_importable_file(self):
        response = self.client.get("/api/samples/%d/gd" % self.samples[0].id)
        self.assertEqual(200, response.status_code)
        self.assertEqual('attachment; filename="1-1-1-1.gd"', response["Content-Disposition"])
        text = response.content.decode()
        self.assertTrue(text.startswith("#=GENOME_DIFF\t1.0"))
        self.assertIn("SNP", text)
        self.assertIn("\t100\t", text)

    def test_a_private_samples_files_are_absent(self):
        private = Sample.objects.filter(population__experiment=self.private).first()
        self.assertEqual(404, self.client.get("/api/samples/%d/gd" % private.id).status_code)
        self.assertEqual(404, self.client.get("/api/samples/%d/vcf" % private.id).status_code)

    def test_the_reference_endpoint_says_where_the_files_are(self):
        status, body = self.get("/api/experiments/%d/reference/" % self.experiment.id)
        self.assertEqual(200, status)
        self.assertEqual(self.experiment.id, body["experiment_id"])
        self.assertIn("contigs", body)
        if body["contigs"]:
            self.assertEqual("/mutations/reference/%d/fasta" % self.experiment.id, body["fasta_url"])
        else:
            self.assertIsNone(body["fasta_url"])
