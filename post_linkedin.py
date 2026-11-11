#!/usr/bin/env python3
"""Repo-root wrapper for linkedin-publisher/scripts/post_linkedin.py.

The implementation lives in the portable skill bundle so there is a single source
of truth. This file loads that source into its own namespace: the module globals
stay the ones a caller patches (for example
``unittest.mock.patch.object(post_linkedin, 'ComposioAPI', FakeAPI)``), because
``main()`` resolves its names in this same dictionary.
"""

import sys
from pathlib import Path

_BUNDLE = Path(__file__).resolve().parent / 'linkedin-publisher' / 'scripts' / 'post_linkedin.py'
if not _BUNDLE.is_file():
    sys.stderr.write('ERROR: skill bundle missing. Expected ' + str(_BUNDLE)
                     + ' — restore the linkedin-publisher/ folder.\n')
    raise SystemExit(1)
_source = _BUNDLE.read_text(encoding='utf-8')
globals()['__skill_root__'] = str(_BUNDLE.parent.parent)
exec(compile(_source, str(_BUNDLE), 'exec'), globals())
