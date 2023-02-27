#!/usr/bin/python
# coding: utf-8


import sys
from resources.lib.script.actions import *
from resources.lib.utilities import *


class Main:
    def __init__(self, *args):
        try:
            self.params = dict(arg.split('=', 1) for arg in args)
        except:
            self.params = {}
        function = eval(self.params['action'])
        function(**self.params)


if __name__ == '__main__':
    Main(*sys.argv[1:])
