from django.apps import AppConfig


class GlobalConfigConfig(AppConfig):
    name = 'global_config'

    def ready(self):
        import global_config.signals  # noqa: F401
