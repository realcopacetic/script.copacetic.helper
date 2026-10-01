# author: realcopacetic

import sys

from resources.lib.script.actions import REGISTRY
from resources.lib.shared.parser import parse_script_argv

if __name__ == "__main__":
    # A context item gets [addon_id, args] and the clicked item as sys.listitem;
    # args uses RunScript's comma syntax, so action=rate_song,rating=0 works.
    params = parse_script_argv([sys.argv[0], *sys.argv[1].split(",")])
    tag = sys.listitem.getMusicInfoTag()
    year = tag.getMediaType().endswith("year")  # year or originalyear nodes
    REGISTRY[params.pop("action")](
        id=str(tag.getYear() if year else tag.getDbId()),
        type="year" if year else tag.getMediaType(),
        path=sys.listitem.getPath(),
        **params,
    )
