import sys
from resources.lib.helper import *

########################

class Main:
    def __init__(self, *args):
        self.params = {}
        for arg in args:
            if '=' in arg:
                key, value = arg.split('=', 1)
                self.params[key] = value.strip('\'').strip('"')
            else:
                self.params[arg] = True
        function = eval(self.params['action'])
        function(**self.params)

if __name__ == '__main__':
    Main(*sys.argv[1:])
