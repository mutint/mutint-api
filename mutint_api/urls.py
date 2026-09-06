from django.urls import re_path

from mutint_api import views

# Mounted at ^api/ (apps.py). Every route is GET and public-projects-only; see views.py.
# Names carry the `api_` prefix so they cannot collide with the pages' own route names --
# core has `reference_view`, and a plugin must not shadow it.
urlpatterns = [
    re_path(r'^$', views.index, name='api_index'),
    re_path(r'^projects/$', views.projects, name='api_projects'),
    re_path(r'^projects/(?P<pk>\d+)/$', views.project, name='api_project'),
    re_path(r'^experiments/$', views.experiments, name='api_experiments'),
    re_path(r'^experiments/(?P<pk>\d+)/$', views.experiment, name='api_experiment'),
    re_path(r'^experiments/(?P<pk>\d+)/samples/$', views.experiment_samples,
            name='api_experiment_samples'),
    re_path(r'^experiments/(?P<pk>\d+)/mutations/$', views.experiment_mutations,
            name='api_experiment_mutations'),
    re_path(r'^experiments/(?P<pk>\d+)/reference/$', views.experiment_reference,
            name='api_experiment_reference'),
    re_path(r'^samples/(?P<pk>\d+)/$', views.sample, name='api_sample'),
    re_path(r'^samples/(?P<pk>\d+)/gd$', views.sample_gd, name='api_sample_gd'),
    re_path(r'^samples/(?P<pk>\d+)/vcf$', views.sample_vcf, name='api_sample_vcf'),
    re_path(r'^genes/$', views.genes, name='api_genes'),
    re_path(r'^mutations/$', views.mutations, name='api_mutations'),
]
