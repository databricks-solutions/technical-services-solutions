"""
Informatica PS connector
"""


class InformaticaPS(object):
    def __init__(self, app_name: str) -> None:
        self.app_name = app_name

    def get_app_name(self) -> str:
        return self.app_name
