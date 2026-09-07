from django.apps import AppConfig


class ApiConfig(AppConfig):
    """MutInt's public read API, at /api/.

    Optional on purpose: it publishes every public project to anyone who asks, which is
    exactly what a public instance wants and a private one may not. A deployment that does
    not list this repo in `.gitmodules` has no `/api/` at all.

    It was `mutint_interop_query` in core -- six endpoints shaped for one other website,
    with search links back to aledb.org baked in. This is the same idea turned to face the
    consumer MutInt actually has in mind: **another MutInt**, pulling a public instance's
    data into a local one. So the vocabulary is MutInt's own (projects, experiments,
    populations, samples, mutations, calls), and what a sample publishes is what the Add
    page accepts: its `.gd`, its VCF, and the experiment's reference.
    """

    name = 'mutint_api'

    def ready(self):
        from django.urls import include, re_path
        from mutint_common.about_registry import register_about_section
        from mutint_common.plugin_registry import register_plugin_urlpatterns
        from mutint_api.version import __version__

        # No nav entry: the API is for programs, and the About section is where a person
        # reading the site learns it exists.
        register_plugin_urlpatterns([
            re_path(r'^api/', include('mutint_api.urls')),
        ])
        register_about_section(self, name='mutint-api', version=__version__,
                               template='about/sections/mutint_api.html')
