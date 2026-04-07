# author: realcopacetic

import faulthandler

import xbmcvfs

_fh_path = xbmcvfs.translatePath(
    "special://profile/addon_data/script.copacetic.helper/faulthandler.log"
)
_fh_file = open(_fh_path, "a", buffering=1)
faulthandler.enable(file=_fh_file)
faulthandler.dump_traceback_later(20, repeat=True, file=_fh_file)


from resources.lib.plugin.main import Main

if __name__ == "__main__":
    Main()
