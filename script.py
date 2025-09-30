# author: realcopacetic

from resources.lib.script.actions import *
from resources.lib.shared.utilities import parse_params, sys


class Main:
    def __init__(self, *args):
        try:
            self.params = dict(arg.split("=", 1) for arg in args)
            self._parse_params()
        except:
            self.params = {}
        function = eval(self.params["action"])
        function(**self.params)

    def _parse_argv(self) -> None:
        try:
            self.params = parse_params(sys.argv)
        except Exception as e:
            log(f"_parse_argv error: {e}")
            self.params = {}
        log(f"Script initialized with params: {self.params}")


if __name__ == "__main__":
    Main(*sys.argv[1:])
